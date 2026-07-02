# Pods — Full Diagnosis & Fix Plan
## All Three Problems: ModuleNotFoundError, Single-GPU, Architecture

---

## Problem 1 — `ModuleNotFoundError: No module named 'pods.models.manager'`

### Root Cause

This is 100% a **setuptools editable install stubs bug**. It was literally listed as Bug #15 in `TODO.md` and marked ✅ — but the actual fix was **never applied to `pyproject.toml`**.

Setuptools ≥ 64 has two editable install modes:

| Mode | How it works | Subpackages added after install |
|------|-------------|--------------------------------|
| `strict` (default) | generates `.pth` stub files at install time | **NOT VISIBLE** |
| `compat` | works like a symlink to repo root | Always visible |

When you first installed, the stub files were generated for whatever subpackages existed at that time. Later `pods/models/` was added (or the stubs got stale). The gateway imports `pods.models.manager` at startup → 403 crash.

The fix is **two lines**, both of which TODO.md says are done but aren't:

**Fix 1 — `pyproject.toml`** (add the `[tool.setuptools]` section):
```toml
[tool.setuptools]
editable-mode = "compat"

[tool.setuptools.packages.find]
where = ["."]
include = ["pods*"]
```

**Fix 2 — `install.sh`** (already has `--reinstall` but needs `--force-reinstall` to regenerate stubs):
```bash
# Line 83 — change to:
uv pip install --python "${VENV_PYTHON}" --quiet --force-reinstall -e "${REPO_DIR}"
```

After applying both: `cd ~/.pods-src && uv pip install --force-reinstall -e . && uvicorn pods.gateway.app:app ...` — the import will work.

**Why `--reinstall` wasn't enough**: `--reinstall` reinstalls the package but reuses the existing stubs. `--force-reinstall` regenerates everything from scratch with the new `editable-mode = "compat"`.

---

## Problem 2 — Model Loads but Only Uses One GPU (Sharding Not Working)

### The Full Chain of What Needs to Happen for Multi-GPU

```
Worker machine                          Coordinator machine
──────────────────                      ──────────────────
pods join <link>                        pods init <name>
  → registers in state.json              → gateway starts (port 8080)
  → agent starts (port 8082)             → (no agent started here)
  → agent sends IMMEDIATE heartbeat    
  → HeartbeatThread fires every 30s   
                                        pods model load qwen32b
                                          → _online_workers() checks state.json
                                          → POSTs to worker:8082/internal/start-rpc
                                          → rpc-server starts on worker (port 50052)
                                          → TCP probe confirms 50052 reachable
                                          → llama-server starts with --rpc worker:50052
                                          → coordinator GPU + worker GPU = sharded
```

There are **four independent failure points** in this chain. All four can cause "coordinator-only / single GPU" silently.

---

### Failure Point A — The Startup Race (Most Likely Your Problem)

`pods join` does `subprocess.Popen(agent)` and immediately returns. The agent process takes 1–3 seconds to import uvicorn, bind port 8082, and send its first heartbeat.

```python
# join.py - the Popen is fire-and-forget
subprocess.Popen([sys.executable, "-m", "uvicorn", "pods.agent.server:app", ...])
click.echo("✓ Joined pod.")  # printed BEFORE agent is listening
click.echo("  Run 'pods attach' to start inference backend.")
```

If you run `pods model load` on the coordinator within 2–3 seconds of the worker running `pods join`, the POST to `worker:8082/internal/start-rpc` hits a port that isn't listening yet. The request times out. Worker is skipped. `rpc_hosts = []`. Single GPU.

**Fix in `pods/cli/join.py`** — probe the agent port before returning:

```python
import time

# After the Popen that starts the agent:
with open(LOGS_DIR / "agent.log", "a") as log:
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "pods.agent.server:app",
         "--host", "0.0.0.0", "--port", "8082", "--log-level", "warning"],
        stdout=log, stderr=log,
    )

# Wait for agent to be ready before telling user to proceed
click.echo("  Waiting for local agent to start...")
from ..network.probe import tcp_probe
deadline = time.time() + 15
while time.time() < deadline:
    if tcp_probe("127.0.0.1", 8082, timeout=0.5):
        click.echo("  ✓ Agent ready on port 8082")
        break
    time.sleep(0.5)
else:
    click.echo("  ⚠ Agent didn't start within 15s — check ~/.pods/logs/agent.log", err=True)
```

