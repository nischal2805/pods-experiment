# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pods is a distributed LLM inference system built in Python. A small group of trusted machines pool their GPUs into one shared cluster exposed as a single OpenAI-compatible API. The spec is in `pods_spec (1).md` — read it before starting any implementation work.

## Build and Development Commands

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run a single test file
pytest tests/test_router.py

# Run a single test
pytest tests/test_router.py::test_fallback_chain

# Build native binary (Linux)
pyinstaller build/pods-linux.spec

# Build Windows exe
pyinstaller build/pods-windows.spec

# Build macOS binary
pyinstaller build/pods-macos.spec

# Build Docker image
docker build -f build/Dockerfile -t pods/pods:latest .

# Run the CLI during development
python -m pods <command>
```

## Architecture

Four layers, each only communicates with the layer directly below it:

1. **Network** (`pods/network/`) — Tailscale only. All inter-node traffic uses `100.x.x.x` IPs exclusively. Never LAN IPs or hostnames.
2. **Inference** (`pods/inference/`) — Process lifecycle management for llama.cpp RPC (primary), exo (fallback), Ollama (last resort). `base.py` defines the abstract `InferenceEngine` interface. `fallback.py` tries engines in order and logs each failure reason before moving to the next.
3. **Gateway** (`pods/gateway/`) — FastAPI proxy on port `8080`. Validates `pk_*` API keys, selects backend via `router.py`, streams SSE via `proxy.py`, records usage. Talks only to `localhost:8081` (llama-server), `localhost:52415` (exo), or `localhost:11434` (Ollama).
4. **Control** (`pods/cli/`, `pods/state/`) — Click CLI + `~/.pods/state.json` as the sole source of truth. `state/store.py` is the only module that reads/writes `state.json`.

### Key Architectural Rules

- **Module boundaries are strict.** CLI files: parse args only, no business logic. Gateway files: HTTP concerns only, no inference engine logic. Inference files: manage processes only, never touch `state.json`. `pods/state/` is the only thing that touches `state.json`. `pods/platform/` is the only thing that touches OS-specific APIs.
- **Entry points:** CLI = `pods.__main__:main`. Gateway and agent are started as subprocesses by `pods init` / `pods join` — never imported directly.
- **Windows:** `pods.exe` is a thin WSL2 proxy (`pods/platform/windows.py`). It translates commands to `wsl -- pods <cmd>` and handles port forwarding via `netsh`. No Windows-native inference.

### Port Allocation

| Port  | Process       | Bound to      |
|-------|--------------|---------------|
| 8080  | gateway       | `0.0.0.0`     |
| 8081  | llama-server  | `127.0.0.1`   |
| 50052 | rpc-server    | `0.0.0.0`     |
| 52415 | exo           | `localhost`   |
| 11434 | Ollama        | `localhost`   |

### State Schema

`~/.pods/state.json` contains: `pod` (metadata), `members[]` (nodes), `keys[]` (API keys with `pk_` prefix), `usage[]` (trimmed to last 1000), `models[]`. See spec for full field definitions.

### llama.cpp RPC Model Load Sequence

1. Read online workers from `state.json`
2. `POST /internal/start-rpc` to each worker → starts `rpc-server` on port `50052`
3. Start `llama-server` on coordinator with `--rpc <worker-tailscale-ip>:50052,...`
4. Poll `localhost:8081/health` until ready
5. Update `state.json` — model marked loaded with participating worker list

Mid-session worker join triggers coordinator to kill and restart llama-server with updated `--rpc` list. In-flight requests get a 503; gateway retries once after 5 seconds.

### Error Handling Convention

Every user-facing error must answer: what failed, why, what to do next. Use `pods/errors.py` error classes which have `message`, `reason`, and `suggestion` fields. No raw exceptions or stack traces surfaced to users.

### Runtime Directories (outside repo)

```
~/.pods/state.json       — coordinator source of truth
~/.pods/config.json      — every node (coordinator address, local node_id)
~/.pods/logs/            — gateway.log, agent.log, llama-server.log, rpc-server.log
~/pods/models/           — downloaded GGUF files
~/pods/llama.cpp/build/bin/  — llama-server and rpc-server binaries
```
