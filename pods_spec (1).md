# Pods — Technical Specification

## What This System Is

Pods is a distributed LLM inference system that lets a small group of people pool their machines into one shared AI cluster, exposed as a single OpenAI-compatible API endpoint. It is not a training system, not a cloud product, and not enterprise software. It is a peer-to-peer inference layer for a group of 3–5 people who trust each other.

The system is built on four foundations: llama.cpp RPC mode for model sharding (primary), exo as a fallback sharding engine where supported, Tailscale for networking, and Ollama as the single-machine fallback runtime for Windows nodes or when sharding is unavailable.

The entire system ships as a single binary called `pods` that is placed on PATH. One binary, one command prefix, works on Linux, WSL2, and macOS. Windows nodes get a pre-built `pods.exe` that transparently manages WSL2 internally — the user never opens a WSL2 terminal. No Python environment, no dependency installation, no pip, no venv. The binary bundles the CLI, the gateway server, the heartbeat agent, and the process manager for llama.cpp and exo.

---

## Distribution and Installation

### How the binary is built

The `pods` CLI and gateway are written in Python but packaged into a single self-contained executable using PyInstaller. PyInstaller bundles the Python interpreter, all dependencies, and the application code into one file. The output is a native executable with no external dependencies.

Build targets:
- Linux x86_64 → `pods` ELF binary
- Windows x86_64 → `pods.exe` PE binary, runs natively in PowerShell or CMD, manages all inference through WSL2 transparently
- macOS arm64 + x86_64 → `pods` universal Mach-O binary, distributed as `pods.dmg`

Users download the binary for their platform, place it anywhere on PATH (`/usr/local/bin` on Linux/Mac, any PATH directory on Windows), and run `pods` directly. No installer wizard, no package manager required. Also published to pip as `pip install pods-cli` for users who prefer that path.

### llama.cpp binaries

llama.cpp's `llama-server` and `rpc-server` are compiled C++ binaries. They are not bundled inside the pods binary because they are large and require platform-specific CUDA builds. Instead, `pods init` and `pods join` run a one-time setup step that:

1. Detects the platform and GPU vendor — NVIDIA CUDA, AMD ROCm, Apple Metal, or CPU-only
2. Downloads the correct pre-built llama.cpp release binary from the llama.cpp GitHub releases page
3. Places them at `~/pods/llama.cpp/build/bin/llama-server` and `~/pods/llama.cpp/build/bin/rpc-server`
4. Verifies the binary runs by executing `llama-server --version`

This happens once during init or join. After setup, `pods` manages these binaries as child processes. The user never calls llama-server or rpc-server directly.

### Docker alternative

For users who want full isolation or are running headless server environments, a Docker image is provided as an alternative to the native binary. The Docker image contains the pods binary, llama.cpp CUDA binaries for Linux, and all dependencies pre-installed.

Docker is not the primary distribution path. It exists for servers and headless machines where a container is more natural, and for environments where CUDA is already configured in Docker.

Docker usage:
```
docker run --gpus all -v ~/.pods:/root/.pods -p 8080:8080 pods/pods:latest init
```

The container shares `~/.pods` with the host via a volume mount so state persists across restarts. Tailscale inside Docker requires `--cap-add NET_ADMIN --device /dev/net/tun` for the TUN interface.

The Docker image and native binary are functionally identical. No features are exclusive to either.

---

## System Layers

There are four distinct layers. Each layer only talks to the layer directly below it.

### Layer 1 — Network (Tailscale)

Every machine in the pod has a Tailscale IP in the `100.x.x.x` range. This IP is stable across reboots, network changes, and NAT boundaries. It does not change. All inter-node communication uses these IPs exclusively. No node ever contacts another node by LAN IP, hostname, or public IP.

Tailscale handles encryption, NAT traversal, and peer discovery at the network level. The pods system treats Tailscale as infrastructure — it assumes Tailscale is running and does not manage it beyond the initial `tailscale up` call during `pods join`.

**Known behavior — DERP relay on first connection:** When two nodes have never communicated directly, Tailscale routes their traffic through its DERP relay servers while attempting to establish a direct peer connection. For llama.cpp RPC, this means the first model load after a new node joins routes tensor transfers through DERP. For a 2B model this takes 2–5 minutes. For a 32B model slice this can take significantly longer. This is expected behavior, not a bug. Once Tailscale establishes a direct connection — accelerated by running `tailscale ping <peer-ip>` between nodes — all subsequent transfers use the direct path and are significantly faster. `pods status` shows whether each peer connection is direct or relayed.