---

### Failure Point B — `_online_workers` Cutoff Too Tight at Join Time

The worker registers at T=0. The coordinator checks `_online_workers` at T+Xs. The cutoff is 90 seconds from `last_seen`. But `last_seen` is only updated when heartbeats arrive at the gateway. The **initial registration** sets `last_seen = now`, so a freshly-joined worker WILL pass the cutoff check.

However: if the worker's `last_seen` in `state.json` is from a previous session (worker was joined, went offline, and `pods join` ran again with the same `node_id`), the old `last_seen` may be >90s ago. The re-join flow re-registers with a new `last_seen`, so this should be fine. But **only if** `/internal/register` actually updates `last_seen` for existing nodes.

```python
# routes_internal.py register() — BUG: doesn't update last_seen for re-joins
def _mutate(state):
    existing_ids = {m.node_id for m in state.members}
    if payload.node_id not in existing_ids:
        state.members.append(member)   # Only adds NEW members
    # If node_id ALREADY EXISTS, last_seen is NOT updated!
```

**Fix in `pods/gateway/routes_internal.py`**:

```python
def _mutate(state):
    now = datetime.now(timezone.utc)
    existing_ids = {m.node_id for m in state.members}
    if payload.node_id not in existing_ids:
        state.members.append(member)
    else:
        # Update existing member's last_seen on re-join
        for m in state.members:
            if m.node_id == payload.node_id:
                m.last_seen = now
                m.tailscale_ip = payload.tailscale_ip  # IP may have changed
                break
```

---

### Failure Point C — `attach.py` Passes Empty Config to FallbackOrchestrator

```python
# attach.py - THIS IS WRONG
engine_name, engine = FallbackOrchestrator().start_best_engine({})
```

The empty `{}` config means `LlamaCppEngine.start()` reads `config.get("mode", "worker")` → `"worker"` → starts `rpc-server`. This happens to be correct for worker machines. But there's a deeper issue: **the coordinator also runs `pods attach` in some workflows**, which would then call `_start_llama_server({})` → `KeyError: 'model_path'` → crash.

**Fix in `pods/cli/attach.py`**:

```python
role = config.get("role", "worker")

if role == "coordinator":
    click.echo("Coordinator node: inference started via 'pods model load', not attach.")
    click.echo("Run 'pods model load <name>' to start inference.")
    return

engine_name, engine = FallbackOrchestrator().start_best_engine({"mode": "worker"})
```

---

### Failure Point D — Port 50052 Not Reachable Across Tailscale

The TCP probe `_wait_rpc_reachable(w.tailscale_ip)` hits `worker_tailscale_ip:50052`. Even if Tailscale is connected and the agent (8082) responds, the **rpc-server on 50052 might be blocked by the worker's firewall** (UFW, iptables). Port 8082 is confirmed open (the `/start-rpc` POST worked), but 50052 is a different port.

rpc-server binds `0.0.0.0:50052` but the Tailscale interface needs to be explicitly allowed in some distros.

**What to check / fix diagnostically** — add better logging in `_start_rpc_on_workers`:

```python
# After the TCP probe fails, log the actual error:
if not _wait_rpc_reachable(w.tailscale_ip):
    print(
        f"  [pods] ✗ Worker {w.name} TCP probe failed: {w.tailscale_ip}:{RPC_PORT}\n"
        f"         Possible causes:\n"
        f"         1. Firewall blocking port 50052 (run: sudo ufw allow 50052/tcp)\n"
        f"         2. rpc-server crashed immediately after start\n"
        f"         3. Tailscale relay adding too much latency (run: pods ping)\n"
        f"         Check: ~/.pods/logs/rpc-server.log on the worker"
    )
    continue
```

---

### The Sharding Architecture Itself IS Correct

llama.cpp's `--rpc` flag is real distributed inference. The coordinator's GPU handles the first layers and final output, workers handle intermediate layers. The GGUF does NOT need to be on worker machines — the coordinator distributes weights over the network. This is all set up correctly in `_start_llama_server`:

```python
cmd = [str(LLAMA_SERVER), "--model", model_path, "--host", "127.0.0.1", "--port", "8081", "-ngl", "99"]
if rpc_hosts:
    cmd += ["--rpc", ",".join(rpc_hosts)]  # e.g. --rpc 100.0.0.2:50052,100.0.0.3:50052
```

