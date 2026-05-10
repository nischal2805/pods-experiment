from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from ..network.probe import tcp_probe_many
from ..state.store import StateStore

router = APIRouter()

STALE_AFTER_S = 90
DEAD_AFTER_S = 600


def get_store() -> StateStore:
    return StateStore()


def _label(member, probes, now):
    if member.role != "worker":
        return "OK"
    age = (now - member.last_seen).total_seconds()
    agent_up = probes.get((member.tailscale_ip, 8082), False)
    rpc_up = probes.get((member.tailscale_ip, 50052), False)
    if age > DEAD_AFTER_S:
        return "DEAD"
    if age > STALE_AFTER_S:
        return "STALE"
    if agent_up and rpc_up:
        return "OK"
    return "DEGRADED"


@router.get("/dashboard/state")
def dashboard_state(store: StateStore = Depends(get_store)) -> JSONResponse:
    state = store.load()
    now = datetime.now(timezone.utc)

    targets = []
    for m in state.members:
        if m.role == "worker":
            targets.append((m.tailscale_ip, 8082))
            targets.append((m.tailscale_ip, 50052))
    probes = tcp_probe_many(targets, timeout=1.0) if targets else {}

    members = []
    for m in state.members:
        members.append({
            "name": m.name,
            "role": m.role,
            "tailscale_ip": m.tailscale_ip,
            "os": m.os,
            "gpu_vram_gb": m.gpu_vram_gb,
            "inference_engine": m.inference_engine,
            "connection_type": m.connection_type,
            "last_seen": m.last_seen.isoformat(),
            "age_s": int((now - m.last_seen).total_seconds()),
            "label": _label(m, probes, now),
        })

    models = [
        {
            "name": m.name,
            "size_gb": m.size_gb,
            "loaded": m.loaded,
            "reloading": m.reloading,
            "worker_nodes": m.worker_nodes,
        }
        for m in state.models
    ]

    keys = [
        {
            "label": k.label,
            "key_id": k.key_id,
            "total_requests": k.total_requests,
            "total_tokens": k.total_tokens,
        }
        for k in state.keys
    ]

    cutoff = now - timedelta(minutes=10)
    recent_usage = [
        {
            "timestamp": u.timestamp.isoformat(),
            "model": u.model,
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "backend": u.backend,
            "latency_ms": u.latency_ms,
        }
        for u in state.usage if u.timestamp > cutoff
    ][-50:]

    return JSONResponse({
        "pod": {
            "id": state.pod.id,
            "name": state.pod.name,
            "coordinator_ip": state.pod.coordinator_ip,
            "inference_engine": state.pod.inference_engine,
        },
        "members": members,
        "models": models,
        "keys": keys,
        "recent_usage": recent_usage,
        "now": now.isoformat(),
    })


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Pods Dashboard</title>
<style>
  :root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --fg: #c9d1d9; --muted: #8b949e;
    --ok: #3fb950; --warn: #d29922; --bad: #f85149; --accent: #58a6ff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--bg); color: var(--fg); padding: 24px; line-height: 1.4;
  }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 14px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin: 24px 0 8px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
  .grid { display: grid; gap: 12px; }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: 14px 16px;
  }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--border); }
  td { padding: 8px; border-bottom: 1px solid var(--border); font-family: ui-monospace, "JetBrains Mono", monospace; }
  tr:last-child td { border-bottom: none; }
  .pill {
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
  }
  .pill.ok       { background: rgba(63,185,80,0.15);  color: var(--ok); }
  .pill.degraded { background: rgba(210,153,34,0.15); color: var(--warn); }
  .pill.stale    { background: rgba(210,153,34,0.15); color: var(--warn); }
  .pill.dead     { background: rgba(248,81,73,0.15);  color: var(--bad); }
  .pill.loaded   { background: rgba(88,166,255,0.15); color: var(--accent); }
  .pill.idle     { background: rgba(139,148,158,0.15); color: var(--muted); }
  .empty { color: var(--muted); padding: 12px 0; font-style: italic; }
  .row { display: flex; gap: 24px; flex-wrap: wrap; align-items: baseline; }
  .row > div { min-width: 0; }
  .hdr { display: flex; justify-content: space-between; align-items: center; }
  #refresh { color: var(--muted); font-size: 12px; }
  .blink { animation: blink 1s ease infinite; }
  @keyframes blink { 50% { opacity: 0.4; } }