### Layer 2 — Inference (llama.cpp RPC primary, exo fallback, Ollama fallback)

#### Primary: llama.cpp RPC mode

llama.cpp RPC is the primary inference engine for multi-machine sharding on CUDA/Linux/WSL2 setups. It uses a coordinator-worker architecture.

**Architecture:** The coordinator machine runs `llama-server`. Worker machines run `rpc-server`. The model file in GGUF format lives entirely on the coordinator — workers do not download or store model weights. When `llama-server` starts with a model and a list of RPC worker addresses, it loads the model and automatically splits tensors across all available devices: CUDA0 for the coordinator's local GPU, RPC0 for the first worker's GPU, RPC1 for the second, and so on. The split is proportional to each device's available VRAM and is computed automatically at load time.

**What workers do:** Each `rpc-server` process exposes the machine's GPU as a remote memory and compute backend. It does not know what model is being run. It receives tensor operations from the coordinator, executes them on its local GPU, and returns results. Workers are stateless with respect to the model.

**What the coordinator does:** `llama-server` on the coordinator orchestrates everything. It holds the full model file on disk, manages the tensor split, runs its own local GPU as one of the compute devices, and exposes the OpenAI-compatible HTTP API internally on port `8081`. The gateway talks to `llama-server` at `localhost:8081`.

**Inter-node communication:** The coordinator connects to each worker's `rpc-server` at `<worker-tailscale-ip>:50052` over TCP. This connection is established at model load time and held open. Tensor data flows over this connection during inference. Tailscale encrypts all traffic at the network layer.

**Binary locations managed by pods:**
- `~/pods/llama.cpp/build/bin/llama-server` — runs on coordinator only
- `~/pods/llama.cpp/build/bin/rpc-server` — runs on worker nodes only

#### Fallback: exo

exo is supported as a fallback engine for Apple Silicon macOS nodes and as a general fallback if llama.cpp RPC fails on a given setup. exo uses a ring pipeline architecture where each node holds a layer slice and passes activations to the next node.

exo is not used on CUDA/Linux machines unless llama.cpp RPC fails. When exo is the active engine on a node, `pods attach` probes `localhost:52415`. The gateway routes to exo's endpoint identically to how it routes to llama-server — both speak OpenAI-compatible HTTP.

#### Fallback: Ollama

Ollama runs on any platform including Windows natively. It cannot shard across machines. The gateway routes to Ollama when the requested model is small enough to fit on one machine, llama.cpp RPC is unavailable, or the node is Windows-native without WSL2. Ollama is probed at `localhost:11434`.

### Layer 3 — Gateway

The gateway is the only process external callers talk to. It runs on the coordinator machine and listens on port `8080` externally, bound to `0.0.0.0`. llama-server runs internally on port `8081` on `127.0.0.1` to avoid conflict.

The gateway validates API keys, selects a backend, proxies the request, streams the response, and records usage. It reads pod state from `~/.pods/state.json` on each request. It holds no model weights and performs no computation.

Exposed endpoints:
- `POST /v1/chat/completions` — main inference endpoint, requires `pk_*` auth
- `GET /v1/models` — returns union of models across all online backends, requires `pk_*` auth

### Layer 4 — Control (Pod State + CLI)

Pod state is a single JSON file at `~/.pods/state.json` on the coordinator. It is the sole source of truth. No distributed consensus, no replication.

The CLI is the human interface. The gateway is the machine interface. Both read from the same state file. The CLI writes directly to the file for coordinator-local operations. Non-coordinator nodes read state via `GET /internal/state`.

---

## Pod State Schema

