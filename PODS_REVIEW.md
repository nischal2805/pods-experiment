# Pods Codebase Review & Claude Code Fix Brief

**Date**: July 2, 2026  
**Commit**: HEAD of `main` (59 commits)  
**Test run**: 159 passed, **1 failed**, 1 warning  

This document is the single handoff for Claude Code. It covers every real problem found across all 70+ source files, ranked by impact. The existing `CODE_REVIEW.md` in the repo is largely **stale** — most of its "critical" issues are already fixed. This replaces it.

---

## 1. Test Suite Status

### The One Failing Test

**File**: `tests/test_setup.py::test_download_unsupported_platform`

**What it tests**: Calling `download_and_install_binaries(PlatformInfo(os="windows", ...))` should raise `PlatformError("Unsupported platform")`.

**Why it fails**: `download_and_install_binaries()` fetches the GitHub API **first** (line 103–112), then calls `_asset_keywords(platform_info)` (line 116), which is where the Windows error is raised. With no network mock in the test, it hits `api.github.com` and gets a 403, producing a "Failed to fetch" error instead of "Unsupported platform".

**Root cause**: Wrong ordering — platform guard comes after network I/O.

**Fix**:  
In `pods/platform/setup.py`, move the `_asset_keywords()` call and its validation to the **top** of `download_and_install_binaries()`, before any network access:

```python
def download_and_install_binaries(platform_info: PlatformInfo) -> None:
    # Guard FIRST — before touching the network
    keywords = _asset_keywords(platform_info)   # raises PlatformError for windows

    print("Fetching latest llama.cpp release info...")
    try:
        req = urllib.request.Request(GITHUB_API, headers={"User-Agent": "pods-cli"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read())
    except Exception as e:
        raise PlatformError(
            "Failed to fetch llama.cpp release info",
            reason=str(e),
            suggestion="Check your internet connection",
        )

    tag = release["tag_name"]
    assets = release.get("assets", [])
    url = _find_asset(assets, keywords)
    # ... rest unchanged
```

**Test fix**: The test itself is correct. No change needed there.

---

## 2. Real Bugs (Not in CODE_REVIEW.md / Not Yet Fixed)

### Bug A — File Handle Leak in `pods/cli/init.py` and `pods/cli/join.py`

**Severity**: Medium (resource leak, not a crash)  
**Status**: Partially addressed in inference engines (`with open`), but NOT in CLI launchers.

`init.py` line ~65 and `join.py` line ~95:
```python
with open(LOGS_DIR / "gateway.log", "a") as log:
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", ...],
        stdout=log, stderr=log,
    )
# The `with` block exits here and closes the fd on the PARENT side.
# The child inherits it, so the subprocess keeps writing.
# BUT: the parent fd is immediately closed after Popen returns — this is actually correct.
```

Actually re-reading the code, the `with open(...) as log:` pattern used in `init.py` / `join.py` is fine — the child inherits the fd, and the parent's fd closes but the child's copy stays open. **No fix needed here**; this was a false alarm in CODE_REVIEW.md. The `_start_rpc_server` / `_start_llama_server` methods also use `with open(...)` correctly now. ✅

### Bug B — `ModelManager.load()` Does Not Close Log File on Failure Path

**Severity**: Low  
**File**: `pods/inference/llamacpp.py`, `_start_llama_server`

The `with open(...) as log` + `Popen` in `_start_llama_server` is correct. But `_wait_for_health()` raises `InferenceError` on timeout. When it raises, the `except` block in `_start_llama_server` kills the process and re-raises. The `with` block's `__exit__` runs, so the log fd closes correctly. **No actual bug here**. ✅

### Bug C — `attach.py` Always Starts Engine in Empty Config Mode

**Severity**: High — **this is a real, unfixed bug**  
**File**: `pods/cli/attach.py`, line 22

```python
engine_name, engine = FallbackOrchestrator().start_best_engine({})
```

The config dict passed to `FallbackOrchestrator.start_best_engine` is empty `{}`. This flows into `InferenceEngine.start(config)`. For `LlamaCppEngine.start()`, `config.get("mode", "worker")` defaults to `"worker"`, which starts `rpc-server`. But `pods attach` is called both on coordinator machines (which should run `llama-server` in coordinator mode) and worker machines (which should run `rpc-server`).

The actual machine role is in `~/.pods/config.json` (`role: "coordinator"` vs `role: "worker"`), but `attach.py` never reads it to set the mode.

**Impact**: Running `pods attach` on the coordinator starts an rpc-server instead of a llama-server, which does nothing useful. The coordinator never gets a working inference backend from `attach`.

