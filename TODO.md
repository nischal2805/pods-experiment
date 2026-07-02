# Pods — Feature & Fix Backlog

## Phase 1 — Reliability + Bug Fixes (DONE 2026-05-10)

| # | Item | Status |
|---|------|--------|
| 3 | Heartbeat retry + backoff | ✅ 3 retries, 2/4/8s backoff, consecutive-failure counter |
| 4 | `pods status` live probe | ✅ TCP probe :8082 + :50052, OK/DEGRADED/STALE/DEAD labels |
| 7 | Auto-prune dead workers | ✅ Manual `pods worker prune` + heartbeat auto-sweep at 10min |
| 8 | Mid-session worker join | ✅ `Model.reloading` flag + gateway 503 + `Retry-After: 5` |
| 11 | exo CUDA fallback noise | ✅ exo gated to `sys.platform == 'darwin'` |
| 12 | llama-server hangs 120s | ✅ TCP probe :50052 (5s deadline) before adding worker to `--rpc` |
| 13 | No visibility into llama-server failures | ✅ Last 30 lines of log streamed into `InferenceError.reason` |
| 14 | Worker flickers online/offline | ✅ `_online_workers` cutoff 60s → 90s (3× heartbeat); skipped members logged |
| 16 | `pods status` shows worker connected when dead | ✅ Live TCP probe + DEAD/STALE/DEGRADED labels |

## Phase 2 — New Commands (DONE 2026-05-10)

| # | Command | Status |
|---|---------|--------|
| 1 | `pods worker remove <ip\|node_id>` | ✅ Best-effort agent shutdown via `/internal/shutdown`, removes from state, clears worker from `model.worker_nodes` |
| 2 | `pods key revoke <label\|pk_...>` + `pods key list` | ✅ Revoke by label or full token; ambiguous-label error path; list shows label/key_id/requests/tokens |
| 5 | `pods model unload <name>` | ✅ SIGTERM `loaded_pid`, POST `/internal/stop-rpc` to each worker, marks loaded=False, clears worker_nodes |
| 6 | `pods leave` | ✅ POST `/internal/leave` to coordinator + `/internal/shutdown` to local agent + delete `~/.pods/config.json` (`--keep-config` opt-out) |

## Phase 3 — Performance & Network

| # | Item | Description |
|---|------|-------------|
| 9 | Parallel shard download | Sequential shard downloads are slow. Switch to threadpool/asyncio parallel fetch. Add per-shard hash verify + resume on interrupted download. |
| 10 | Reduce model load latency | (a) Start all worker RPC servers in parallel instead of sequential. (b) Reduce health poll interval to 500ms. (c) Log per-step timing to surface bottleneck. (d) Investigate Tailscale relay vs direct — relay adds 50-150ms RTT, direct <5ms. Add `--direct` flag to force direct Tailscale connection. |

### Network / Tailscale notes

- Relay mode (DERP) is the default when two nodes haven't established a direct path — adds significant latency to every inference token
- Fix: ensure nodes attempt direct connection (`tailscale ping <peer>` forces hole-punch), expose connection type in `pods status` (already tracked as `connection_type` in schema)
- Long-term: investigate whether llama.cpp RPC benefits from TCP_NODELAY / low-latency socket options over Tailscale

---

## Bugs Fixed (Session 2026-06-10 — full-codebase review)

| # | Bug | Root Cause | Fix |
|---|-----|------------|-----|
| 17 | Gateway exposed `?path=` query param on all authed endpoints | `Depends(StateStore)` made FastAPI treat the store's `path` ctor arg as a query parameter — clients could point key validation at an arbitrary state file | Dependency provider `get_store()` in `gateway/auth.py` ✅ |
| 18 | Backend connect errors crashed mid-stream after HTTP 200 already sent | `stream_to_backend` returned the StreamingResponse before opening the upstream connection; errors raised inside the generator bypassed the route's try/except | Connect + status check before returning; backend 4xx/5xx now propagate as 503 with body excerpt ✅ |
| 19 | Long generations / slow prefill cut off at 30s | Blanket `timeout=30` on the proxy stream | `httpx.Timeout(read=300, connect=10)` ✅ |
| 20 | Second `pods model load` orphaned worker rpc-server | `/internal/start-rpc` spawned a new rpc-server without stopping the old one — new one fails to bind :50052 and dies, `_engine` points at corpse | `_replace_engine()` stops the old engine first; engine swaps serialized with a lock ✅ |
| 21 | Failed coordinator restart left model marked `loaded=True` with dead pid | `_restart_llamacpp` returned silently on `engine.start()` failure | Marks `loaded=False`, `loaded_pid=0`, clears `worker_nodes` ✅ |
| 22 | Models-dir containment check bypassable via sibling dir (`models-evil`) | `str.startswith` prefix check | `Path.is_relative_to` ✅ |
| 23 | `pods.exe` crashed with raw traceback when WSL missing | `subprocess.run(["wsl", ...])` raises `FileNotFoundError` | `check_wsl`/`_get_wsl_ip` catch FileNotFoundError/Timeout ✅ |
| 24 | Hung tailscale daemon froze `pods init/join/status/ping` forever | No subprocess timeouts in `network/tailscale.py`; `ping` TimeoutExpired uncaught | Timeouts on all calls; missing binary → friendly `NetworkError` ✅ |
| 25 | AMD GPUs always reported 0 GB VRAM | rocm-smi output never parsed | Parse `VRAM Total Memory (B)` lines, sum across GPUs ✅ |
| 26 | Log file handle leaks in exo/ollama engines | `open()` without close before `Popen` | `with open(...)` (child keeps inherited fd) ✅ |
| — | Module-level code placed above imports in `models/manager.py` | Earlier hotfix inserted `_validate_rpc_hosts` before the import block | Reordered ✅ |

Regression tests: `tests/test_codebase_fixes.py` (8 tests).

## Bugs Fixed (Sessions ≤ 2026-05-10)

| # | Bug | Root Cause | Fix |
|---|-----|------------|-----|
| 11 | exo listed as CUDA fallback but does nothing | exo 0.3.x dropped CUDA/Linux backend, MLX-only now | Gate exo to darwin in `_engine_list` ✅ |
| 12 | `llama-server` hangs 120s then generic timeout | Coordinator can't reach worker:50052 (firewall/relay). rpc-server starts but connection never establishes | TCP probe `worker:50052` (5s deadline) before adding to `--rpc` ✅ |
| 13 | No visibility into why llama-server fails | Health wait silent — stderr goes to log file only | Stream last 30 lines of llama-server.log into `InferenceError.reason` ✅ |
| 14 | Worker flickers online/offline across `pods model load` calls | Heartbeat 30s interval, `_online_workers()` cutoff 60s — one missed beat drops worker | Cutoff 60s → 90s ✅ |
| 15 | `ModuleNotFoundError: pods.models.manager` after install | setuptools strict editable mode generates stubs at install time; new subpackages not in old stubs | `editable-mode="compat"` in pyproject.toml + `--force-reinstall` in install.sh ✅ |
| 16 | `pods status` shows worker connected when agent server is dead | status reads stale `state.json`, no live probe | Live TCP probe + DEAD/STALE/DEGRADED label ✅ |