```
pod
  id                  — random uuid generated at init
  name                — human readable name
  coordinator_ip      — tailscale IP of the coordinator
  created_at          — ISO timestamp
  inference_engine    — "llamacpp" | "exo" | "ollama"

members[]
  node_id             — random uuid per machine
  name                — human readable label
  tailscale_ip        — 100.x.x.x address
  role                — "coordinator" | "worker"
  os                  — "linux" | "wsl2" | "mac" | "windows"
  gpu_vram_gb         — integer
  inference_engine    — "llamacpp_rpc" | "exo" | "ollama" | "none"
  connection_type     — "direct" | "relay"
  models[]            — model names available (coordinator only for llamacpp)
  joined_at           — ISO timestamp
  last_seen           — ISO timestamp

keys[]
  key                 — pk_* string
  label               — human readable
  created_at          — ISO timestamp
  total_requests      — integer
  total_tokens        — integer

usage[]
  timestamp           — ISO timestamp
  key                 — pk_* string
  model               — model name
  prompt_tokens       — integer
  completion_tokens   — integer
  backend             — "llamacpp" | "exo" | "ollama"
  latency_ms          — time to first token

models[]
  name                — friendly name e.g. "qwen32b"
  file                — GGUF filename on coordinator disk
  size_gb             — float
  added_at            — ISO timestamp
  loaded              — boolean
  worker_nodes[]      — node_ids of workers currently participating
```

---

## llama.cpp RPC Layer — How It Actually Works

### Model loading sequence

When `pods model load <model-name>` is run:

1. pods reads the current online worker list from state.json
2. pods sends `POST /internal/start-rpc` to each online worker node's pods agent, which starts `rpc-server` bound to `0.0.0.0:50052`
3. pods starts `llama-server` on the coordinator with the GGUF file path and `--rpc <worker1-ip>:50052,<worker2-ip>:50052` flags where IPs are Tailscale addresses
4. llama-server connects to each rpc-server, queries available VRAM, computes the tensor split proportionally, and loads each device's tensors
5. pods polls `localhost:8081/health` until llama-server reports ready
6. state.json is updated to mark the model as loaded with the participating worker list
7. The gateway begins routing inference requests to `localhost:8081`

### Tensor split behavior

llama.cpp computes the split automatically. For a Q4_K_M quantized 32B model at approximately 20GB across three 8GB GPUs, each device receives roughly 6.7GB of tensors. The split is tensor-based, not layer-based — individual weight matrices can be split across devices.

### When a new worker joins mid-session

When `pods attach` is called on a new worker while a model is already loaded, the coordinator receives `POST /internal/attach`, kills the current llama-server process, sends `POST /internal/start-rpc` to all workers including the new one, and restarts llama-server with the updated `--rpc` list. Inference requests in flight at restart receive a 503. The gateway retries once automatically after a 5-second delay.

### Port allocation summary

- `50052` — rpc-server on worker nodes, bound to `0.0.0.0`, reached via Tailscale IP
- `8081` — llama-server on coordinator, bound to `127.0.0.1`, internal only
- `8080` — pods gateway on coordinator, bound to `0.0.0.0`, reachable by all pod members
- `52415` — exo, on any node where exo is the active engine
- `11434` — Ollama, on any node where Ollama is the active engine

---

## Model Auto-Download Orchestration

`pods model add <name>` runs on the coordinator and handles the full download flow.

pods resolves the friendly model name to a HuggingFace repository and specific GGUF filename using a built-in registry. It downloads the file to `~/pods/models/` using the HuggingFace Hub HTTP API, streaming the download and reporting real-time progress — bytes downloaded, percentage complete, and estimated time remaining. After download, pods registers the model in state.json.

Workers never download model files in llama.cpp RPC mode. The full GGUF lives on the coordinator only.

Built-in model registry:
- `qwen32b` → Qwen2.5-32B-Instruct Q4_K_M, approximately 20GB
- `qwen7b` → Qwen2.5-7B-Instruct Q4_K_M, approximately 5GB
- `gemma9b` → Gemma-2-9B-Instruct Q4_K_M, approximately 6GB
- `llama8b` → Llama-3.1-8B-Instruct Q4_K_M, approximately 5GB

Custom models are added by placing a GGUF file in `~/pods/models/` and running `pods model register <name> <filename>`.

For exo fallback mode, each node downloads its own assigned layer slice from HuggingFace when exo starts. This is handled by exo itself.

---

## Gateway — Request Lifecycle