**Fix** in `pods/cli/attach.py`:
```python
@click.command()
def cmd():
    """Detect and start the best available inference backend on this node."""
    try:
        try:
            config = json.loads(CONFIG_PATH.read_text())
        except Exception:
            click.echo("Not joined to a pod. Run 'pods join <link>' first.", err=True)
            sys.exit(1)

        coordinator_ip = config.get("coordinator_ip")
        node_id = config.get("node_id")
        role = config.get("role", "worker")                    # <-- read role

        engine_config = {"mode": role}                         # <-- pass it in
        engine_name, engine = FallbackOrchestrator().start_best_engine(engine_config)
        click.echo(f"✓ Active engine: {engine_name}")
        # ... rest unchanged
```

Also fix `FallbackOrchestrator.start_best_engine` to pass the config through to `engine.start()`:
The config is already forwarded — `engine.start(config)` is called with the full config dict. So the fix is just in `attach.py` passing the right `mode`.

### Bug D — `_restart_llamacpp` Accesses `engine._process.pid` After Potential `stop()`

**Severity**: Medium  
**File**: `pods/gateway/routes_internal.py`, `_restart_llamacpp()`

```python
engine.start(config)  # may succeed
# ...
loaded_pid = engine._process.pid if engine._process else 0
```

`engine._process` is set to `None` by `stop()`. Between `engine.start()` and the `loaded_pid` read, no concurrent `stop()` can happen here (this is a background thread, not async), so it's technically safe. However accessing `._process` (private attribute) is a fragile coupling. Low priority.

**Fix**: Add a `get_pid()` method to `LlamaCppEngine`:
```python
def get_pid(self) -> int:
    return self._process.pid if self._process else 0
```
And use `engine.get_pid()` in `routes_internal.py`.

### Bug E — `pods model add` Registry Doesn't Have `llama3-8b`

**Severity**: Medium — documentation mismatch  
**File**: `pods/models/registry.py`

The README says `pods model add llama3-8b` but the registry key is `llama8b`. There is no `llama3-8b` key. Same for `qwen0.5b` vs... actually `qwen0.5b` does exist. But the README example `llama3-8b` will fail.

**Fix** in `pods/models/registry.py`, add alias:
```python
"llama3-8b": {
    "repo": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
    "filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
    "size_gb": 5.0,
},
```
Or update the README to use `llama8b`.

### Bug F — `_online_workers` Cutoff vs `attach` Timing Window

**Severity**: Low  
**File**: `pods/models/manager.py`, `_online_workers()`

`ONLINE_CUTOFF_SECONDS = 90` (3× heartbeat). But on the very first `pods attach` of a fresh worker, the heartbeat has only been sent once. If the coordinator's `pods model load` is run within seconds of the worker joining, the `last_seen` timestamp is recent and the worker gets included. This is correct behavior. No bug.

### Bug G — `_file_lock` Lock File Never Deleted

**Severity**: Low  
**File**: `pods/state/store.py`

The `_file_lock` context manager creates `state.json.lock` but never deletes it. On repeated writes, the same lock file is reused (correct), but the file accumulates. This is intentional for file-based locking — the file needs to persist. Not a bug per se, but worth noting.

---

## 3. Architecture / Design Issues to Fix

### Issue 1 — Gateway Exposes `/internal/*` Routes Without IP Guard Via `Depends`

**Status**: Fixed via `Depends(require_internal_access)` on the internal router. ✅ The fix is correct and working.

### Issue 2 — `router.py` Tries Ollama Even When Model Not Loaded There

**File**: `pods/gateway/router.py`

The current logic: if `loaded_model is None` (i.e., no model with this name is loaded in llamacpp or exo), it skips those backends but still tries Ollama — on the assumption Ollama can serve any model. This is a valid design choice, but it means a request for `qwen0.5b` will silently redirect to Ollama if Ollama happens to be running, even if the model isn't pulled there.

**Recommendation**: This is acceptable for now. No change needed, but consider adding Ollama model-availability check before routing.

### Issue 3 — `FallbackOrchestrator` Called by `attach.py` Tries to Start ALL Engines

**File**: `pods/inference/fallback.py`

`FallbackOrchestrator.start_best_engine` tries llama.cpp first, then exo, then Ollama. On a worker node, this is correct. On a coordinator node, it should also try llama.cpp but in coordinator mode (with a model path). The current code passes `{}` (empty config) which means no `model_path` → llamacpp coordinator start would fail immediately. So `pods attach` on a coordinator calling this will fail to start llama-server (no model path), and fall through to Ollama.

