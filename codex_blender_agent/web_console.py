from __future__ import annotations

import html
import json
import mimetypes
import secrets
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlparse


StateProvider = Callable[[], dict[str, Any]]
ControlHandler = Callable[[str], dict[str, Any]]

SAFE_CONTROL_ACTIONS = {
    "stop_review",
    "continue_review",
    "refresh_state",
    "validate_now",
    "plan_viewpoints",
    "show_overlays",
    "clear_overlays",
    "apply_safe_repair",
}


@dataclass(frozen=True)
class WebConsoleStatus:
    running: bool
    url: str
    host: str
    port: int
    token: str
    error: str = ""

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "url": self.url,
            "host": self.host,
            "port": self.port,
            "error": self.error,
        }


class WebConsoleServer:
    """Small localhost observability console for visual-review runs.

    The server is deliberately narrow: it serves cached runtime state and a few
    fixed control actions. It does not expose arbitrary Blender or tool calls.
    """

    def __init__(
        self,
        *,
        state_provider: StateProvider,
        control_handler: ControlHandler | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        token: str | None = None,
    ) -> None:
        self.state_provider = state_provider
        self.control_handler = control_handler
        self.host = host
        self.requested_port = int(port or 0)
        self.token = token or secrets.token_urlsafe(18)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._error = ""
        self._live_sequence = 0

    @property
    def running(self) -> bool:
        return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    @property
    def port(self) -> int:
        if self._httpd is None:
            return 0
        return int(self._httpd.server_address[1])

    @property
    def url(self) -> str:
        if not self.running:
            return ""
        return f"http://{self.host}:{self.port}/?token={quote(self.token)}"

    def status(self) -> WebConsoleStatus:
        return WebConsoleStatus(self.running, self.url, self.host, self.port, self.token, self._error)

    def start(self) -> WebConsoleStatus:
        if self.running:
            return self.status()
        server = self

        class Handler(_ConsoleHandler):
            owner = server

        try:
            self._httpd = ThreadingHTTPServer((self.host, self.requested_port), Handler)
            self._httpd.daemon_threads = True
            self._thread = threading.Thread(target=self._httpd.serve_forever, name="CodexBlenderWebConsole", daemon=True)
            self._thread.start()
            self._error = ""
        except Exception as exc:
            self._error = str(exc)
            self._httpd = None
            self._thread = None
        return self.status()

    def stop(self) -> WebConsoleStatus:
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception as exc:
                self._error = str(exc)
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        return self.status()

    def public_state(self) -> dict[str, Any]:
        try:
            state = dict(self.state_provider() or {})
        except Exception as exc:
            state = {"error": str(exc)}
        cached_web = state.get("web_console", {}) if isinstance(state.get("web_console", {}), dict) else {}
        public_web = self.status().as_public_dict()
        if "auto_started" in cached_web:
            public_web["auto_started"] = bool(cached_web.get("auto_started", False))
        state["web_console"] = public_web
        return state

    def live_state(self) -> dict[str, Any]:
        state = self.public_state()
        try:
            sequence = int(state.get("sequence", 0) or 0)
        except Exception:
            sequence = 0
        if sequence > 0:
            self._live_sequence = max(self._live_sequence, sequence)
            state["sequence"] = sequence
        else:
            self._live_sequence += 1
            state["sequence"] = self._live_sequence
        return state

    def execute_control(self, action: str) -> dict[str, Any]:
        action = (action or "").strip().lower().replace("-", "_")
        if action not in SAFE_CONTROL_ACTIONS:
            return {"ok": False, "error": f"Unsupported web console action: {action}"}
        if self.control_handler is None:
            return {"ok": False, "action": action, "error": f"Unsupported web console action: {action}"}
        return dict(self.control_handler(action) or {"ok": True, "action": action})


