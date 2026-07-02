1. errors.py is left unchecked with all errors being ignored
2. registery has support for very less models and no support for newer models and instead of having this registery where we have support for only these models, we should directly fetch from the foundry or registry(hf) and get the model.
3. add support for others on the network to access the chat completions end point for people without gpu and still be able to run inference
4. add an ui for chat purpose 
5. add better cli support with explainable documentation 
6. stress test with finding the limitations
7. add support for people on different tailnet to join or use another global system for anyone to join so that every device doesnt have to join personal tailnet
8. Fix the -ngl 99 bug (just did this) — this is blocking you from using the GPU pool at all right now. This is a 10x improvement from 0 workers to 2 workers contributing.
9. Dynamic layer assignment — let llama.cpp auto-distribute based on VRAM instead of hardcoding. Already in the fix above.
10. VRAM-aware worker selection — instead of just "is the worker online", query nvidia-smi on each worker via the agent and pick workers that actually have free VRAM. Wrong workers in the RPC pool cause the crash you just saw.
11. Persistent RPC connections — right now every pods model load restarts all rpc-servers from scratch. If you keep rpc-servers running across model loads, the weight transfer reuses established connections. This saves 30-60s on every model switch.
12. Direct Tailscale paths — you're already on this. Relay is killing your weight transfer speed. Getting all three machines to direct paths cuts weight distribution time by 3-5x.
ADDITIONAL CONCERNS:
1. Gateway binds to 0.0.0.0:8080, not just the Tailscale IP. The rpc-server also binds to 0.0.0.0:50052. This means anyone on the same LAN as the coordinator can hit your API (or worse, the rpc-server directly) without being on the Tailscale network. The rpc-server has no auth — it's meant to be internal only. You probably want:
python# gateway: bind to tailscale IP only
host = get_tailscale_ip() or "127.0.0.1"
uvicorn.run(app, host=host, port=8080)
Or at minimum document that users should configure Tailscale ACLs to block port 50052 from non-pod machines.
2. Phase 3 is still open. Sequential shard downloads and sequential RPC server startup on workers are the two biggest latency killers. pods model load taking 2+ minutes on a slow connection is a bad first impression. These should be high priority.
3. The Tailscale auth key requirement is the highest friction point for "others on the network." They need a tailscale.com account and a reusable auth key. The README mentions this once but doesn't explain the scoping. Ephemeral keys vs. reusable keys matter here — if someone uses an ephemeral key and their machine reboots, they're disconnected. The pods invite flow should explicitly recommend reusable auth keys.
4. CPU-only documentation gap. The install succeeds silently on CPU-only machines, then inference is just very slow. Add a warning banner in pods status when no GPU is detected, like [WARN] No GPU detected — inference will be CPU-only (slow).
5. State file is not locked. state.json is your cluster state. If two CLI commands run concurrently (e.g., pods model load and pods worker remove), you could get a corrupted write. If you're not already doing this, wrap state writes in a file lock. fcntl.flock on Linux or filelock package cross-platform.
6. loaded_pid tracking for llama-server. If the coordinator machine reboots, state.json still has loaded=True with a stale PID. Bug #21 fixed the failed-start case, but a reboot leaves stale state. On pods init or pods status, you should validate that loaded_pid is actually alive (os.kill(pid, 0)) and clear the model state if no