1. Request arrives at `POST /v1/chat/completions` with `Authorization: Bearer pk_*` header
2. Gateway extracts the token and looks it up in `keys[]` in state.json. Returns 401 if not found.
3. Gateway reads the `model` field from the request body and checks `models[]` for a loaded match.
4. Gateway selects backend: llama-server at `localhost:8081` if the model is loaded there, exo at `localhost:52415` if exo is active, Ollama at the appropriate node if the model fits there. Returns 404 with available model list if nothing matches.
5. Gateway forwards the full request body to the selected backend with `stream: true` forced.
6. Gateway reads SSE chunks from the backend and re-streams each chunk to the caller unchanged. Counts tokens from `usage` delta fields in the stream.
7. After stream ends, gateway appends a usage record to `usage[]` in state.json and increments counters on the matching key.
8. If backend returns an error or times out (30 second default), gateway returns 503. No automatic retry on inference errors.

---

## CLI — Command Definitions

All commands are subcommands of the `pods` binary. The binary reads `~/.pods/config.json` for local node config.

### `pods init`

Run once on the coordinator. Checks Tailscale is running. Reads local Tailscale IP via `tailscale ip -4`. Runs one-time llama.cpp binary setup. Creates `~/.pods/` directory. Generates pod ID. Writes initial state.json. Starts the gateway as a managed background process. Optionally stores a Tailscale API token for programmatic pre-auth key generation.

### `pods join <invite-link>`

Run on any machine joining the pod. Decodes the base64 invite link to extract Tailscale pre-auth key, coordinator Tailscale IP, and pod name. Runs `tailscale up --authkey=<key> --accept-routes`. Runs one-time llama.cpp binary setup. Sends `POST /internal/register` to the coordinator with node details. Writes `~/.pods/config.json`. Starts the local pods agent as a background process.

### `pods attach`

Run on any node after joining. Detects which inference runtime is available by probing ports. If nothing is running, starts the appropriate backend automatically based on OS and GPU. Reports backend and available models to the coordinator. If a model is currently loaded and this is a new RPC worker, the coordinator automatically reloads llama-server to include this worker.

### `pods model add <name>`

Run on the coordinator. Downloads the GGUF file to `~/pods/models/` with real-time progress. Registers in state.json.

### `pods model load <name>`

Run on the coordinator. Starts rpc-server on all online workers. Starts llama-server with the model and all worker RPC addresses. Waits for llama-server to report healthy. Updates state.json.

### `pods model list`

Prints all models: name, file size, loaded status, participating workers.

### `pods keygen <label>`

Run on the coordinator. Generates a cryptographically random `pk_` prefixed key. Writes to state.json. Prints once.

### `pods invite`

Run on the coordinator. Generates a Tailscale pre-auth key via the API. Encodes coordinator IP, key, and pod name as URL-safe base64. Prints the invite link.

### `pods status`

Fetches `GET /internal/state` from the coordinator. Prints pod overview, member list with health and connection type, loaded models, API key usage totals, and last 5 usage records.

### `pods logs`

Prints usage records in reverse chronological order. Accepts `--limit N` and `--key <label>`.

### `pods ping`

Runs `tailscale ping` against all online members. Reports direct or relayed status. If any peer is relayed, prompts the user to run ping a few more times to help Tailscale establish a direct path.

---

## Heartbeat and Node Health

Each node's pods agent sends `POST /internal/heartbeat` to the coordinator every 30 seconds with node_id and current connection type. The coordinator updates `last_seen` and `connection_type` in state.json.

A node is offline if last_seen is more than 60 seconds ago. The gateway stops routing to offline nodes. When heartbeats resume, the node becomes available automatically.

If the coordinator goes offline, worker heartbeats fail silently. Active inference via llama-server continues — llama-server manages its own RPC connections independently.

---

## Internal HTTP Endpoints

External (require `pk_*` auth):
- `POST /v1/chat/completions`
- `GET /v1/models`

Internal (Tailscale-only, no auth):
- `POST /internal/register` — new node joining
- `POST /internal/heartbeat` — node health ping
- `POST /internal/attach` — node reporting inference backend
- `POST /internal/start-rpc` — coordinator instructs worker to start rpc-server
- `POST /internal/reconfigure` — updated worker list, worker restarts rpc-server
- `GET /internal/state` — full state.json

---

## Usage Monitoring

Usage records are appended to `usage[]` after each completed request. Token counts come from SSE stream delta fields. The array is trimmed to the last 1000 records on each write.

`pods logs` displays records. `pods status` aggregates by key. No external metrics server, no dashboard.

---

## Cross-Platform Behavior and Windows WSL2 Transparency