class _ConsoleHandler(BaseHTTPRequestHandler):
    owner: WebConsoleServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return None

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urlparse(self.path)
        if parsed.path == "/":
            if not self._authorized(parsed):
                self._write_text("Missing or invalid web console token.", HTTPStatus.FORBIDDEN)
                return
            self._write_html(_html_shell(self.owner.token))
            return
        if not self._authorized(parsed):
            self._write_json({"ok": False, "error": "missing_or_invalid_token"}, HTTPStatus.FORBIDDEN)
            return
        if parsed.path == "/api/status":
            self._write_json(self.owner.public_state())
            return
        if parsed.path == "/api/live":
            self._write_json(self.owner.live_state())
            return
        if parsed.path == "/api/runs":
            self._write_json(_section_payload(self.owner.public_state(), "runs"))
            return
        if parsed.path.startswith("/api/runs/"):
            run_id = parsed.path.removeprefix("/api/runs/").strip("/")
            self._write_json(_run_payload(self.owner.public_state(), run_id))
            return
        if parsed.path in {
            "/api/visual-review",
            "/api/validation",
            "/api/checks",
            "/api/algorithms",
            "/api/intent-manifest",
            "/api/constraints",
            "/api/repair-plan",
            "/api/overlays",
            "/api/screenshots",
            "/api/logs",
            "/api/timeline",
            "/api/critic",
            "/api/raw",
        }:
            self._write_json(_section_payload(self.owner.public_state(), parsed.path.rsplit("/", 1)[-1]))
            return
        if parsed.path == "/api/screenshot":
            self._serve_screenshot(parsed)
            return
        self._write_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urlparse(self.path)
        if not self._authorized(parsed):
            self._write_json({"ok": False, "error": "missing_or_invalid_token"}, HTTPStatus.FORBIDDEN)
            return
        prefix = "/api/control/"
        if not parsed.path.startswith(prefix):
            self._write_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        action = parsed.path[len(prefix) :]
        self._write_json(self.owner.execute_control(action))

    def _authorized(self, parsed) -> bool:
        query = parse_qs(parsed.query)
        token = (query.get("token") or [""])[0] or self.headers.get("X-Codex-Token", "")
        return token == self.owner.token

    def _serve_screenshot(self, parsed) -> None:
        query = parse_qs(parsed.query)
        raw_path = unquote((query.get("path") or [""])[0])
        if not raw_path:
            self._write_json({"ok": False, "error": "missing_path"}, HTTPStatus.BAD_REQUEST)
            return
        path = Path(raw_path).expanduser()
        state = self.owner.public_state()
        allowed = [Path(item).expanduser() for item in state.get("allowed_screenshot_roots", []) if str(item).strip()]
        if not _is_allowed_path(path, allowed):
            self._write_json({"ok": False, "error": "path_not_allowed"}, HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or not path.is_file():
            self._write_json({"ok": False, "error": "screenshot_not_found"}, HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _write_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _write_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def _is_allowed_path(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return False
    for root in roots:
        try:
            if resolved.is_relative_to(root.resolve()):
                return True
        except Exception:
            continue
    return False


def _section_payload(state: dict[str, Any], section: str) -> dict[str, Any]:
    if section == "visual-review":
        return {"visual_review": state.get("visual_review", {}), "automation": state.get("automation", {}), "runs": state.get("runs", {})}
    if section == "validation":
        return {"validation": state.get("validation", {})}
    if section == "checks":
        return {"checks": state.get("checks", [])}
    if section == "algorithms":
        return {"algorithms": state.get("algorithms", [])}
    if section in {"intent-manifest", "intent_manifest"}:
        return {"intent_manifest": state.get("intent_manifest", {})}
    if section == "constraints":
        return {"constraints": state.get("constraints", {})}
    if section == "repair-plan":
        return {"repair_plan": state.get("repair_plan", {})}
    if section == "overlays":
        return {"overlays": state.get("overlays", {})}
    if section == "screenshots":
        return {"screenshots": state.get("screenshots", [])}
    if section == "logs":
        return {"logs": state.get("logs", []), "startup_trace": state.get("startup_trace", []), "backend_error": state.get("backend_error", {})}
    if section == "timeline":
        return {"timeline": state.get("timeline", [])}
    if section == "critic":
        return {"critic": state.get("critic", {})}
    if section == "runs":
        return {"runs": state.get("runs", {}), "visual_review": state.get("visual_review", {})}
    if section == "raw":
        return {"raw": state}
    return state


def _run_payload(state: dict[str, Any], run_id: str) -> dict[str, Any]:
    runs = state.get("runs", {})
    if isinstance(runs, dict):
        index = runs.get("index", {})
        if isinstance(index, dict) and run_id in index:
            return {"run": index[run_id], "run_id": run_id, "runs": runs}
        active = runs.get("active", {})
        if isinstance(active, dict) and str(active.get("run_id", "")) == run_id:
            return {"run": active, "run_id": run_id, "runs": runs}
        recent = list(runs.get("recent", []) or [])
        for item in recent:
            if isinstance(item, dict) and str(item.get("run_id", "")) == run_id:
                return {"run": item, "run_id": run_id, "runs": runs}
    visual_review = state.get("visual_review", {})
    if isinstance(visual_review, dict):
        active = visual_review.get("active_run", {})
        if isinstance(active, dict) and str(active.get("run_id", "")) == run_id:
            return {"run": active, "run_id": run_id, "visual_review": visual_review}
        for item in list(visual_review.get("recent_runs", []) or []):
            if isinstance(item, dict) and str(item.get("run_id", "")) == run_id:
                return {"run": item, "run_id": run_id, "visual_review": visual_review}
    return {"run": {}, "run_id": run_id, "error": "run_not_found"}


def _html_shell(token: str) -> str:
    escaped_token = html.escape(token, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Codex Live Review Console</title>
<style>
:root {{
  --bg: #08100d;
  --panel: #101916;
  --panel-2: #16231e;
  --text: #e9f6ef;
  --muted: #96b0a4;
  --good: #3ee08d;
  --warn: #ffb84d;
  --bad: #ff6c6c;
  --line: #274338;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: radial-gradient(circle at 10% 0%, rgba(62,224,141,.12), transparent 24%), linear-gradient(135deg, #06100d, #11160f 55%, #17130d);
  color: var(--text);
  font-family: ui-monospace, "Cascadia Code", "Segoe UI Mono", monospace;
}}
header {{
  padding: 18px 22px 16px;
  border-bottom: 1px solid var(--line);
  background: rgba(6, 16, 12, .94);
  position: sticky;
  top: 0;
  z-index: 10;
}}
.title-row {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
h1 {{ margin: 0; font-size: 24px; letter-spacing: .04em; }}
.banner {{ font-size: 18px; font-weight: 800; color: var(--good); }}
.banner.reconnecting {{ color: #7ed7ff; }}
.sub {{ color: var(--muted); font-size: 12px; margin-top: 8px; }}
main {{ padding: 18px; display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 18px; }}
.panel, .section {{ background: rgba(16, 25, 22, .96); border: 1px solid var(--line); border-radius: 14px; padding: 14px; box-shadow: 0 12px 32px rgba(0,0,0,.28); }}
.panel {{ position: sticky; top: 92px; align-self: start; }}
button {{ background: #203d31; color: var(--text); border: 1px solid #37674f; border-radius: 10px; padding: 8px 10px; margin: 4px 4px 4px 0; cursor: pointer; }}
button:hover {{ border-color: var(--good); }}
button.active {{ background: #2f5e47; border-color: var(--good); }}
.tabs {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
.grid.tight {{ grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }}
.card {{ background: var(--panel-2); border: 1px solid var(--line); border-radius: 12px; padding: 12px; overflow: hidden; }}
.pill {{ display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; margin: 3px 6px 3px 0; color: var(--muted); }}
.pill.good {{ color: var(--good); border-color: rgba(62,224,141,.45); }}
.pill.warn {{ color: var(--warn); border-color: rgba(255,184,77,.45); }}
.pill.bad {{ color: var(--bad); border-color: rgba(255,108,108,.45); }}
.ok {{ color: var(--good); }}
.warn {{ color: var(--warn); }}
.bad {{ color: var(--bad); }}
.muted {{ color: var(--muted); }}
pre {{ white-space: pre-wrap; word-break: break-word; max-height: 420px; overflow: auto; background: #07100d; border: 1px solid var(--line); border-radius: 10px; padding: 10px; }}
img {{ width: 100%; border-radius: 10px; border: 1px solid var(--line); background: #07100d; }}
.shots {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }}
.row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
.kv {{ display: grid; grid-template-columns: 150px 1fr; gap: 8px 12px; }}
.kv div {{ padding: 2px 0; }}
.table {{ width: 100%; border-collapse: collapse; }}
.table th, .table td {{ border-bottom: 1px solid rgba(39,67,56,.75); padding: 8px 6px; text-align: left; vertical-align: top; }}
.table th {{ color: var(--muted); font-weight: 700; }}
.stack {{ display: grid; gap: 12px; }}
.feed {{ display: grid; gap: 10px; }}
.section-block {{ scroll-margin-top: 108px; margin-bottom: 14px; }}
.section-block h2 {{ margin: 0 0 10px; font-size: 18px; letter-spacing: .03em; }}
.section-block h3 {{ margin: 0 0 8px; font-size: 14px; color: var(--muted); }}
.nav-links {{ display: grid; gap: 6px; margin: 10px 0 12px; }}
.nav-links a {{
  display: block;
  color: var(--text);
  text-decoration: none;
  padding: 7px 10px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: #13201b;
}}
.nav-links a:hover {{ border-color: var(--good); }}
.status-banner {{
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(62,224,141,.45);
  background: linear-gradient(180deg, rgba(62,224,141,.14), rgba(18,28,23,.95));
  color: var(--good);
  font-weight: 800;
  letter-spacing: .03em;
}}
.status-banner.reconnecting {{
  border-color: rgba(126,215,255,.5);
  background: linear-gradient(180deg, rgba(126,215,255,.15), rgba(18,28,23,.95));
  color: #7ed7ff;
}}
.status-banner.warn {{
  border-color: rgba(255,184,77,.5);
  background: linear-gradient(180deg, rgba(255,184,77,.14), rgba(18,28,23,.95));
  color: var(--warn);
}}
@media (max-width: 980px) {{
  main {{ grid-template-columns: 1fr; }}
  .panel {{ position: static; }}
}}
</style>
</head>
<body>
<header>
  <div class="title-row">
    <h1>Codex Live Review Console</h1>
    <div class="banner" id="phase">LOADING</div>
  </div>
  <div class="sub" id="summary">Waiting for Blender runtime state...</div>
  <div class="sub" id="subsummary"></div>
</header>
<main>
  <aside class="panel">
    <div class="row">
      <button onclick="control('stop_review')">Stop</button>
      <button onclick="control('continue_review')">Continue</button>
      <button onclick="control('refresh_state')">Refresh</button>
    </div>
    <div class="row">
      <button onclick="control('validate_now')">Validate now</button>
      <button onclick="control('plan_viewpoints')">Plan viewpoints</button>
    </div>
    <div class="row">
      <button onclick="control('show_overlays')">Show overlays</button>
      <button onclick="control('clear_overlays')">Clear overlays</button>
      <button onclick="control('apply_safe_repair')">Apply safe repair</button>
    </div>
    <div class="nav-links" id="navLinks"></div>
    <div id="navFacts" class="muted"></div>
  </aside>
  <section class="section">
    <div id="content"></div>
  </section>
</main>
<template id="live-page-skeleton">
  <section id="live-status"></section>
  <section id="prompt-timeline"></section>
  <section id="action-feed"></section>
  <section id="console-log"></section>
  <section id="scene-now"></section>
  <section id="geometry-checks"></section>
  <section id="screenshots"></section>
  <section id="issues"></section>
  <section id="critic"></section>
  <section id="raw-json"></section>
</template>
<script>
const TOKEN = "{escaped_token}";
const SECTION_ENDPOINTS = {{
  live: '/api/live',
  overview: '/api/status',
  screenshots: '/api/screenshots',
  algorithms: '/api/algorithms',
  intent: '/api/intent-manifest',
  constraints: '/api/constraints',
  issues: '/api/validation',
  repair: '/api/repair-plan',
  critic: '/api/critic',
  logs: '/api/logs',
  timeline: '/api/timeline',
  runs: '/api/runs',
  raw: '/api/raw',
  visual: '/api/visual-review',
}};
const TABS = [
  ['overview', 'Overview'],
  ['screenshots', 'Screenshots'],
  ['algorithms', 'Geometry Algorithms'],
  ['intent', 'Intent Manifest'],
  ['constraints', 'Constraint Graph'],
  ['issues', 'Issues'],
  ['repair', 'Repair Plan'],
  ['critic', 'Critic'],
  ['timeline', 'Timeline'],
  ['runs', 'Runs'],
  ['raw', 'Raw JSON'],
];
const SECTIONS = [
  ['live-status', 'Live Status'],
  ['prompt-timeline', 'Prompt Timeline'],
  ['action-feed', 'Codex Action Feed'],
  ['console-log', 'Console Log'],
  ['scene-now', 'Scene Now'],
  ['geometry-checks', 'Geometry Checks'],
  ['screenshots', 'Screenshots'],
  ['issues', 'Issues And Repair'],
  ['critic', 'Critic And Patch'],
  ['raw-json', 'Advanced Raw JSON'],
];
let ACTIVE_TAB = 'overview';
let DATA = {{}};
const api = path => fetch(path + (path.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN), {{cache:'no-store'}}).then(r => r.json());
async function control(action) {{
  const result = await fetch('/api/control/' + action + '?token=' + encodeURIComponent(TOKEN), {{method: 'POST'}});
  const payload = await result.json();
  const status = payload.ok ? ('ACTION: ' + action.toUpperCase()) : ('NEEDS ATTENTION: ' + (payload.error || action));
  document.getElementById('summary').textContent = status;
  await load();
}}
function esc(v) {{ return String(v ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
function json(v) {{ return '<pre>' + esc(JSON.stringify(v, null, 2)) + '</pre>'; }}
function shotImg(path) {{ return '/api/screenshot?token=' + encodeURIComponent(TOKEN) + '&path=' + encodeURIComponent(path); }}
function issueClass(sev) {{ return sev === 'critical' || sev === 'high' ? 'bad' : (sev === 'medium' ? 'warn' : 'muted'); }}
function pill(text, klass='') {{ return '<span class="pill ' + klass + '">' + esc(text) + '</span>'; }}
function sectionBlock(id, title, body, subtitle='') {{
  return '<section class="section-block" id="' + id + '"><div class="card"><h2>' + esc(title) + '</h2>' + (subtitle ? '<div class="muted" style="margin-bottom:8px;">' + esc(subtitle) + '</div>' : '') + body + '</div></section>';
}}
function renderLiveStatus(state) {{
  const auto = state.automation || {{}};
  const validation = state.validation || {{}};
  const service = state.service || {{}};
  const web = state.web_console || {{}};
  const active = !!(auto.active || auto.phase || (validation.issue_count || 0) > 0);
  const bannerText = service.stream_recovering ? 'RECONNECTING' : (active ? 'ACTIVE' : 'READY');
  const phase = auto.phase_label || auto.phase || (service.stream_recovering ? 'RECONNECTING' : 'IDLE');
  const current = auto.activity || state.current_action || validation.validation_summary || service.status || '';
  const loginState = service.account ? ('Logged in as ' + service.account + (service.plan ? ' / ' + service.plan : '')) : 'Login not confirmed';
  const statusClass = service.stream_recovering ? 'status-banner reconnecting' : (active ? 'status-banner' : 'status-banner warn');
  const scoreValue = Number(auto.score ?? validation.asset_score ?? 0);
  return `
    <div class="${{statusClass}}">
      ${{bannerText}}: ${{esc(phase)}}
    </div>
    <div class="grid" style="margin-top:12px;">
      <div class="card">
        <div class="kv">
          <div>Sequence</div><div>${{esc(state.sequence ?? 0)}}</div>
          <div>Run</div><div>${{esc(auto.run_id || ((state.visual_review || {{}}).active_run || {{}}).run_id || 'none')}}</div>
          <div>Pass</div><div>${{esc(auto.pass || 0)}} / ${{esc(auto.max_passes || 0)}}</div>
          <div>Score</div><div>${{esc(scoreValue.toFixed(2))}}</div>
        </div>
      </div>
      <div class="card">
        <div class="kv">
          <div>Service</div><div>${{esc(service.status || '')}}</div>
          <div>Login</div><div>${{esc(loginState)}}</div>
          <div>Recovering</div><div>${{service.stream_recovering ? '<span class="warn">YES</span>' : '<span class="ok">NO</span>'}}</div>
          <div>Web console</div><div>${{esc(web.running ? 'running' : 'stopped')}}${{web.url ? ' | ' + esc(web.url) : ''}}</div>
        </div>
      </div>
      <div class="card">
        <div class="kv">
          <div>Issues</div><div>${{esc(validation.issue_count ?? ((validation.issues || []).length || 0))}}</div>
          <div>Critical</div><div>${{esc(validation.critical_count ?? 0)}}</div>
          <div>Report</div><div>${{esc(validation.report_id || 'none')}}</div>
          <div>Current</div><div>${{esc(current)}}</div>
        </div>
      </div>
    </div>
  `;
}}
function renderPromptTimeline(state) {{
  const events = state.prompt_events || ((state.visual_review || {{}}).prompt_events || []);
  const header = [];
  if (state.original_prompt) header.push('<div class="card"><h3>Original Prompt</h3><div>' + esc(state.original_prompt) + '</div></div>');
  if (state.expanded_prompt) header.push('<div class="card"><h3>Expanded Prompt</h3><div>' + esc(state.expanded_prompt) + '</div></div>');
  const timeline = events.length ? '<div class="feed" style="margin-top:12px;">' + events.map(event => `
    <div class="card">
      <div class="row">
        ${{pill(event.kind || event.phase || 'prompt', event.status === 'failed' ? 'bad' : 'good')}}
        ${{pill(event.actor || 'user')}}
        ${{pill(event.status || 'done')}}
      </div>
      <div><b>${{esc(event.label || event.title || event.kind || 'prompt event')}}</b></div>
      <div class="muted">${{esc(event.timestamp || event.started_at || event.created_at || '')}}</div>
      <div class="muted">${{esc(event.summary || event.detail || event.prompt || '')}}</div>
    </div>`).join('') + '</div>' : '<div class="card muted" style="margin-top:12px;">No prompt events recorded yet.</div>';
  return (header.length ? '<div class="grid">' + header.join('') + '</div>' : '') + timeline;
}}
function renderActionFeed(state) {{
  const events = state.automation_events || state.timeline || [];
  if (!events.length) return '<div class="card muted">No action feed yet.</div>';
  return '<div class="feed">' + events.map(event => `
    <div class="card">
      <div class="row">
        ${{pill(event.actor || 'codex', 'good')}}
        ${{pill(event.phase || event.label || 'event')}}
        ${{pill(event.status || 'done', event.status === 'failed' ? 'bad' : (event.status === 'running' ? 'warn' : 'good'))}}
        ${{pill(event.event_id || event.id || '')}}
      </div>
      <div><b>${{esc(event.label || event.name || 'Action')}}</b></div>
      <div class="muted">${{esc(event.timestamp || event.started_at || event.created_at || '')}}</div>
      <div class="muted">${{esc(event.summary || event.detail || event.message || '')}}</div>
    </div>`).join('') + '</div>';
}}
function renderBackendError(state) {{
  const error = state.backend_error || {{}};
  if (!error || !Object.keys(error).length) return '';
  return `<div class="card" style="border-color:rgba(255,107,107,.45);">
    <h3 class="bad">${{esc(error.title || 'Backend Error')}}</h3>
    <div>${{esc(error.summary || '')}}</div>
    <div class="muted">${{esc(error.recovery || '')}}</div>
    <details style="margin-top:8px;"><summary>Raw diagnostic</summary>${{json(error.raw || error)}}</details>
  </div>`;
}}
function renderConsoleLog(state) {{
  const logs = state.logs || [];
  const startup = state.startup_trace || [];
  const backend = renderBackendError(state);
  const startupHtml = startup.length ? '<div class="feed">' + startup.slice(-12).map(row => `
    <div class="card">
      <div class="row">${{pill(row.label || row.type || 'event', row.status === 'failed' ? 'bad' : (row.status === 'running' ? 'warn' : 'good'))}}${{pill(row.type || '')}}</div>
      <div class="muted">${{esc(row.created_at || row.timestamp || '')}}</div>
      <div>${{esc(row.summary || '')}}</div>
    </div>`).join('') + '</div>' : '<div class="card muted">No startup trace yet.</div>';
  const logHtml = logs.length ? '<div class="feed" style="margin-top:12px;">' + logs.slice(-40).reverse().map(row => `
    <div class="card">
      <div class="row">${{pill(row.label || row.type || 'log', row.status === 'failed' ? 'bad' : (row.status === 'running' ? 'warn' : 'good'))}}${{pill(row.status || '')}}${{pill(row.run_id || '')}}</div>
      <div class="muted">${{esc(row.created_at || '')}}</div>
      <div>${{esc(row.summary || '')}}</div>
    </div>`).join('') + '</div>' : '<div class="card muted" style="margin-top:12px;">No console logs recorded yet.</div>';
  return backend + '<div class="card"><h3>Startup Trace</h3>' + startupHtml + '</div>' + logHtml;
}}
function renderSceneNow(state) {{
  const scene = state.scene_snapshot || {{}};
  const objects = scene.objects || scene.scene_objects || [];
  const changes = scene.changes || [];
  const selected = scene.selected_objects || scene.selected || [];
  const materials = scene.materials || [];
  const summary = scene.summary || scene.scene_summary || '';
  const latest = [
    ['Scene', scene.scene_name || state.scene_name || 'Scene'],
    ['Objects', objects.length || scene.object_count || 0],
    ['Selected', selected.length || scene.selected_count || 0],
    ['Materials', materials.length || scene.material_count || 0],
    ['Latest score', scene.validation_score ?? (state.validation || {{}}).asset_score ?? 0],
  ];
  const objectsHtml = objects.length ? '<div class="row">' + objects.slice(0, 12).map(item => pill(item.name || item.label || item, item.type === 'CAMERA' ? '' : 'good')).join('') + '</div>' : '<span class="muted">No object list available.</span>';
  const changesHtml = changes.length ? '<div class="row">' + changes.map(item => pill(item)).join('') + '</div>' : '<span class="muted">No scene deltas recorded yet.</span>';
  return `
    <div class="grid">
      <div class="card">
        <div class="kv">
          ${{latest.map(([key, value]) => '<div>' + esc(key) + '</div><div>' + esc(value) + '</div>').join('')}}
        </div>
      </div>
      <div class="card">
        <h3>Objects</h3>
        ${{objectsHtml}}
      </div>
      <div class="card">
        <h3>Changes</h3>
        ${{changesHtml}}
      </div>
    </div>
    <div class="card" style="margin-top:12px;">
      <h3>Summary</h3>
      <div class="muted">${{esc(summary)}}</div>
    </div>
  `;
}}
function renderLivePage() {{
  const state = DATA.live || DATA.overview || {{}};
  const validation = state.validation || {{}};
  const algorithms = state.algorithms || [];
  const screenshots = state.screenshots || [];
  const critic = state.critic || {{}};
  const criticIssues = critic.issues || [];
  const issues = (validation.issues || validation.top_issues || []);
  const safe = (state.repair_plan || {{}}).safe_actions || [];
  const blocked = (state.repair_plan || {{}}).blocked_operations || [];
  const issueCards = issues.length ? '<div class="feed">' + issues.map(item => `
    <div class="card">
      <div class="row">
        <b class="${{issueClass(item.severity)}}">${{esc(item.severity || 'low')}} / ${{esc(item.type || 'issue')}}</b>
        ${{pill(item.source || 'geometry')}}
      </div>
      <div><b>${{esc(item.target || (item.objects || []).join(', ') || 'scene')}}</b></div>
      <div class="muted">${{esc(item.suggested_fix || item.remediation_hint || '')}}</div>
      <div class="muted">${{esc((item.acceptance_tests || []).join(' | '))}}</div>
      <div>${{json(item.evidence || {{}})}}</div>
    </div>`).join('') + '</div>' : '<div class="card ok">No validation issues reported.</div>';
  const repairCards = `
    <div class="grid" style="margin-top:12px;">
      <div class="card">
        <h3>Safe Actions</h3>
        ${{safe.length ? safe.map(item => '<div class="card" style="margin-bottom:8px;"><b>' + esc(item.issue_type || '') + '</b><div class="muted">' + esc((item.action || {{}}).op || '') + ': ' + esc((item.action || {{}}).reason || '') + '</div><div class="muted">' + esc((item.acceptance_tests || []).join(' | ')) + '</div></div>').join('') : '<span class="muted">No safe actions proposed.</span>'}}
      </div>
      <div class="card">
        <h3>Blocked Ops</h3>
        ${{blocked.length ? blocked.map(item => '<div class="card" style="margin-bottom:8px;"><b class="warn">' + esc(item.operation || '') + '</b><div class="muted">' + esc(item.reason || '') + '</div></div>').join('') : '<span class="muted">No blocked operations listed.</span>'}}
      </div>
    </div>`;
  const geometryCards = algorithms.length ? '<div class="feed">' + algorithms.map(item => `
    <div class="card">
      <div class="row">
        <b>${{esc(item.label || item.id || 'algorithm')}}</b>
        <span class="pill ${{item.status === 'blocked' ? 'bad' : (item.status === 'warn' ? 'warn' : 'good')}}">${{esc(item.status || 'done')}}</span>
      </div>
      <div class="kv">
        <div>Duration</div><div>${{esc(item.duration_ms ?? 'n/a')}} ms</div>
        <div>Inputs</div><div>${{json(item.inputs || {{}})}}</div>
        <div>Thresholds</div><div>${{json(item.thresholds || {{}})}}</div>
        <div>Issue count</div><div>${{esc(item.issue_count ?? 0)}}</div>
        <div>Evidence</div><div>${{json(item.evidence_refs || [])}}</div>
      </div>
    </div>`).join('') + '</div>' : '<div class="card muted">No geometry checks yet.</div>';
  const screenshotCards = screenshots.length ? '<div class="shots">' + screenshots.map(item => `
    <div class="card">
      <img src="${{shotImg(item.path)}}" alt="${{esc(item.view_id || item.label || 'screenshot')}}">
      <div class="row" style="margin-top:8px;">
        ${{pill('pass ' + (item.pass_index || 0), 'good')}}
        ${{pill(item.kind || 'view')}}
        ${{pill('score ' + esc(item.score ?? 0), item.kind === 'audit' ? 'warn' : 'good')}}
      </div>
      <div><b>${{esc(item.view_id || item.label || 'view')}}</b></div>
      <div class="muted">${{esc(item.notes || '')}}</div>
      <div class="muted">${{esc((item.phase || item.phase_label || '') + (item.pass_id ? ' | ' + item.pass_id : ''))}}</div>
      <div class="muted">${{esc(item.source || '')}}</div>
    </div>`).join('') + '</div>' : '<div class="card muted">No screenshots captured yet.</div>';
  const criticCards = `
    <div class="grid">
      <div class="card">
        <h3>Critic</h3>
        <div class="kv">
          <div>Score</div><div>${{esc((critic.pairwise_vs_best && critic.pairwise_vs_best.confidence) ?? critic.critic_score ?? critic.score ?? 0)}}</div>
          <div>Pairwise</div><div>${{json(critic.pairwise_vs_best || {{}})}}</div>
          <div>Summary</div><div>${{esc(critic.summary || '')}}</div>
          <div>Next prompt</div><div>${{esc(critic.next_prompt || '')}}</div>
          <div>View notes</div><div>${{json(critic.viewpoint_notes || [])}}</div>
          <div>Delta prompt</div><div>${{json(critic.delta_prompt || {{}})}}</div>
        </div>
      </div>
      <div class="card">
        <h3>Issue Signature</h3>
        <div class="row">${{(critic.issue_signature || []).length ? critic.issue_signature.map(item => pill(item)).join('') : '<span class="muted">No issue signature.</span>'}}</div>
      </div>
    </div>
    <div class="card" style="margin-top:12px;"><h3>Issues</h3>${{criticIssues.length ? criticIssues.map(item => '<div class="card" style="margin-bottom:8px;"><b>' + esc(item.severity || 'low') + ' / ' + esc(item.category || item.type || '') + '</b><div>' + esc(item.evidence || '') + '</div><div class="muted">' + esc(item.suggested_safe_fix || item.suggested_fix || '') + '</div></div>').join('') : '<span class="muted">No critic issues.</span>'}}</div>
    <div class="card" style="margin-top:12px;"><h3>Prompt</h3>${{json(critic.prompt || '')}}</div>
    <div class="card" style="margin-top:12px;"><h3>Raw Critic JSON</h3>${{json(critic.raw || critic)}}</div>
  `;
  return [
    sectionBlock('live-status', 'Live Status', renderLiveStatus(state), 'Current automation and service state.'),
    sectionBlock('prompt-timeline', 'Prompt Timeline', renderPromptTimeline(state), 'When the prompt was typed, expanded, and submitted.'),
    sectionBlock('action-feed', 'Codex Action Feed', renderActionFeed(state), 'Chronological labels for what Codex is doing.'),
    sectionBlock('console-log', 'Console Log', renderConsoleLog(state), 'Persistent local logs and startup/recovery trace.'),
    sectionBlock('scene-now', 'Scene Now', renderSceneNow(state), 'What is currently in the scene.'),
    sectionBlock('geometry-checks', 'Geometry Checks', geometryCards, 'Validator ledger and thresholds.'),
    sectionBlock('screenshots', 'Screenshots', screenshotCards, 'All live review passes and viewpoints.'),
    sectionBlock('issues', 'Issues And Repair', issueCards + repairCards, 'Validation issues and safe repair guidance.'),
    sectionBlock('critic', 'Critic And Patch', criticCards, 'Structured critic output and bounded patch intent.'),
    sectionBlock('raw-json', 'Advanced Raw JSON', '<details><summary>Advanced Raw JSON</summary><div class="card" style="margin-top:10px;">' + json(state.raw || state) + '</div></details>', 'Collapsed by default in the visual layout.')
  ].join('');
}}
function renderTabs() {{
  document.getElementById('tabs').innerHTML = TABS.map(([id, label]) => '<button class="' + (id === ACTIVE_TAB ? 'active' : '') + '" onclick="setTab(\\'' + id + '\\')">' + esc(label) + '</button>').join('');
}}
function setTab(id) {{
  ACTIVE_TAB = id;
  renderTabs();
  renderPanel();
}}
function sectionCard(title, body) {{
  return '<div class="card"><h2>' + esc(title) + '</h2>' + body + '</div>';
}}
function renderOverview() {{
  const state = DATA.overview || {{}};
  const auto = state.automation || {{}};
  const validation = state.validation || {{}};
  const service = state.service || {{}};
  const runs = state.runs || (state.visual_review || {{}}).runs || {{}};
  const latestIssues = (validation.top_issues || validation.issues || []).slice(0, 6);
  const issueRow = latestIssues.length ? latestIssues.map(i => pill((i.severity || 'low') + ' ' + (i.type || 'issue'), issueClass(i.severity))).join('') : '<span class="muted">No blocking issues.</span>';
  return `
    <div class="grid">
      <div class="card">
        <h2>Automation</h2>
        <div class="kv">
          <div>Phase</div><div>${{esc(auto.phase_label || auto.phase || 'READY')}}</div>
          <div>Run</div><div>${{esc(auto.run_id || 'none')}}</div>
          <div>Pass</div><div>${{esc(auto.pass || 0)}} / ${{esc(auto.max_passes || 0)}}</div>
          <div>Score</div><div>${{esc((auto.score ?? 0).toFixed ? Number(auto.score).toFixed(2) : auto.score ?? 0)}}</div>
          <div>Activity</div><div>${{esc(auto.activity || '')}}</div>
        </div>
      </div>
      <div class="card">
        <h2>Validation</h2>
        <div class="kv">
          <div>Report</div><div>${{esc(validation.report_id || 'none')}}</div>
          <div>Asset score</div><div>${{esc(validation.asset_score ?? 0)}}</div>
          <div>Issues</div><div>${{esc(validation.issue_count ?? 0)}}</div>
          <div>Critical</div><div>${{esc(validation.critical_count ?? 0)}}</div>
          <div>Summary</div><div>${{esc(validation.validation_summary || '')}}</div>
        </div>
      </div>
      <div class="card">
        <h2>Service</h2>
        <div class="kv">
          <div>Status</div><div>${{esc(service.status || '')}}</div>
          <div>Thread</div><div>${{esc(service.thread || '')}}</div>
          <div>Recovering</div><div>${{service.stream_recovering ? '<span class="warn">YES</span>' : '<span class="ok">NO</span>'}}</div>
          <div>Error</div><div>${{esc(service.error_summary || '')}}</div>
          <div>Recovery</div><div>${{esc(service.error_recovery || '')}}</div>
        </div>
      </div>
      <div class="card">
        <h2>Runs</h2>
        <div class="kv">
          <div>Active</div><div>${{esc(runs.active_run_id || auto.run_id || 'none')}}</div>
          <div>Recent</div><div>${{esc((runs.recent || []).length || 0)}}</div>
          <div>Version</div><div>${{esc(state.version || '')}}</div>
          <div>Module</div><div>${{esc(state.module_file || '')}}</div>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:12px;">
      <h2>Top Issues</h2>
      <div class="row">${{issueRow}}</div>
    </div>
  `;
}}
function renderScreenshots() {{
  const items = DATA.screenshots || [];
  if (!items.length) return '<div class="card muted">No screenshots captured yet.</div>';
  return '<div class="shots">' + items.map(item => `
    <div class="card">
      <img src="${{shotImg(item.path)}}" alt="${{esc(item.view_id || item.label || 'screenshot')}}">
      <div class="row" style="margin-top:8px;">
        ${{pill('pass ' + (item.pass_index || 0), 'good')}}
        ${{pill(item.kind || 'view')}}
        ${{pill('score ' + esc(item.score ?? 0), item.kind === 'audit' ? 'warn' : 'good')}}
      </div>
      <div><b>${{esc(item.view_id || item.label || 'view')}}</b></div>
      <div class="muted">${{esc(item.notes || '')}}</div>
      <div class="muted">${{esc((item.phase || item.phase_label || '') + (item.pass_id ? ' | ' + item.pass_id : ''))}}</div>
      <div class="muted">${{esc(item.source || '')}}</div>
    </div>`).join('') + '</div>';
}}
function renderAlgorithms() {{
  const items = DATA.algorithms || [];
  if (!items.length) return '<div class="card muted">No algorithm ledger yet.</div>';
  return '<div class="stack">' + items.map(item => `
    <div class="card">
      <div class="row">
        <b>${{esc(item.label || item.id || 'algorithm')}}</b>
        <span class="pill ${{item.status === 'blocked' ? 'bad' : (item.status === 'warn' ? 'warn' : 'good')}}">${{esc(item.status || 'done')}}</span>
      </div>
      <div class="kv">
        <div>Duration</div><div>${{esc(item.duration_ms ?? 'n/a')}} ms</div>
        <div>Inputs</div><div>${{json(item.inputs || {{}})}}</div>
        <div>Thresholds</div><div>${{json(item.thresholds || {{}})}}</div>
        <div>Issue count</div><div>${{esc(item.issue_count ?? 0)}}</div>
        <div>Evidence</div><div>${{json(item.evidence_refs || [])}}</div>
      </div>
    </div>`).join('') + '</div>';
}}
function renderIntent() {{
  const manifest = DATA.intent || {{}};
  if (!Object.keys(manifest).length) return '<div class="card muted">No manifest available.</div>';
  const objects = (manifest.objects || []).map(obj => pill((obj.role || 'unknown') + ': ' + (obj.name || 'object'), obj.source === 'manifest' ? 'good' : 'warn')).join('');
  return `
    <div class="grid">
      <div class="card">
        <h2>Manifest</h2>
        <div class="kv">
          <div>Asset</div><div>${{esc(manifest.asset_name || '')}}</div>
          <div>Schema</div><div>${{esc(manifest.schema_version || '')}}</div>
          <div>Source</div><div>${{esc(manifest.source || '')}}</div>
          <div>Repair policy</div><div>${{json(manifest.repair_policy || {{}})}}</div>
        </div>
      </div>
      <div class="card">
        <h2>Objects</h2>
        <div class="row">${{objects || '<span class="muted">No object annotations.</span>'}}</div>
      </div>
    </div>
    <div class="card" style="margin-top:12px;"><h2>Raw Manifest</h2>${{json(manifest)}}</div>
  `;
}}
function renderConstraints() {{
  const graph = DATA.constraints || {{}};
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  return `
    <div class="grid">
      <div class="card">
        <h2>Nodes</h2>
        <div class="row">${{nodes.length ? nodes.map(node => pill(node.label || node.id || 'node', 'good')).join('') : '<span class="muted">No nodes.</span>'}}</div>
      </div>
      <div class="card">
        <h2>Edges</h2>
        <div class="row">${{edges.length ? edges.map(edge => pill((edge.relation || 'relation') + ': ' + (edge.source || '') + ' -> ' + (edge.target || ''), edge.constraint_source === 'manifest' ? 'good' : 'warn')).join('') : '<span class="muted">No edges.</span>'}}</div>
      </div>
    </div>
    <div class="card" style="margin-top:12px;"><h2>Constraint Graph</h2>${{json(graph)}}</div>
  `;
}}
function renderIssues() {{
  const validation = DATA.issues || {{}};
  const items = (validation.issues || validation.top_issues || []);
  if (!items.length) return '<div class="card ok">No validation issues reported.</div>';
  return '<div class="stack">' + items.map(item => `
    <div class="card">
      <div class="row">
        <b class="${{issueClass(item.severity)}}">${{esc(item.severity || 'low')}} / ${{esc(item.type || 'issue')}}</b>
        ${{pill(item.source || 'geometry')}}
      </div>
      <div><b>${{esc(item.target || (item.objects || []).join(', ') || 'scene')}}</b></div>
      <div class="muted">${{esc(item.suggested_fix || item.remediation_hint || '')}}</div>
      <div class="muted">${{esc((item.acceptance_tests || []).join(' | '))}}</div>
      <div>${{json(item.evidence || {{}})}}</div>
    </div>`).join('') + '</div>';
}}
function renderRepair() {{
  const plan = DATA.repair || {{}};
  const safe = plan.safe_actions || [];
  const blocked = plan.blocked_operations || [];
  return `
    <div class="grid">
      <div class="card">
        <h2>Plan</h2>
        <div class="kv">
          <div>Status</div><div>${{esc(plan.status || 'idle')}}</div>
          <div>Score</div><div>${{esc(plan.validation_score ?? 0)}}</div>
          <div>Issues</div><div>${{esc(plan.top_issue_count ?? 0)}}</div>
          <div>Policy</div><div>${{json(plan.policy || {{}})}}</div>
        </div>
      </div>
      <div class="card">
        <h2>Safe Actions</h2>
        ${{safe.length ? safe.map(item => `<div class="card" style="margin-bottom:8px;"><b>${{esc(item.issue_type || '')}}</b><div class="muted">${{esc(item.action?.op || '')}}: ${{esc(item.action?.reason || '')}}</div><div class="muted">${{esc((item.acceptance_tests || []).join(' | '))}}</div></div>`).join('') : '<span class="muted">No safe actions proposed.</span>'}}
      </div>
      <div class="card">
        <h2>Blocked Ops</h2>
        ${{blocked.length ? blocked.map(item => `<div class="card" style="margin-bottom:8px;"><b class="warn">${{esc(item.operation || '')}}</b><div class="muted">${{esc(item.reason || '')}}</div></div>`).join('') : '<span class="muted">No blocked operations listed.</span>'}}
      </div>
    </div>
    <div class="card" style="margin-top:12px;"><h2>Raw Repair Plan</h2>${{json(plan)}}</div>
  `;
}}
function renderCritic() {{
  const critic = DATA.critic || {{}};
  const issues = critic.issues || [];
  return `
    <div class="grid">
      <div class="card">
        <h2>Critic</h2>
        <div class="kv">
          <div>Score</div><div>${{esc(critic.pairwise_vs_best?.confidence ?? critic.critic_score ?? critic.score ?? 0)}}</div>
          <div>Pairwise</div><div>${{json(critic.pairwise_vs_best || {{}})}}</div>
          <div>Summary</div><div>${{esc(critic.summary || '')}}</div>
          <div>Next prompt</div><div>${{esc(critic.next_prompt || '')}}</div>
          <div>View notes</div><div>${{json(critic.viewpoint_notes || [])}}</div>
          <div>Delta prompt</div><div>${{json(critic.delta_prompt || {{}})}}</div>
        </div>
      </div>
      <div class="card">
        <h2>Issue Signature</h2>
        <div class="row">${{(critic.issue_signature || []).length ? critic.issue_signature.map(item => pill(item)).join('') : '<span class="muted">No issue signature.</span>'}}</div>
      </div>
    </div>
    <div class="card" style="margin-top:12px;"><h2>Issues</h2>${{issues.length ? issues.map(item => `<div class="card" style="margin-bottom:8px;"><b>${{esc(item.severity || 'low')}} / ${{esc(item.category || item.type || '')}}</b><div>${{esc(item.evidence || '')}}</div><div class="muted">${{esc(item.suggested_safe_fix || item.suggested_fix || '')}}</div></div>`).join('') : '<span class="muted">No critic issues.</span>'}}</div>
    <div class="card" style="margin-top:12px;"><h2>Prompt</h2>${{json(critic.prompt || '')}}</div>
    <div class="card" style="margin-top:12px;"><h2>Raw Critic JSON</h2>${{json(critic.raw || critic)}}</div>
  `;
}}
function renderTimeline() {{
  const rows = DATA.timeline || [];
  if (!rows.length) return '<div class="card muted">No timeline entries yet.</div>';
  return '<div class="stack">' + rows.map(row => `
    <div class="card">
      <div class="row">
        <b>${{esc(row.phase_label || row.phase || 'event')}}</b>
        <span class="pill">${{esc(row.status || '')}}</span>
        <span class="pill">${{esc(row.iteration ?? row.pass ?? '')}}</span>
      </div>
      <div class="muted">${{esc(row.summary || '')}}</div>
      <div class="muted">${{esc(row.started_at || row.ended_at || '')}}</div>
    </div>`).join('') + '</div>';
}}
function renderRuns() {{
  const runs = DATA.runs || {{}};
  const recent = runs.recent || [];
  const active = runs.active || {{}};
  return `
    <div class="grid">
      <div class="card">
        <h2>Active Run</h2>
        <div class="kv">
          <div>Run ID</div><div>${{esc(runs.active_run_id || active.run_id || 'none')}}</div>
          <div>Phase</div><div>${{esc(active.phase_label || active.phase || '')}}</div>
          <div>Score</div><div>${{esc(active.current_score ?? active.score ?? 0)}}</div>
          <div>Stop reason</div><div>${{esc(active.stop_reason || '')}}</div>
        </div>
      </div>
      <div class="card">
        <h2>Recent Runs</h2>
        <div class="stack">${{recent.length ? recent.map(item => `<div class="card"><div class="row"><b>${{esc(item.run_id || '')}}</b><span class="pill">${{esc(item.phase || item.status || '')}}</span><span class="pill">${{esc(item.current_score ?? item.score ?? 0)}}</span></div><div class="muted">${{esc(item.stop_reason || '')}}</div></div>`).join('') : '<span class="muted">No recent runs.</span>'}}</div>
      </div>
    </div>
    <div class="card" style="margin-top:12px;"><h2>Run Index</h2>${{json(runs)}}</div>
  `;
}}
function renderRaw() {{
  return '<div class="card"><h2>Raw Advanced JSON</h2>' + json(DATA.raw || DATA.status || DATA) + '</div>';
}}
function renderPanel() {{
  let html = '';
  if (ACTIVE_TAB === 'overview') html = renderOverview();
  else if (ACTIVE_TAB === 'screenshots') html = renderScreenshots();
  else if (ACTIVE_TAB === 'algorithms') html = renderAlgorithms();
  else if (ACTIVE_TAB === 'intent') html = renderIntent();
  else if (ACTIVE_TAB === 'constraints') html = renderConstraints();
  else if (ACTIVE_TAB === 'issues') html = renderIssues();
  else if (ACTIVE_TAB === 'repair') html = renderRepair();
  else if (ACTIVE_TAB === 'critic') html = renderCritic();
  else if (ACTIVE_TAB === 'timeline') html = renderTimeline();
  else if (ACTIVE_TAB === 'runs') html = renderRuns();
  else html = renderRaw();
  document.getElementById('content').innerHTML = html;
}}
async function load() {{
  const keys = Object.keys(SECTION_ENDPOINTS);
  const responses = await Promise.all(keys.map(async key => {{
    try {{
      return [key, await api(SECTION_ENDPOINTS[key])];
    }} catch (error) {{
      return [key, {{error: String(error)}}];
    }}
  }}));
  DATA = Object.fromEntries(responses.map(([key, value]) => {{
    if (key === 'live') return [key, value];
    if (key === 'overview') return [key, value];
    if (!value || typeof value !== 'object') return [key, value];
    if (key === 'screenshots') return [key, value.screenshots || []];
    if (key === 'algorithms') return [key, value.algorithms || []];
    if (key === 'intent') return [key, value.intent_manifest || value.manifest || value];
    if (key === 'constraints') return [key, value.constraints || value.graph || value];
    if (key === 'issues') return [key, value.validation || value];
    if (key === 'repair') return [key, value.repair_plan || value];
    if (key === 'critic') return [key, value.critic || value];
    if (key === 'logs') return [key, value.logs || []];
    if (key === 'timeline') return [key, value.timeline || []];
    if (key === 'runs') return [key, value.runs || value];
    if (key === 'raw') return [key, value.raw || value];
    return [key, value];
  }}));
  const state = DATA.live || DATA.overview || {{}};
  const liveError = DATA.live && (DATA.live.error || (DATA.live.backend_error || {{}}).summary) ? String(DATA.live.error || (DATA.live.backend_error || {{}}).summary) : '';
  const auto = state.automation || {{}};
  const validation = state.validation || {{}};
  const service = state.service || {{}};
  const banner = service.stream_recovering ? 'RECONNECTING' : (auto.active ? 'ACTIVE' : (auto.phase_label || 'READY'));
  const phase = document.getElementById('phase');
  phase.textContent = liveError ? 'NEEDS ATTENTION' : banner;
  phase.className = 'banner' + (liveError ? ' warn' : (banner === 'RECONNECTING' ? ' reconnecting' : (auto.active ? '' : ' warn')));
  document.getElementById('summary').textContent = liveError ? 'Live state fetch failed. The console is still running; refresh or restart the web console if this persists.' : (auto.activity || validation.validation_summary || service.status || '');
  document.getElementById('subsummary').textContent = liveError ? liveError : ('Sequence ' + esc(state.sequence ?? 0) + ' | Validation score ' + esc(validation.asset_score ?? 0) + ' | issues ' + esc(validation.issue_count ?? 0) + ' | web console ' + esc((state.web_console || {{}}).running ? 'running' : 'stopped'));
  document.getElementById('navFacts').innerHTML =
    '<p>Version: ' + esc(state.version || '') + '</p>' +
    '<p>Module: ' + esc(state.module_file || '') + '</p>' +
    '<p>Service: ' + esc(service.status || '') + '</p>' +
    '<p>Run: ' + esc(auto.run_id || 'none') + '</p>' +
    '<p>Sequence: ' + esc(state.sequence ?? 0) + '</p>' +
    '<p>Web console: ' + esc((state.web_console || {{}}).url || 'n/a') + '</p>';
  document.getElementById('navLinks').innerHTML = SECTIONS.map(([id, label]) => '<a href="#' + id + '">' + esc(label) + '</a>').join('');
  document.getElementById('content').innerHTML = renderLivePage();
}}
load().catch(error => {{
  const phase = document.getElementById('phase');
  phase.textContent = 'NEEDS ATTENTION';
  phase.className = 'banner warn';
  document.getElementById('summary').textContent = 'The web console script could not load live state.';
  document.getElementById('subsummary').textContent = String(error);
}});
setInterval(load, 750);
</script>
</body>
</html>"""
