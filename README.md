# Pods

Pool GPUs from multiple machines into one shared LLM inference cluster. Expose it as a single OpenAI-compatible API endpoint. Uses Tailscale for networking and llama.cpp RPC for distributed inference.

```
┌─────────────┐        Tailscale VPN         ┌──────────────┐
│ coordinator │ ──────────────────────────── │   worker 1   │
│  port 8080  │ ←── llama-server --rpc ────→ │ rpc-server   │
│  gateway    │                               │  port 50052  │
└─────────────┘                               └──────────────┘
      │                                       ┌──────────────┐
      │                                       │   worker 2   │
      └───────────────────────────────────── │ rpc-server   │
                                              │  port 50052  │
                                              └──────────────┘
```

## How it works

- Coordinator runs the gateway (port 8080) and llama-server (port 8081)
- Workers run rpc-server (port 50052) — expose GPU memory over the network
- llama.cpp splits model layers across all GPUs automatically
- All traffic routes through Tailscale `100.x.x.x` IPs — no port forwarding needed

---

## Install

### Curl (fresh machine, no clone needed)

```bash
curl -fsSL https://raw.githubusercontent.com/nischal2805/pods-experiment/main/install.sh | bash
```

### From local clone

```bash
git clone https://github.com/nischal2805/pods-experiment
cd pods-experiment
bash install.sh
```

The installer:
1. Installs `uv` (fast Python package manager) if missing
2. Creates `~/.pods-venv` with Python 3.11
3. Installs the `pods` CLI
4. Installs Tailscale if missing
5. Downloads prebuilt llama.cpp binaries (auto-detects CUDA / Metal / ROCm)

After install, add to your shell profile if prompted:

```bash
export PATH="${HOME}/.local/bin:${PATH}"
```

---

## Setup: 2-machine cluster

### On the coordinator machine

```bash
# 1. Initialize the pod (starts gateway on port 8080)
pods init my-pod

# 2. Generate an API key
pods keygen my-key

# 3. Print an invite link for workers
pods invite
```

### On each worker machine

```bash
# Join using the invite link from above
# --authkey is a Tailscale auth key from https://login.tailscale.com/admin/settings/keys
pods join <invite-link> --authkey <tailscale-auth-key>

# Start the agent (registers this machine with the coordinator)
pods attach
```

### Back on the coordinator — load a model

```bash
# Download + register (downloads to ~/pods/models/)
pods model add qwen0.5b       # ~400 MB, good for testing
pods model add llama3-8b      # ~4.7 GB

# Load — auto-discovers online workers and starts RPC sharding
pods model load qwen0.5b

# Check status
pods status
```

---

## Use the API

Standard OpenAI-compatible endpoint:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer <your-pk_-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen0.5b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

Works with any OpenAI SDK — just change `base_url` and `api_key`:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="pk_your_key_here",
)
response = client.chat.completions.create(
    model="qwen0.5b",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

---

## Dashboard

Live cluster dashboard at `http://localhost:8080/dashboard` — updates every 2s.

Shows: member health (OK / DEGRADED / STALE / DEAD), loaded models, API key usage, recent requests.

---

## CLI reference

```
pods init <name>              Initialize pod on this coordinator machine
pods join <link>              Join an existing pod as a worker
pods attach                   Start this machine's agent process
pods invite                   Generate a worker invite link
pods status                   Show cluster health and member list

pods model add <name>         Download and register a model
pods model load <name>        Load model into inference (starts RPC on workers)
pods model unload <name>      Unload model and stop RPC servers
pods model list               List registered models
pods model register <n> <f>   Register an existing GGUF file

pods keygen <label>           Create an API key
pods key list                 List all API keys
pods key revoke <label|pk_>   Revoke an API key

pods worker remove <id|ip>    Remove a worker from the cluster
pods leave                    Leave the pod (run on a worker machine)

pods ping                     Ping all workers
pods logs [--follow]          Tail gateway / agent logs
```

---

## Ports

| Port  | Process        | Bound to    |
|-------|---------------|-------------|
| 8080  | gateway        | `0.0.0.0`   |
| 8081  | llama-server   | `127.0.0.1` |
| 8082  | agent          | `127.0.0.1` |
| 50052 | rpc-server     | `0.0.0.0`   |

---

## Runtime files

```
~/.pods/state.json        Cluster state (coordinator only)
~/.pods/config.json       Local node config (every machine)
~/.pods/logs/             gateway.log, agent.log, llama-server.log
~/pods/models/            Downloaded GGUF files
~/pods/llama.cpp/         llama-server and rpc-server binaries
~/.pods-venv/             Python virtualenv
```

---

## Uninstall

```bash
# Interactive
bash ~/.pods-src/uninstall.sh

# Non-interactive (skip prompt)
bash ~/.pods-src/uninstall.sh --yes

# Keep model files (just remove everything else)
bash ~/.pods-src/uninstall.sh --yes --keep-models
```

Removes: venv, state, config, logs, launcher, source clone, binaries.  
Does NOT remove: Tailscale, uv.

---

## Dev / testing

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run all tests
pytest tests/

# Single test file
pytest tests/test_dashboard.py

# Single test
pytest tests/test_router.py::test_fallback_chain
```

Requirements: Python 3.10+, pytest, fastapi, uvicorn, httpx, pydantic, huggingface_hub.