If `rpc_hosts` is empty due to any of the above failures, this becomes single-GPU. No architectural fix needed — just fix the four failure points above.

---

## Problem 3 — Should You Ditch Tailscale?

### Short Answer: Not Now, But Plan For It

Tailscale is deeply embedded:

| What uses it | Coupling level |
|---|---|
| `internal_auth.py` hardcodes `host.startswith("100.")` | High |
| `state.json` stores `tailscale_ip` field | High |
| `get_ip()` calls `tailscale ip -4` binary | Medium |
| `preflight.py` checks `tailscale status` | Medium |
| `join.py` optionally calls `tailscale up` | Low |

Replacing Tailscale is a **medium refactor (~200 lines), not a rewrite**. The path is:

1. Rename `tailscale_ip → node_ip` in schema + all references
2. Replace `get_ip()` with a configurable function that tries: env var `PODS_NODE_IP`, then `hostname -I | awk '{print $1}'`, then falls back to `tailscale ip -4`
3. Replace `host.startswith("100.")` in `internal_auth.py` with a configurable trusted CIDR list read from config.json
4. Make preflight Tailscale check a warning not a block when `PODS_SKIP_TAILSCALE=1`

However, **Tailscale is giving you real value**: NAT traversal, encryption, stable IPs across reboots. If your machines are on the **same LAN** (dorm network, same switch), you can bypass Tailscale with just the LAN IPs and the refactor above. If they're on different networks (different dorms, home + hostel), you need Tailscale or something equivalent.

**Recommendation**: If all your GPUs are on the same LAN right now, do the `node_ip` refactor and add `PODS_SKIP_TAILSCALE=1` env support. Don't write custom network scripts — you'd be reinventing Tailscale's NAT traversal and encryption with more bugs.

---

## Problem 4 — Actual Race Conditions

### RC1 — `load()` Reads Without File Lock (Benign)

`store.load()` reads `state.json` without acquiring `_write_lock` or `_file_lock`. While `store.update()` is doing the `tmp → os.replace()` dance in another process, `load()` might read either the old or new file. `os.replace()` is atomic on Linux (POSIX rename), so the read always gets a complete file. Pydantic validates it. Backup recovery catches corruption. **This race is safe by design.**

### RC2 — Multiple `store.update()` From Gateway Threads (Safe)

The gateway process handles requests in async coroutines, but `_record_usage()` runs as a `BackgroundTask` (a thread) and `_restart_llamacpp` runs in a `threading.Thread`. Both call `store.update()`. Inside `update()`, `_write_lock` (a `threading.RLock`) serializes these within the same process. Then `_file_lock` (fcntl) serializes across processes (gateway vs agent). **Safe.**

### RC3 — Worker Re-registers During Model Load (Real Race, Low Impact)

Timeline:
```
T=0  Worker sends heartbeat → coordinator updates last_seen
T=1  Coordinator runs _start_rpc_on_workers, sends POST to worker:8082
T=2  Worker's network hiccups → worker's next heartbeat fails
T=3  Worker re-runs pods join (reconnect flow) → /internal/register called
T=4  register() adds a DUPLICATE member entry (if node_id differs)
```

The `register()` check is `if payload.node_id not in existing_ids`. If the worker generates a new `node_id` (no existing config.json), it gets added as a second member with the same `tailscale_ip`. The old member still has `last_seen` from T=0, and `_online_workers` might include BOTH entries → two entries in `rpc_hosts` for the same machine → llama-server fails to connect to the second (same port).

**Fix in `pods/gateway/routes_internal.py`** — also deduplicate by IP:

```python
def _mutate(state):
    now = datetime.now(timezone.utc)
    # Remove any stale entry for this tailscale_ip (handles re-joins with new node_id)
    state.members = [
        m for m in state.members
        if m.node_id == payload.node_id or m.tailscale_ip != payload.tailscale_ip
    ]
    existing_ids = {m.node_id for m in state.members}
    if payload.node_id not in existing_ids:
        state.members.append(member)
    else:
        for m in state.members:
            if m.node_id == payload.node_id:
                m.last_seen = now
                break
```

### RC4 — `_restart_llamacpp` and `_record_usage` Both Write Model State (Real, Fixable)