### Platform support matrix

- **Linux native** — full support. llama.cpp RPC, exo, Ollama all run directly. This is the primary development and coordinator platform.
- **WSL2 on Windows** — full support. NVIDIA GPU is accessible via CUDA on WSL2. llama.cpp RPC and exo run inside WSL2. The user experience is identical to Linux.
- **macOS (Apple Silicon)** — full support. llama.cpp RPC runs with Metal backend. exo with MLX is the preferred fallback for Apple Silicon due to better MLX optimization on that hardware.
- **macOS (Intel)** — supported, CPU inference only unless an eGPU is present. Usable as a coordinator or small model node.
- **Windows native (no WSL2)** — partial support. Ollama runs natively. llama.cpp RPC and exo require WSL2. If WSL2 is absent, this node can only contribute Ollama-served small models.

### How Windows WSL2 transparency works

The `pods.exe` binary on Windows is a thin wrapper. When the user runs any `pods` command in PowerShell or CMD, `pods.exe` does the following invisibly:

1. Checks if WSL2 is installed via `wsl --status`. If not, prints a clear message instructing the user to run `wsl --install` in PowerShell as Administrator and rerun the command. Does not proceed silently.
2. Checks if the Linux pods binary is installed inside WSL2 at `~/.local/bin/pods`. If not, downloads and installs it automatically.
3. Translates the Windows command into a WSL2 command — `pods join <link>` becomes `wsl -- pods join <link>`.
4. Streams stdout and stderr from the WSL2 process back to the Windows terminal in real time.
5. Exits with the same exit code as the WSL2 process.

From the user's perspective in PowerShell: they ran `pods join <link>` and it worked. They never opened a WSL2 terminal, never typed `wsl`, never configured anything. The only visible difference is that the first run takes slightly longer while the Linux binary is installed inside WSL2.

Port forwarding from WSL2 to Windows is handled automatically by `pods.exe` for the gateway port. When the coordinator runs on a Windows machine via WSL2, `pods.exe` runs `netsh interface portproxy` to forward `0.0.0.0:8080` on Windows to the WSL2 internal IP on port `8080`, making the gateway reachable from the Tailscale network.

---

## Fallback Chain and Error Handling

### Inference engine fallback chain

Every node attempts to start the best available inference engine in this order. It moves to the next only if the current one fails, not because of preference.

```
llama.cpp RPC (if NVIDIA or AMD GPU detected and CUDA/ROCm available)
  ↓ fails
exo (if Linux or macOS and Python environment available)
  ↓ fails
Ollama (always available as last resort on any platform)
  ↓ fails
no inference backend — node registers as compute-unavailable
```

When a fallback occurs, pods logs exactly why the preferred engine failed before moving to the next. The user sees this in their terminal during `pods attach`, not silently. Example:

```
[llama.cpp RPC] Checking CUDA availability... nvidia-smi found, CUDA 12.2 detected ✓
[llama.cpp RPC] Downloading rpc-server binary for linux-cuda12... ✓
[llama.cpp RPC] Starting rpc-server on port 50052... FAILED
  → rpc-server exited with code 1
  → stderr: CUDA error: no kernel image is available for execution on the device
  → Your GPU (RTX 4060 Laptop) requires CUDA compute capability 8.9
  → The downloaded binary was built for compute capability 8.6
  → Falling back to exo

[exo] Checking Python 3.12+... found 3.12.3 ✓
[exo] Installing exo-explore... ✓
[exo] Starting exo daemon... ✓
[exo] Active engine: exo on port 52415
```

### Gateway-level fallback

When a request arrives and the primary backend for that model fails or is unavailable, the gateway tries the next available backend that has the model. The fallback order at the gateway level is: llama-server → exo → Ollama. The gateway does not mix backends for a single request — it picks one and stays with it for the full stream.

If all backends fail, the gateway returns a 503 with a body that tells the user exactly what was tried:

```json
{
  "error": {
    "message": "All backends failed for model qwen32b",
    "type": "backend_unavailable",
    "details": {
      "llamacpp": "timeout after 30s — llama-server may still be loading",
      "exo": "connection refused — exo not running on coordinator",
      "ollama": "model qwen32b not found in ollama — available: llama3.2:3b"
    },
    "suggestion": "Run 'pods status' to check which nodes are online. Run 'pods model load qwen32b' if the model is not loaded."
  }
}
```

