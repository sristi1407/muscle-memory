"""A minimal operator console for the live session.

Deliberately bare (the brief scopes a full co-browsing console out), but it is a real
control surface, not a mock:

  * shows the open InterventionRequest: capability, step, why it stopped, expected vs. observed;
  * streams the live session as screenshots (PII masked before capture);
  * lets the operator take control, click on the screenshot, type, and press keys —
    all executed on the SAME browser session the automation was using;
  * hands control back: Resume / Abort, or Approve / Deny for a risky step.

It speaks pixels and keystrokes on purpose, which works for any surface, including a
desktop app with no DOM. Bound to 127.0.0.1 with no auth; a production console would
sit behind SSO with per-request tokens (see REPORT.md).
"""
import logging
from threading import Thread

from flask import Flask, Response, jsonify, request
from werkzeug.serving import make_server

from .control import ControlChannel, ControlError

logging.getLogger("werkzeug").setLevel(logging.WARNING)  # the console polls every second; keep stdout readable


def create_app(channel: ControlChannel) -> Flask:
    app = Flask(__name__)

    def body() -> dict:
        return request.get_json(silent=True) or {}

    @app.errorhandler(ControlError)
    def _control_error(e):
        return jsonify(error=str(e)), 409

    @app.get("/")
    def index():
        return Response(PAGE, mimetype="text/html")

    @app.get("/api/state")
    def state():
        return jsonify(channel.state())

    @app.get("/api/frame")
    def frame():
        if not channel.latest_frame:
            return Response(status=204)
        return Response(channel.latest_frame, mimetype="image/png",
                        headers={"Cache-Control": "no-store"})

    @app.post("/api/claim")
    def claim():
        channel.claim(body().get("operator", ""))
        return jsonify(ok=True)

    @app.post("/api/command")
    def command():
        data = body()
        channel.command(data.get("operator", ""), data)
        return jsonify(ok=True)

    @app.post("/api/resolve")
    def resolve():
        data = body()
        channel.resolve(data.get("operator", ""), data.get("resolution", ""), data.get("note"))
        return jsonify(ok=True)

    return app


class OperatorConsole:
    """Runs the console in a background thread next to the automation."""

    def __init__(self, channel: ControlChannel, host: str = "127.0.0.1", port: int = 5050):
        self.url = f"http://{host}:{port}"
        self._server = make_server(host, port, create_app(channel), threaded=True)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> "OperatorConsole":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Operator Console</title>