`_restart_llamacpp` sets `model.reloading = True`, then later sets `model.loaded = True` and `model.loaded_pid = new_pid`. Meanwhile, incoming requests check `target.reloading` in `routes_external.py`. If a heartbeat sweep happens between these two writes and removes a worker from `state.members`, the reloaded model gets a stale `worker_nodes` list.

This is handled: `_restart_llamacpp` calls `_start_rpc_on_workers(state)` at restart time, getting fresh workers. **Safe enough for current scale.**

---

## Complete Fix List for Claude Code

### Priority 1 — Fixes the Import Crash

```
1. pyproject.toml
   Add: [tool.setuptools] section with editable-mode = "compat"

2. install.sh  
   Change: --reinstall to --force-reinstall
```

### Priority 2 — Fixes Single-GPU (All four failure points)

```
3. pods/cli/join.py
   After Popen(agent): probe 127.0.0.1:8082 with 15s timeout before printing success

4. pods/gateway/routes_internal.py → register()
   On re-join: update last_seen and tailscale_ip for existing node_id
   Also: deduplicate by tailscale_ip to prevent ghost members

5. pods/cli/attach.py
   Read role from config; return early if coordinator; pass {"mode": "worker"} to FallbackOrchestrator

6. pods/models/manager.py → _start_rpc_on_workers()
   On TCP probe failure: print actionable message with firewall/log suggestions
```

### Priority 3 — Polish

```
7. pods/platform/setup.py → download_and_install_binaries()
   Move _asset_keywords() call above network fetch (fixes 1 failing test)

8. pods/inference/detector.py
   Delete — dead code, never imported, out of sync with fallback.py

9. pods/models/registry.py
   Add "llama3-8b" alias

10. pyproject.toml → [tool.pytest.ini_options]
    Add filterwarnings = ["ignore::DeprecationWarning"]
```

### Priority 4 — Tailscale Decoupling (Do Later, Before Dynamic Sharding)

```
11. pods/state/schema.py: rename tailscale_ip → node_ip
12. pods/network/tailscale.py: add get_node_ip() that checks PODS_NODE_IP env first
13. pods/internal_auth.py: replace 100.x hardcode with configurable trusted_cidrs from config.json
14. pods/preflight.py: make Tailscale checks warnings not blocks when PODS_SKIP_TAILSCALE=1
```

---

## On Dynamic Sharding (Your Next Move)

The current architecture is **static sharding** — workers are discovered at `pods model load` time and locked in. If a new GPU comes online after the model is loaded, it's not used until you `pods model unload` + `pods model load` again (or a mid-session join triggers `_restart_llamacpp`).

For dynamic sharding you need:
- A pool manager that tracks available GPU memory across nodes
- Layer assignment logic (not just binary include/exclude per node)
- Hot-swap: redistribute layers without full model reload (llama.cpp RPC doesn't support this yet)
- The `reloading` flag + 503 pattern you already have is the right foundation

The mid-session worker join flow (`/internal/attach` → `_restart_llamacpp`) is already your dynamic sharding skeleton. Fix the four bugs above first so the static case works reliably, then that same infrastructure becomes the basis for the dynamic pool.

---

## Claude Code Handoff Prompt

```
Read this file first. Then fix issues in this exact order:

PHASE 1 (fixes the import crash — do this first):
1. pyproject.toml: add [tool.setuptools] section with editable-mode = "compat"
2. install.sh: change --reinstall to --force-reinstall on the uv pip line

PHASE 2 (fixes single-GPU / sharding):
3. pods/cli/join.py: after Popen(agent), probe 127.0.0.1:8082 with 15s timeout before printing success
4. pods/gateway/routes_internal.py register(): on re-join update last_seen + tailscale_ip; deduplicate members by tailscale_ip  
5. pods/cli/attach.py: read role from config.json; return early for coordinators; pass {"mode": "worker"} to FallbackOrchestrator
6. pods/models/manager.py _start_rpc_on_workers(): improve TCP probe failure message with firewall/log suggestions

PHASE 3 (test & polish):
7. pods/platform/setup.py: move _asset_keywords() above network fetch in download_and_install_binaries()
8. Delete pods/inference/detector.py (dead code)
9. pods/models/registry.py: add "llama3-8b" alias for "llama8b"
10. pyproject.toml: add filterwarnings = ["ignore::DeprecationWarning"] to pytest options

Run `python -m pytest tests/ -q` after each phase. Target: 160/160 passing.
After all fixes: test the actual flow with two machines to confirm sharding works.
```