</style>
</head>
<body>
  <div class="hdr">
    <div>
      <h1 id="pod-name">Pods</h1>
      <div class="sub" id="pod-meta">loading...</div>
    </div>
    <div id="refresh">refresh: <span id="refresh-state">--</span></div>
  </div>

  <h2>Members</h2>
  <div class="card"><table>
    <thead><tr><th>Name</th><th>Role</th><th>Tailscale IP</th><th>OS</th><th>VRAM</th><th>Engine</th><th>Net</th><th>Last seen</th><th>Status</th></tr></thead>
    <tbody id="members"></tbody>
  </table></div>

  <h2>Models</h2>
  <div class="card"><table>
    <thead><tr><th>Name</th><th>Size</th><th>State</th><th>RPC workers</th></tr></thead>
    <tbody id="models"></tbody>
  </table></div>

  <h2>API Keys</h2>
  <div class="card"><table>
    <thead><tr><th>Label</th><th>Key ID</th><th>Requests</th><th>Tokens</th></tr></thead>
    <tbody id="keys"></tbody>
  </table></div>

  <h2>Recent usage (last 10 min)</h2>
  <div class="card"><table>
    <thead><tr><th>Time</th><th>Model</th><th>Tokens (in/out)</th><th>Latency</th><th>Backend</th></tr></thead>
    <tbody id="usage"></tbody>
  </table></div>

<script>
const $ = (id) => document.getElementById(id);
const fmtAge = (s) => s < 60 ? s + 's' : s < 3600 ? Math.floor(s/60) + 'm' : Math.floor(s/3600) + 'h';
const esc = (s) => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

async function poll() {
  $("refresh-state").textContent = "fetching...";
  $("refresh-state").classList.add("blink");
  try {
    const r = await fetch("/dashboard/state", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const s = await r.json();
    render(s);
    $("refresh-state").textContent = "live (every 2s)";
  } catch (e) {
    $("refresh-state").textContent = "error: " + e.message;
  } finally {
    $("refresh-state").classList.remove("blink");
  }
}

function render(s) {
  $("pod-name").textContent = s.pod.name;
  $("pod-meta").textContent = `pod ${s.pod.id.slice(0,8)} | coordinator ${s.pod.coordinator_ip} | engine ${s.pod.inference_engine}`;

  const mb = $("members");
  mb.innerHTML = s.members.map(m => `
    <tr>
      <td>${esc(m.name)}</td>
      <td>${esc(m.role)}</td>
      <td>${esc(m.tailscale_ip)}</td>
      <td>${esc(m.os)}</td>
      <td>${m.gpu_vram_gb || '-'} GB</td>
      <td>${esc(m.inference_engine)}</td>
      <td>${esc(m.connection_type)}</td>
      <td>${fmtAge(m.age_s)} ago</td>
      <td><span class="pill ${m.label.toLowerCase()}">${m.label}</span></td>
    </tr>`).join("") || `<tr><td colspan="9" class="empty">no members</td></tr>`;

  const md = $("models");
  md.innerHTML = s.models.map(m => `
    <tr>
      <td>${esc(m.name)}</td>
      <td>${m.size_gb.toFixed(1)} GB</td>
      <td><span class="pill ${m.loaded ? 'loaded' : 'idle'}">${m.reloading ? 'reloading' : (m.loaded ? 'loaded' : 'idle')}</span></td>
      <td>${m.worker_nodes.length ? m.worker_nodes.map(esc).join(", ") : '<span style="color:var(--muted)">coordinator only</span>'}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="empty">no models registered</td></tr>`;

  const ks = $("keys");
  ks.innerHTML = s.keys.map(k => `
    <tr>
      <td>${esc(k.label)}</td>
      <td>${esc(k.key_id)}...</td>
      <td>${k.total_requests}</td>
      <td>${k.total_tokens.toLocaleString()}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="empty">no API keys</td></tr>`;

  const u = $("usage");
  u.innerHTML = s.recent_usage.slice().reverse().map(r => `
    <tr>
      <td>${new Date(r.timestamp).toLocaleTimeString()}</td>
      <td>${esc(r.model)}</td>
      <td>${r.prompt_tokens} / ${r.completion_tokens}</td>
      <td>${r.latency_ms} ms</td>
      <td>${esc(r.backend)}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="empty">no requests in last 10 min</td></tr>`;
}

poll();
setInterval(poll, 2000);
</script>
</body>
</html>"""


@router.get("/dashboard")
def dashboard() -> HTMLResponse:
    return HTMLResponse(_DASHBOARD_HTML)
