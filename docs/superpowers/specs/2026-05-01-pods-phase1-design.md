# Pods Phase 1 — Core Foundation Design

**Date:** 2026-05-01
**Scope:** State, network, platform detection, inference engine management, pre-flight checks
**Approach:** Spec-faithful strict layering (Approach A)

---

## Context

Full spec lives in `pods_spec (1).md`. This document covers Phase 1 only — the foundation layer that can be validated against real hardware before any HTTP or CLI code exists.

Phase 2 (gateway, agent, model downloader, full CLI, build specs) is a separate session.

## Environment

- Platform: Windows 11 + WSL2 (Ubuntu)
- GPU: NVIDIA with CUDA configured inside WSL2
- llama.cpp already built at `~/pods/llama.cpp/build/bin/` inside WSL2
- Binaries confirmed present: `llama-server`, `rpc-server`
- Tailscale running, direct peer connections validated
- Multi-node RPC sharding already manually tested and working

## Phase 1 Deliverables

### 1. Package skeleton

`pyproject.toml` with:
- Package name `pods-cli`, entry point `pods = "pods.__main__:main"`
- Dependencies: `click`, `fastapi`, `uvicorn`, `httpx`, `pydantic`, `huggingface_hub`
- Dev dependencies: `pytest`, `pytest-asyncio`

Directory structure matching the spec exactly — all `__init__.py` files, all module files created (even if stub).

### 2. `pods/errors.py`

All user-facing error classes. Every class carries `message`, `reason`, `suggestion`. Categories: `SetupError`, `NetworkError`, `InferenceError`, `APIError`, `StateError`. No raw exceptions surface to users.

### 3. `pods/state/`

- `schema.py` — Pydantic dataclasses for `Pod`, `Member`, `Key`, `UsageRecord`, `Model`
- `store.py` — `StateStore`: `load()`, `save()` (atomic write via temp file + rename), `trim_usage()` (keep last 1000)
- `defaults.py` — factory functions for new pod, new member, new key

`StateStore` is the **only** module that touches `state.json`. All other modules receive a `StateStore` instance.

### 4. `pods/network/`

- `tailscale.py` — wraps Tailscale CLI: `get_ip()`, `get_status()`, `ping(peer_ip)`, `bring_up(authkey)`. All calls go through `subprocess.run`. Returns structured results, never raw strings.
- `invite.py` — `encode_invite(coordinator_ip, authkey, pod_name) -> str` and `decode_invite(link) -> dict`. URL-safe base64, JSON payload.

### 5. `pods/platform/`

- `detect.py` — `detect_platform() -> PlatformInfo` dataclass: `os` (linux/wsl2/mac/windows), `gpu_vendor` (nvidia/amd/apple/none), `cuda_version`, `vram_gb`
  - WSL2 detection: check `/proc/version` for `microsoft` string
  - GPU detection: `nvidia-smi` → NVIDIA, `rocm-smi` → AMD, `system_profiler` on Mac → Apple
- `setup.py` — two functions, both present from Phase 1:
  - `validate_existing_binaries()` — checks `llama-server` and `rpc-server` exist at `~/pods/llama.cpp/build/bin/` and are executable. Raises `PlatformError` with exact missing path. Fully implemented Phase 1.
  - `download_and_install_binaries(platform_info)` — downloads correct llama.cpp release binary for detected platform/GPU (linux-cuda, linux-rocm, linux-cpu, macos-metal, macos-cpu), places at standard paths. **Only downloads if binaries not already present** (calls `validate_existing_binaries()` first, skips if passing). Stubbed in Phase 1, fully implemented in Phase 2 with multi-platform support.
- `windows.py` — `WindowsProxy`: wraps `wsl -- pods <args>` translation and `netsh` port forwarding. Stub in Phase 1, fully implemented in Phase 2.

### 6. `pods/inference/`