### Error message philosophy

Every error the user sees must answer three questions: what failed, why it failed, and what to do next. No error message exits with just a code or a stack trace. Internal exceptions are caught at every boundary and converted to user-facing messages before surfacing.

Error categories and their required content:

**Setup errors** (during init, join, attach) — state exactly which prerequisite is missing, the exact command to fix it, and whether the rest of setup can continue without it.

**Network errors** — distinguish between Tailscale not running, Tailscale running but peer unreachable, peer reachable but pods agent not responding, and pods agent responding but inference backend not running. Each is a different problem with a different fix.

**Inference errors** — distinguish between model not loaded, model loading in progress, backend crashed, and backend out of memory. OOM errors include the model size, available VRAM, and the suggestion to add more workers or use a smaller quantization.

**API errors** — 401 means the key is invalid or missing, with a reminder of where keys are generated. 404 means the model name is not recognized, with the list of available models. 503 means backends are down, with the structured detail object shown above.

**State corruption** — if state.json is malformed or missing fields, pods prints exactly which field is invalid, shows the expected schema for that field, and offers to reset that field to its default without wiping the rest of the file.

### Startup health checks

When `pods init` runs, it performs a pre-flight check sequence before writing any state. Each check either passes, warns, or blocks. Blocks prevent init from continuing. Warns proceed but tell the user what will be degraded.

```
Tailscale running         → blocks if not found, shows install instructions
Tailscale IP assigned     → blocks if not found, shows 'tailscale up' instruction
NVIDIA driver             → warns if not found, node will use CPU inference
CUDA toolkit              → warns if not found, falls back to exo or Ollama
Disk space (~/pods/)      → warns if under 25GB free, notes model sizes
Port 8080 available       → blocks if occupied, suggests alternative port
Port 8081 available       → blocks if occupied, notes llama-server conflict
```

When `pods join` runs on a new node, it runs the same pre-flight checks and reports them before attempting to connect to the coordinator.

---

## Project Directory Structure

This is the full layout of the pods repository. Every module maps directly to one layer or one responsibility. Nothing lives outside its layer's directory.