This is actually OK for `pods attach` — the coordinator loads a model separately via `pods model load`, not via `attach`. `attach` is meant to start the RPC server on workers. The confusion is that `attach` is also called on coordinators (the README doesn't clearly separate these). The coordinator's llama-server is started by `pods model load`, not `pods attach`.

**Recommendation**: Document this more clearly in CLAUDE.md. No code change strictly needed, but the Bug C fix above (passing `mode` from config) would make `attach` on coordinator a no-op (it'd try to start rpc-server in coordinator mode, which LlamaCppEngine will... actually still call `_start_rpc_server` because `mode == "coordinator"` triggers `_start_llama_server`, not rpc_server). Wait — re-check:

```python
def start(self, config: dict) -> None:
    mode = config.get("mode", "worker")
    self._mode = mode
    if mode == "worker":
        self._start_rpc_server()
    else:
        self._start_llama_server(config)  # needs model_path in config
```

So if a coordinator runs `pods attach` with `{"mode": "coordinator"}`, it calls `_start_llama_server` with no `model_path` → `KeyError: 'model_path'` crash.

**Revised fix for Bug C**: `attach` should only pass `mode` for workers. For coordinators, skip the engine start entirely, since `pods model load` handles that:

```python
role = config.get("role", "worker")
if role == "coordinator":
    click.echo("Coordinator: inference backend started via 'pods model load'. Nothing to do.")
    return
engine_config = {"mode": "worker"}
engine_name, engine = FallbackOrchestrator().start_best_engine(engine_config)
```

---

## 4. Security Issues (Actual Impact Assessment)

### Security S1 — Invite Link Contains Internal Token in Base64 (Not Encrypted)

**File**: `pods/network/invite.py`

The invite link is base64-encoded JSON containing `internal_token`. Anyone who intercepts the link can extract the token and call internal endpoints (register fake workers, trigger model reload, etc.).

**Context**: The internal endpoints also require the IP to be a Tailscale `100.x.x.x` address. So the attacker would need to be on the same Tailscale network. If they're already on your Tailscale network, they're likely trusted. **Real-world risk is low** unless you share invite links over untrusted channels.

**Fix** (optional, recommended for defense-in-depth): Make invite links one-time use by having the coordinator generate a short-lived token:

```python
# In encode_invite: include expiry timestamp
payload = json.dumps({
    "coordinator_ip": coordinator_ip,
    "pod_name": pod_name,
    "internal_token": internal_token,
    "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
})
# In decode_invite: check expires_at
```

No encryption needed if the token is single-use and short-lived.

### Security S2 — No Rate Limiting on `/v1/chat/completions`

**File**: `pods/gateway/routes_external.py`

A valid API key can hammer the endpoint indefinitely. For a home cluster shared with friends, this is probably fine. For anything more serious, add per-key rate limiting.

**Fix**: Add `slowapi` or a simple in-memory token bucket. Not critical for the current use case.

### Security S3 — `config.json` Permissions

**Status**: Already fixed — `CONFIG_PATH.chmod(0o600)` is in both `init.py` and `join.py`. ✅

### Security S4 — Internal Token in Plaintext in `config.json`

This is unavoidable without a keyring. The `0o600` chmod is the correct mitigation. ✅

---

## 5. Code Quality / Minor Issues

### Quality Q1 — `logs.py` vs `pods logs` Help Text Mismatch

**File**: `pods/cli/logs.py`

The help text says "Show usage logs in reverse chronological order" but the command name is `logs`, and the README says `pods logs [--follow]`. The `--follow` option is documented in README but `logs.py` has no `--follow` flag at all — only `--limit` and `--key-id`. The README is misleading.

**Fix**: Either add `--follow` that tails `~/.pods/logs/gateway.log`, or update the README to remove `[--follow]`.

### Quality Q2 — Stale Warning in Starlette

**Warning**: `Using httpx with starlette.testclient is deprecated; install httpx2 instead`

This is a test-only warning from FastAPI's `TestClient`. Not a production issue. Can be suppressed with `filterwarnings = ["ignore::DeprecationWarning"]` in `pyproject.toml` under `[tool.pytest.ini_options]`.

### Quality Q3 — `preflight.py` Auto-Kills Stale Pods Processes Silently

**File**: `pods/preflight.py`, `_try_free_port()`

If port 8080 is in use by a stale pods process, `PreflightChecker` calls `pkill -f` to kill it automatically without user confirmation. This is aggressive behavior — if the user has intentionally left the gateway running, `pods init` on the same machine will silently kill it.

**Recommendation**: Log a warning before killing: `print(f"[pods] Killing stale pods process on port {port}...")`.

### Quality Q4 — `detector.py` (`viable_engines`) Is Not Used Anywhere

**File**: `pods/inference/detector.py`

`viable_engines()` is defined but never imported or called. The actual engine selection is in `fallback.py::_engine_list()`, which has its own platform logic. These two are out of sync (e.g., `detector.py` allows exo on Linux for AMD, but `fallback.py` only allows exo on darwin).

**Fix**: Either delete `detector.py` or replace `_engine_list()` in `fallback.py` with a call to `viable_engines()`. Currently `detector.py` is dead code.

### Quality Q5 — `FallbackOrchestrator.start_best_engine` Health Check After Start Is Unreliable for RPC Server

**File**: `pods/inference/fallback.py`

After `engine.start(config)`, it calls `engine.health()`. For the RPC server (worker mode), `LlamaCppEngine.health()` in worker mode checks `_process.poll() is None`. The process may have just started and not yet bound to port 50052. The health check returns `RUNNING` immediately because the process is alive, but the port isn't bound yet. The TCP probe in `_start_rpc_on_workers` handles this, but the fallback orchestrator doesn't know.

**Impact**: Low — the TCP probe in `manager.py` correctly waits for port 50052 before including the worker in RPC. The double-check is fine.

---

## 6. Missing Test Coverage

These flows have zero test coverage and are the most likely failure points:

| Gap | File | What to test |
|-----|------|--------------|
| `attach` role handling | `cli/attach.py` | Coordinator role should skip/return, worker role starts rpc-server |
| `init` flow | `cli/init.py` | Gateway subprocess spawn, config.json created with correct structure |
| `join` flow | `cli/join.py` | Config written, agent spawned, coordinator registration call |
| `model load` with workers | `models/manager.py` | `_start_rpc_on_workers` called, llama-server started with rpc_hosts |
| `_restart_llamacpp` | `gateway/routes_internal.py` | Reloading flag set/cleared, model pid updated |
| `invite` expiry | `network/invite.py` | No expiry logic exists yet |

---

## 7. Summary: What to Fix in Claude Code

### Must Fix (breaks functionality or tests)

1. **`pods/platform/setup.py`** — Move `_asset_keywords()` call above network fetch in `download_and_install_binaries()`. Fixes the 1 failing test.

2. **`pods/cli/attach.py`** — Fix role handling: coordinators should not start an engine via attach (they use `pods model load`). Workers should start rpc-server. Currently always passes empty config to FallbackOrchestrator.

3. **`pods/models/registry.py`** — Add `"llama3-8b"` alias (or update README). The README example is broken.

### Should Fix (correctness / polish)

4. **`pods/cli/logs.py`** — Add `--follow` option that tails `~/.pods/logs/gateway.log` (with `subprocess.run(["tail", "-f", ...])` or Python equivalent), or remove `--follow` from README.

5. **`pods/inference/llamacpp.py`** — Add `get_pid() -> int` method to avoid accessing `._process` directly from `routes_internal.py`.

6. **`pods/inference/detector.py`** — Delete this file or wire it into `fallback.py`. It's dead code.

7. **`pods/preflight.py`** — Log a message before killing stale process with pkill.

8. **`pyproject.toml`** — Add `filterwarnings = ["ignore::DeprecationWarning"]` under `[tool.pytest.ini_options]` to suppress the starlette warning.

### Nice to Have (security / future)

9. **`pods/network/invite.py`** — Add expiry timestamp to invite links.

10. **`pods/gateway/routes_external.py`** — Add per-key request counting and basic rate limiting.

---

## 8. Files That Are Actually Solid (Don't Touch)

These are well-implemented and don't need changes:

- `pods/state/store.py` — Atomic writes, file locking, backup/recovery, migration all correct.
- `pods/state/schema.py` — Clean Pydantic models.
- `pods/gateway/auth.py` — Correct `hmac.compare_digest` key validation, proper dependency injection.
- `pods/gateway/proxy.py` — Correct timeout, proper streaming, error handling before returning response.
- `pods/gateway/router.py` — Simple, correct fallback chain.
- `pods/agent/heartbeat.py` — Good retry/backoff, consecutive failure tracking.
- `pods/network/probe.py` — Correct TCP probe with timeout and parallelism.
- `pods/network/tailscale.py` — All calls have timeouts, FileNotFoundError handled.
- `pods/internal_auth.py` — Correct layered IP + HMAC check.
- `pods/models/manager.py` — Symlink check, path containment via `is_relative_to`, RPC validation all correct.
- All tests in `tests/` except the one failing test in `test_setup.py`.

---

## 9. Quick Claude Code Prompt

After handing this off, start Claude Code with:

```
Read PODS_REVIEW.md first. Then fix issues in this order:
1. pods/platform/setup.py — move _asset_keywords() call above network fetch
2. pods/cli/attach.py — fix coordinator vs worker role handling  
3. pods/models/registry.py — add "llama3-8b" as alias for "llama8b"
4. pods/cli/logs.py — add --follow option or update README
5. Delete pods/inference/detector.py (dead code)
6. pyproject.toml — suppress starlette DeprecationWarning in pytest

Run pytest after each fix to confirm no regressions. Target: 160/160 passing.
```