- `base.py` — `InferenceEngine` abstract base class with abstract methods: `detect() -> bool`, `start(config) -> None`, `stop() -> None`, `health() -> HealthStatus`, `get_models() -> list[str]`
- `detector.py` — `HardwareDetector`: reads `PlatformInfo`, returns which engines are viable on this hardware
- `llamacpp.py` — `LlamaCppEngine(InferenceEngine)`:
  - Coordinator mode: starts `llama-server` process with `--rpc` flags, model path, ports
  - Worker mode: starts `rpc-server` on `0.0.0.0:50052`
  - `health()`: polls `localhost:8081/health`
  - Process managed via `subprocess.Popen`, PID tracked, stdout/stderr piped to `~/.pods/logs/`
- `exo.py` — `ExoEngine(InferenceEngine)`: starts/stops exo daemon, health at `localhost:52415`
- `ollama.py` — `OllamaEngine(InferenceEngine)`: starts/stops ollama, health at `localhost:11434`, model pulls
- `fallback.py` — `FallbackOrchestrator`: tries engines in order (llamacpp → exo → ollama), logs each attempt and failure reason with the exact output format from the spec, returns first that succeeds

### 7. `pods/preflight.py`

`PreflightChecker` runs the 7 checks from the spec in order. Each check returns `CheckResult(name, status, message)` where status is `pass | warn | block`. Blocks halt execution. Warns continue. Prints live status as each check runs.

Checks: Tailscale running, Tailscale IP assigned, NVIDIA driver, CUDA toolkit, disk space `~/pods/`, port 8080, port 8081.

### 8. Tests

- `tests/test_state.py` — StateStore read/write/atomic write/trim, schema serialization roundtrip
- `tests/test_inference.py` — engine start/stop/health with mocked subprocess calls; fallback chain logic
- `tests/test_invite.py` — encode/decode roundtrip, malformed input handling
- `tests/test_preflight.py` — each check with mocked system calls (pass/warn/block paths)

## Module Boundary Rules (enforced in Phase 1)

| Module | Can read state.json | Can write state.json | Can call subprocess | Can do HTTP |
|--------|-------------------|---------------------|--------------------|----|
| state/ | yes (via StateStore) | yes (via StateStore) | no | no |
| network/ | no | no | yes (tailscale CLI) | no |
| platform/ | no | no | yes (nvidia-smi, wsl) | no |
| inference/ | no | no | yes (llama-server, rpc-server) | yes (health checks) |
| preflight/ | no | no | yes (port checks) | no |

## Key Decisions

1. **Binary paths not downloaded in Phase 1.** `platform/setup.py` validates existing binaries only. Download logic comes in Phase 2 alongside `pods init`.
2. **No CLI in Phase 1.** `pods/__main__.py` stub only. Real Click commands in Phase 2.
3. **`download_and_install_binaries()` stubbed in Phase 1.** Signature and docstring written, body raises `NotImplementedError`. Prevents Phase 2 from needing to create the function — it just fills in the body. Multi-platform matrix (linux-cuda12/11, linux-rocm, linux-cpu, macos-metal-arm64, macos-cpu-x86) implemented in Phase 2.
3. **Pydantic for state schema.** `state.json` serialization via Pydantic model `.model_dump()` / `.model_validate()`. Handles field defaults, validation errors, and schema evolution cleanly.
4. **Atomic state writes.** Write to `.state.json.tmp` then `os.replace()`. Prevents corrupt state on crash.
5. **All subprocess output goes to `~/.pods/logs/`**, not swallowed. Named by process (gateway.log, rpc-server.log, etc.).

## Validation Against Real Hardware

After Phase 1 is built, run:
```bash
cd /path/to/pods-experiment
pytest tests/ -v

# Manual smoke test inside WSL2:
python -m pods.platform.detect     # should print nvidia + cuda version
python -m pods.platform.setup      # should validate binary paths
python -m pods.preflight           # should show 7 checks, all pass/warn
```