```
pods/
│
├── pods/                          ← main Python package
│   │
│   ├── cli/                       ← all Click command definitions
│   │   ├── __init__.py            ← registers all subcommands onto the root `pods` group
│   │   ├── init.py                ← pods init
│   │   ├── join.py                ← pods join <link>
│   │   ├── attach.py              ← pods attach
│   │   ├── invite.py              ← pods invite
│   │   ├── keygen.py              ← pods keygen <label>
│   │   ├── status.py              ← pods status
│   │   ├── logs.py                ← pods logs
│   │   ├── ping.py                ← pods ping
│   │   └── model.py               ← pods model add / load / list / register
│   │
│   ├── gateway/                   ← FastAPI gateway process
│   │   ├── __init__.py
│   │   ├── app.py                 ← FastAPI app, mounts external and internal routers
│   │   ├── routes_external.py     ← /v1/chat/completions and /v1/models
│   │   ├── routes_internal.py     ← /internal/* endpoints
│   │   ├── auth.py                ← pk_* key validation against state.json
│   │   ├── router.py              ← backend selection logic, fallback chain
│   │   └── proxy.py               ← SSE streaming proxy to selected backend
│   │
│   ├── agent/                     ← background process running on every node
│   │   ├── __init__.py
│   │   ├── heartbeat.py           ← 30s heartbeat thread to coordinator
│   │   └── server.py              ← FastAPI server for internal commands (start-rpc, reconfigure)
│   │
│   ├── inference/                 ← process lifecycle management for all inference engines
│   │   ├── __init__.py
│   │   ├── base.py                ← abstract InferenceEngine base class with start/stop/health/detect
│   │   ├── llamacpp.py            ← manages llama-server (coordinator) and rpc-server (worker) processes
│   │   ├── exo.py                 ← manages exo daemon process
│   │   ├── ollama.py              ← manages ollama process and model pulls
│   │   ├── detector.py            ← hardware detection: GPU vendor, VRAM, CUDA version, platform
│   │   └── fallback.py            ← tries engines in order, logs each attempt and failure reason
│   │
│   ├── state/                     ← all reads and writes to state.json
│   │   ├── __init__.py
│   │   ├── schema.py              ← dataclasses for Pod, Member, Key, UsageRecord, Model
│   │   ├── store.py               ← StateStore class: load, save, atomic write, trim usage array
│   │   └── defaults.py            ← default values for new pod, new member, new key
│   │
│   ├── network/                   ← Tailscale interaction
│   │   ├── __init__.py
│   │   ├── tailscale.py           ← wraps tailscale CLI: ip, status, ping, up, pre-auth key generation
│   │   └── invite.py              ← encode and decode base64 invite links
│   │
│   ├── models/                    ← model registry and download orchestration
│   │   ├── __init__.py
│   │   ├── registry.py            ← built-in name → HuggingFace repo + GGUF filename mapping
│   │   ├── downloader.py          ← streaming HuggingFace download with progress reporting
│   │   └── manager.py             ← pods model add/load/list logic, coordinates with inference layer
│   │
│   ├── platform/                  ← platform detection and Windows WSL2 wrapper
│   │   ├── __init__.py
│   │   ├── detect.py              ← detects OS, WSL2, GPU vendor, CUDA version
│   │   ├── setup.py               ← one-time setup: downloads correct llama.cpp binaries for platform
│   │   └── windows.py             ← pods.exe WSL2 proxy logic, netsh port forwarding
│   │
│   ├── errors.py                  ← all user-facing error classes with message, reason, and suggestion fields
│   ├── preflight.py               ← pre-flight check sequence run at init and join
│   └── __main__.py                ← entry point: `python -m pods` invokes the Click root group
│
├── build/                         ← PyInstaller packaging
│   ├── pods-linux.spec            ← PyInstaller spec for Linux ELF binary
│   ├── pods-windows.spec          ← PyInstaller spec for Windows .exe (thin WSL2 wrapper only)
│   ├── pods-macos.spec            ← PyInstaller spec for macOS universal binary
│   └── Dockerfile                 ← builds the Docker image with CUDA llama.cpp binaries
│
├── tests/
│   ├── test_state.py              ← StateStore read/write/trim tests
│   ├── test_auth.py               ← API key validation tests
│   ├── test_router.py             ← backend selection and fallback logic tests
│   ├── test_invite.py             ← invite link encode/decode tests
│   ├── test_preflight.py          ← pre-flight check tests with mocked system calls
│   └── test_inference.py          ← process start/stop/health tests with mocked binaries
│
├── pyproject.toml                 ← package metadata, dependencies, CLI entry point definition
├── README.md
└── .github/
    └── workflows/
        ├── build-linux.yml        ← builds and releases Linux binary on tag push
        ├── build-windows.yml      ← builds and releases Windows .exe on tag push
        └── build-macos.yml        ← builds and releases macOS .dmg on tag push
```

### Module responsibility rules

Every module has exactly one job. The CLI modules only parse arguments and call into other modules — no business logic lives in CLI files. The gateway modules only handle HTTP concerns — no inference engine logic lives in gateway files. The inference modules only manage processes — they do not read or write state.json directly. The state module is the only thing that touches state.json. The platform module is the only thing that touches OS-specific APIs.

### Entry points

The `pods` CLI entry point is defined in `pyproject.toml` as `pods = "pods.__main__:main"`. PyInstaller uses this as the entry point for all binary builds. The gateway is started as a subprocess by `pods init` — it is not imported directly. The agent is started as a subprocess by `pods join` — same pattern.

### Runtime directories

At runtime on each machine, pods uses these directories outside the repo:

```
~/.pods/
  state.json       ← coordinator only, source of truth
  config.json      ← every node, stores coordinator address and local node_id
  logs/
    gateway.log    ← gateway stdout/stderr
    agent.log      ← agent stdout/stderr
    llama-server.log
    rpc-server.log
    exo.log

~/pods/
  models/          ← downloaded GGUF files
  llama.cpp/
    build/
      bin/
        llama-server
        rpc-server
```

---

## What Is Explicitly Out of Scope

- Raft or any distributed consensus — single coordinator JSON is the state store
- Treasury or billing between pod members
- Compute marketplace
- Cloud fallback routing
- TLS on internal endpoints — Tailscale encrypts at the network layer
- Multi-pod federation
- Authentication beyond static pk_* keys
- True zero-config NAT traversal without Tailscale
- Web UI or dashboard