<style>
  :root { --bg:#f4f6f9; --card:#fff; --ink:#1b2430; --muted:#5d6b7c; --line:#dde3ea;
          --auto:#1d7a46; --wait:#b26a00; --human:#1f5fbf; --bad:#b42318; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.45 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         background:var(--bg); color:var(--ink); }
  header { display:flex; align-items:center; gap:12px; padding:12px 20px; background:#12233a; color:#fff; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  header .sub { color:#a9b8cc; font-size:12px; }
  .badge { margin-left:auto; padding:4px 10px; border-radius:999px; font-weight:600; font-size:12px;
           letter-spacing:.02em; background:#2c3e57; }
  .badge.automation { background:var(--auto); } .badge.awaiting_human { background:var(--wait); }
  .badge.human { background:var(--human); }
  main { display:grid; grid-template-columns:minmax(0,1fr) 380px; gap:16px; padding:16px 20px; }
  @media (max-width: 980px) { main { grid-template-columns:1fr; } }
  .card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:0 0 10px; }
  #view { position:relative; }
  #frame { width:100%; display:block; border:1px solid var(--line); border-radius:4px; background:#e9edf2;
           min-height:240px; }
  #frame.live { cursor:crosshair; outline:3px solid var(--human); }
  .hint { color:var(--muted); font-size:12px; margin-top:6px; }
  dl { display:grid; grid-template-columns:96px 1fr; gap:4px 10px; margin:0; }
  dt { color:var(--muted); } dd { margin:0; overflow-wrap:anywhere; }
  .reason { color:var(--bad); font-weight:600; }
  .row { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
  input[type=text], input[type=password] { flex:1; min-width:0; padding:7px 9px; border:1px solid #c3ccd7;
           border-radius:6px; font:inherit; }
  button { padding:7px 12px; border-radius:6px; border:1px solid #c3ccd7; background:#fff; font:inherit;
           cursor:pointer; }
  button:disabled { opacity:.45; cursor:not-allowed; }
  button.primary { background:var(--human); border-color:var(--human); color:#fff; }
  button.go { background:var(--auto); border-color:var(--auto); color:#fff; }
  button.stop { background:var(--bad); border-color:var(--bad); color:#fff; }
  ol { margin:0; padding-left:20px; } ol li { margin:2px 0; overflow-wrap:anywhere; }
  #msg { color:var(--bad); min-height:18px; margin-top:8px; font-size:13px; }
  .stack > .card + .card { margin-top:16px; }
  label.small { color:var(--muted); font-size:12px; display:flex; gap:6px; align-items:center; }
</style></head>
<body>
<header>
  <div><h1>Operator Console</h1><div class="sub">Muscle Memory · human-in-the-loop handoff</div></div>
  <span id="badge" class="badge">connecting…</span>
</header>
<main>
  <section class="card" id="view">
    <h2>Live session</h2>
    <img id="frame" alt="Live view of the automated browser session">
    <div class="hint" id="viewHint">This is the same browser session the automation was using.</div>
  </section>
  <section class="stack">
    <div class="card"><h2>Status</h2><div id="idle">Automation is running. Nothing needs you right now.</div></div>
    <div class="card" id="req" hidden>
      <h2 id="reqTitle">Intervention</h2>
      <dl>
        <dt>Capability</dt><dd id="cap"></dd>
        <dt>Stopped at</dt><dd id="step"></dd>
        <dt>Why</dt><dd id="reason" class="reason"></dd>
        <dt>Expected</dt><dd id="expected"></dd>
        <dt>Observed</dt><dd id="observed"></dd>
      </dl>
      <div class="row">
        <input id="op" type="text" value="operator1" aria-label="Operator name">
        <button id="claim" class="primary">Take control</button>
      </div>
      <div class="row">
        <input id="text" type="text" placeholder="Type into the focused field" aria-label="Text to type">
        <button id="typeBtn" class="needs-control">Type</button>
      </div>
      <div class="row">
        <button class="needs-control key" data-key="Enter">Enter</button>
        <button class="needs-control key" data-key="Tab">Tab</button>
        <button class="needs-control key" data-key="Backspace">Backspace</button>
        <label class="small"><input id="hide" type="checkbox"> hide what I type</label>
      </div>
      <div class="row"><input id="note" type="text" placeholder="Note for the record (optional)" aria-label="Note"></div>
      <div class="row" id="decisions"></div>
      <div id="msg"></div>
    </div>
    <div class="card"><h2>What the human did</h2><ol id="actions"></ol>
      <div class="hint" id="noActions">Nothing yet.</div></div>
  </section>
</main>
<script>
const $ = id => document.getElementById(id);
let state = null;
const me = () => $('op').value.trim();
const LABELS = { resume: 'Resume automation', abort: 'Abort run', approve: 'Approve step', deny: 'Deny' };
const STYLE = { resume: 'go', approve: 'go', abort: 'stop', deny: 'stop' };
const BADGE = { automation: 'Automation in control', awaiting_human: 'Waiting for an operator',
                human: 'Human in control' };

async function api(path, payload) {
  const r = await fetch(path, payload === undefined ? {} : {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { flash(data.error || r.statusText); throw new Error(data.error); }
  return data;
}
function flash(text) { $('msg').textContent = text; setTimeout(() => { $('msg').textContent = ''; }, 5000); }
const holding = () => state && state.controller === 'human' && state.request && state.request.operator === me();

function render() {
  const c = state.controller, r = state.request;
  $('badge').textContent = BADGE[c] + (c === 'human' && r ? ` · ${r.operator}` : '');
  $('badge').className = 'badge ' + c;
  $('req').hidden = !r;
  $('frame').classList.toggle('live', holding());
  $('viewHint').textContent = holding() ? 'You have control: click the screenshot to click the page.'
                                        : 'This is the same browser session the automation was using.';
  const last = state.history.at(-1);
  $('idle').textContent =
      c === 'awaiting_human' ? 'Automation has paused and is waiting for an operator to take control.'
    : c === 'human' && r ? `${r.operator} is driving the live session. Automation is locked out.`
    : last ? `Control is back with automation (${last.resolution} by ${last.operator || 'nobody'}).`
    : 'Automation is running. Nothing needs you right now.';
  const acts = r ? r.actions : (last?.actions || []);
  $('actions').replaceChildren(...acts.map(a => Object.assign(document.createElement('li'),
                                                             { textContent: `${a.operator}: ${a.detail}` })));
  $('noActions').hidden = acts.length > 0;
  if (!r) return;
  $('reqTitle').textContent = r.kind === 'approval' ? 'Approval needed' : 'Automation is stuck';
  $('cap').textContent = `${r.capability_id} v${r.capability_version} · run ${r.run_id}`;
  $('step').textContent = `step ${r.step_index}: ${r.step_description}`;
  $('reason').textContent = r.reason;
  $('expected').textContent = r.expected;
  $('observed').textContent = r.observed;
  $('claim').disabled = c !== 'awaiting_human';
  document.querySelectorAll('.needs-control').forEach(b => { b.disabled = !holding(); });
  const want = r.allowed.join(',');
  if ($('decisions').dataset.allowed !== want) {
    $('decisions').dataset.allowed = want;
    $('decisions').replaceChildren(...r.allowed.map(res => {
      const b = Object.assign(document.createElement('button'),
                              { textContent: LABELS[res], className: 'needs-control ' + STYLE[res] });
      b.onclick = () => api('/api/resolve', { operator: me(), resolution: res, note: $('note').value })
                        .then(() => { $('note').value = ''; });
      return b;
    }));
  }
  $('decisions').querySelectorAll('button').forEach(b => { b.disabled = !holding(); });
}

async function poll() {
  try { state = await api('/api/state'); render(); } catch (e) {}
  setTimeout(poll, 1000);
}
function refreshFrame() {
  const img = new Image();
  img.onload = () => { $('frame').src = img.src; };
  img.src = '/api/frame?t=' + Date.now();
}

$('frame').addEventListener('click', e => {
  if (!holding()) return flash('Take control first.');
  const img = e.currentTarget;
  api('/api/command', { operator: me(), kind: 'click',
                        x: e.offsetX * img.naturalWidth / img.clientWidth,
                        y: e.offsetY * img.naturalHeight / img.clientHeight });
});
$('claim').onclick = () => { if (!me()) return flash('Enter your operator name.'); api('/api/claim', { operator: me() }); };
$('typeBtn').onclick = () => {
  const text = $('text').value;
  if (text) api('/api/command', { operator: me(), kind: 'type', text }).then(() => { $('text').value = ''; });
};
$('text').addEventListener('keydown', e => { if (e.key === 'Enter') $('typeBtn').click(); });
document.querySelectorAll('.key').forEach(b => {
  b.onclick = () => api('/api/command', { operator: me(), kind: 'key', key: b.dataset.key });
});
$('hide').onchange = () => { $('text').type = $('hide').checked ? 'password' : 'text'; };

poll(); refreshFrame(); setInterval(refreshFrame, 800);
</script>
</body></html>
"""
