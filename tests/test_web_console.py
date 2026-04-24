from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from http.client import HTTPConnection
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codex_blender_agent.web_console import WebConsoleServer, _html_shell


def _http_request(
    url: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    parsed = url.split("://", 1)[1]
    host_port = parsed.partition("/")[0]
    host, port_text = host_port.split(":", 1)
    connection = HTTPConnection(host, int(port_text), timeout=2)
    try:
        connection.request(method, "/" + path.lstrip("/"), body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, {key: value for key, value in response.getheaders()}, response.read()
    finally:
        connection.close()


def _request_json(
    url: str,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], dict[str, Any]]:
    status, response_headers, body = _http_request(url, path, method=method, headers=headers)
    return status, response_headers, json.loads(body.decode("utf-8"))


def _request_text(url: str, path: str) -> tuple[int, dict[str, str], str]:
    status, response_headers, body = _http_request(url, path)
    return status, response_headers, body.decode("utf-8")


def _request_bytes(url: str, path: str) -> tuple[int, dict[str, str], bytes]:
    return _http_request(url, path)


def _wait_for_ready(url: str, token: str, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    request_path = f"/api/status?token={quote(token)}"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, _, payload = _request_json(url, request_path)
        except Exception as exc:  # pragma: no cover - race protection
            last_error = exc
            time.sleep(0.05)
            continue
        if status == 200 and payload.get("web_console", {}).get("running"):
            return
        time.sleep(0.05)
    raise AssertionError(f"web console did not become ready: {last_error!r}")


def _script_from_html(html: str) -> str:
    start = html.index("<script>") + len("<script>")
    end = html.index("</script>", start)
    return html[start:end]


def test_rendered_web_console_javascript_is_syntax_valid(tmp_path: Path) -> None:
    script = _script_from_html(_html_shell("syntax-token"))
    assert "validation.issue_count ?? (validation.issues || []).length || 0" not in script
    assert "validation.issue_count ?? ((validation.issues || []).length || 0)" in script
    node = shutil.which("node")
    if node:
        script_path = tmp_path / "web_console.js"
        script_path.write_text(script, encoding="utf-8")
        completed = subprocess.run(
            [node, "--check", str(script_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout


def test_web_console_lifecycle_and_status_roundtrip(tmp_path: Path) -> None:
    state = {
        "version": "0.15.0",
        "service": {"status": "ready"},
        "allowed_screenshot_roots": [str(tmp_path / "shots")],
    }
    server = WebConsoleServer(state_provider=lambda: dict(state), host="127.0.0.1", port=0, token="test-token")

    try:
        started = server.start()

        assert started.running is True
        assert started.host == "127.0.0.1"
        assert started.port > 0
        assert started.url.endswith("token=test-token")
        assert server.running is True
        assert server.status().as_public_dict()["running"] is True

        _wait_for_ready(started.url, started.token)
        status_code, _, payload = _request_json(started.url, f"api/status?token={quote(started.token)}")
        live_status, _, live_payload = _request_json(started.url, f"api/live?token={quote(started.token)}")
        second_live_status, _, second_live_payload = _request_json(started.url, f"api/live?token={quote(started.token)}")

        assert status_code == 200
        assert payload["version"] == "0.15.0"
        assert payload["service"]["status"] == "ready"
        assert payload["web_console"]["running"] is True
        assert payload["web_console"]["url"] == started.url
        assert "token" not in payload["web_console"]
        assert live_status == 200
        assert live_payload["sequence"] >= 1
        assert second_live_status == 200
        assert second_live_payload["sequence"] > live_payload["sequence"]
    finally:
        stopped = server.stop()
        assert stopped.running is False
        assert stopped.url == ""


def test_web_console_live_endpoint_can_use_compact_provider() -> None:
    full_state = {
        "version": "0.15.0",
        "service": {"status": "full"},
        "screenshots": [{"path": "heavy.png"}],
        "raw_heavy": {"large": True},
    }
    live_state = {
        "version": "0.15.0",
        "service": {"status": "live"},
        "sequence": 44,
        "active_tool_events": [{"tool_name": "validate_gpt_asset", "status": "running"}],
        "tool_events": [{"tool_name": "validate_gpt_asset", "status": "running"}],
        "addon_health": {"ok": True},
    }
    server = WebConsoleServer(
        state_provider=lambda: dict(full_state),
        live_state_provider=lambda: dict(live_state),
        host="127.0.0.1",
        port=0,
        token="compact-token",
    )

    try:
        started = server.start()
        _wait_for_ready(started.url, started.token)

        status_code, _, status_payload = _request_json(started.url, f"api/status?token={quote(started.token)}")
        live_status, _, live_payload = _request_json(started.url, f"api/live?token={quote(started.token)}")

        assert status_code == 200
        assert status_payload["service"]["status"] == "full"
        assert status_payload["screenshots"][0]["path"] == "heavy.png"
        assert live_status == 200
        assert live_payload["service"]["status"] == "live"
        assert live_payload["sequence"] == 44
        assert live_payload["active_tool_events"][0]["tool_name"] == "validate_gpt_asset"
        assert "screenshots" not in live_payload
    finally:
        server.stop()


def test_web_console_rejects_missing_or_invalid_tokens() -> None:
    state = {"version": "0.15.0"}
    server = WebConsoleServer(state_provider=lambda: dict(state), host="127.0.0.1", port=0, token="secret-token")

    try:
        started = server.start()
        _wait_for_ready(started.url, started.token)

        status_code, _, body = _request_text(started.url, "api/status")
        assert status_code == 403
        assert "missing_or_invalid_token" in body

        status_code, _, body = _request_text(started.url, "api/status?token=wrong-token")
        assert status_code == 403
        assert "missing_or_invalid_token" in body

        status_code, _, body = _request_text(started.url, "")
        assert status_code == 403
        assert "Missing or invalid web console token." in body
    finally:
        server.stop()


def test_web_console_basic_api_and_control_handler() -> None:
    actions: list[str] = []

    def control_handler(action: str) -> dict[str, Any]:
        actions.append(action)
        return {"ok": True, "handled": action}

    state = {
        "version": "0.15.0",
        "checks": [{"label": "geometry", "status": "done", "count": 1}],
        "algorithms": [{"id": "collect_geometry", "label": "Collect geometry", "status": "done"}],
        "intent_manifest": {"schema_version": "0.15.0", "objects": [{"name": "Castle"}]},
        "constraints": {"nodes": [{"id": "Castle"}], "edges": []},
        "repair_plan": {"counts": {"safe": 1, "gated": 0}},
        "overlays": {"visible": True},
        "logs": [{"label": "WEB CONSOLE STARTED", "summary": "Console is live."}],
        "startup_trace": [{"label": "WEB CONSOLE STARTED", "summary": "Console is live."}],
        "capabilities": [{"id": "image_generation", "label": "Generate images"}],
        "tool_events": [{"actor": "tool", "label": "Tool completed: list_studio_context", "status": "completed"}],
        "runs": {"active_run_id": "run-1", "active": {"run_id": "run-1"}, "recent": [{"run_id": "run-1"}], "index": {"run-1": {"run_id": "run-1"}}},
    }
    server = WebConsoleServer(
        state_provider=lambda: dict(state),
        control_handler=control_handler,
        host="127.0.0.1",
        port=0,
        token="control-token",
    )

    try:
        started = server.start()
        _wait_for_ready(started.url, started.token)

        direct = server.execute_control("refresh-state")
        assert direct == {"ok": True, "handled": "refresh_state"}
        assert actions == ["refresh_state"]

        unsupported = server.execute_control("not-supported")
        assert unsupported["ok"] is False
        assert "Unsupported web console action" in unsupported["error"]

        status_code, _, payload = _request_json(started.url, f"api/control/refresh_state?token={quote(started.token)}", method="POST")
        assert status_code == 200
        assert payload == {"handled": "refresh_state", "ok": True}
        assert actions == ["refresh_state", "refresh_state"]

        status_code, _, payload = _request_json(started.url, f"api/raw?token={quote(started.token)}")
        assert status_code == 200
        assert payload["raw"]["version"] == "0.15.0"
        assert payload["raw"]["checks"][0]["label"] == "geometry"

        status_code, _, payload = _request_json(started.url, f"api/live?token={quote(started.token)}")
        assert status_code == 200
        assert payload["sequence"] >= 1

        for endpoint, key in [
            ("api/algorithms", "algorithms"),
            ("api/intent-manifest", "intent_manifest"),
            ("api/constraints", "constraints"),
            ("api/repair-plan", "repair_plan"),
            ("api/overlays", "overlays"),
            ("api/logs", "logs"),
            ("api/capabilities", "capabilities"),
            ("api/runs", "runs"),
        ]:
            status_code, _, payload = _request_json(started.url, f"{endpoint}?token={quote(started.token)}")
            assert status_code == 200
            assert key in payload
        status_code, _, payload = _request_json(started.url, f"api/capabilities?token={quote(started.token)}")
        assert status_code == 200
        assert payload["tool_events"][0]["label"] == "Tool completed: list_studio_context"

        status_code, _, payload = _request_json(started.url, f"api/runs/run-1?token={quote(started.token)}")
        assert status_code == 200
        assert payload["run"]["run_id"] == "run-1"
    finally:
        server.stop()


def test_web_console_exposes_observability_sections_and_run_payloads() -> None:
    state = {
        "version": "0.15.0",
        "module_file": "codex_blender_agent/runtime.py",
        "service": {"status": "ready", "stream_recovering": False},
        "automation": {"phase_label": "VERIFYING GEOMETRY", "run_id": "run-1", "score": 0.91, "activity": "Analyzing castle geometry."},
        "sequence": 7,
        "prompt_events": [
            {"kind": "typed", "actor": "user", "status": "done", "label": "Prompt entered", "timestamp": "2026-04-22T10:00:00Z", "summary": "make a castle"},
            {"kind": "expanded", "actor": "codex", "status": "done", "label": "Prompt expanded", "timestamp": "2026-04-22T10:00:01Z", "summary": "Expanded with geometry QA hints."},
            {"kind": "submitted", "actor": "user", "status": "done", "label": "Prompt submitted", "timestamp": "2026-04-22T10:00:02Z", "summary": "Sent to Codex."},
        ],
        "automation_events": [
            {"event_id": "event-1", "actor": "codex", "phase": "creator_prompt", "status": "running", "label": "CREATING", "timestamp": "2026-04-22T10:00:03Z", "summary": "Creator prompt sent."},
            {"event_id": "event-2", "actor": "validator", "phase": "geometry", "status": "done", "label": "VERIFYING GEOMETRY", "timestamp": "2026-04-22T10:00:04Z", "summary": "Evaluated geometry checks completed."},
            {"event_id": "event-3", "actor": "tool", "phase": "tool_running", "status": "running", "label": "Tool running: validate_gpt_asset", "timestamp": "2026-04-22T10:00:05Z", "summary": "selected_only=True"},
        ],
        "tool_events": [{"event_id": "event-3", "actor": "tool", "status": "running", "label": "Tool running: validate_gpt_asset", "summary": "selected_only=True"}],
        "capabilities": [{"id": "image_generation", "label": "Generate images", "status": "handoff_ready", "tool_names": ["create_image_generation_brief"]}],
        "logs": [
            {"event_id": "log-1", "type": "web_console", "label": "WEB CONSOLE STARTED", "status": "completed", "created_at": "2026-04-22T10:00:00Z", "summary": "http://127.0.0.1:9999"},
            {"event_id": "log-2", "type": "automation", "label": "SERVICE STARTING", "status": "running", "created_at": "2026-04-22T10:00:02Z", "summary": "Starting app-server."},
        ],
        "startup_trace": [
            {"event_id": "log-1", "type": "web_console", "label": "WEB CONSOLE STARTED", "status": "completed", "created_at": "2026-04-22T10:00:00Z", "summary": "http://127.0.0.1:9999"},
            {"event_id": "log-2", "type": "automation", "label": "SERVICE STARTING", "status": "running", "created_at": "2026-04-22T10:00:02Z", "summary": "Starting app-server."},
        ],
        "backend_error": {},
        "validation": {
            "report_id": "report-1",
            "asset_score": 86.0,
            "issue_count": 2,
            "critical_count": 0,
            "validation_summary": "castle validation summary",
            "top_issues": [{"type": "interpenetration", "severity": "high", "source": "geometry"}],
            "issues": [{"type": "interpenetration", "severity": "high", "source": "geometry", "objects": ["tower", "wall"]}],
        },
        "scene_snapshot": {
            "scene_name": "Castle Scene",
            "object_count": 18,
            "selected_count": 2,
            "materials": [{"name": "stone"}, {"name": "wood"}],
            "objects": [{"name": "keep", "type": "MESH"}, {"name": "tower", "type": "MESH"}, {"name": "camera", "type": "CAMERA"}],
            "changes": ["added tower", "aligned wall loop"],
            "validation_score": 86.0,
            "summary": "Castle blockout with towers, keep, moat, and bridge.",
        },
        "algorithms": [
            {
                "id": "evaluated_geometry",
                "label": "Evaluated geometry snapshot",
                "status": "done",
                "duration_ms": 12,
                "inputs": {"selected_only": True},
                "thresholds": {"minimum_coverage_score": 0.65},
                "issue_count": 1,
                "evidence_refs": ["report-1"],
            }
        ],
        "intent_manifest": {
            "asset_name": "castle",
            "schema_version": "0.15.0",
            "source": "scene",
            "objects": [{"name": "keep", "role": "structure"}],
        },
        "constraints": {
            "nodes": [{"id": "keep", "label": "keep"}],
            "edges": [{"source": "keep", "target": "wall", "relation": "supported_by"}],
        },
        "repair_plan": {
            "status": "ready",
            "validation_score": 0.86,
            "top_issue_count": 2,
            "safe_actions": [{"issue_type": "floating_part", "action": {"op": "snap_to_support", "reason": "reduce gap"}, "acceptance_tests": ["gap <= 0.003"]}],
            "blocked_operations": [{"operation": "boolean_apply", "reason": "policy gated"}],
        },
        "overlays": {
            "issue_markers": [{"type": "interpenetration", "objects": ["tower", "wall"]}],
            "support_footprints": [{"target": "keep"}],
        },
        "screenshots": [
            {
                "index": 1,
                "path": str((Path(__file__).parent / "fixtures" / "shot-1.png").resolve()),
                "view_id": "view-1",
                "label": "front",
                "kind": "optimization",
                "method": "pca",
                "score": 0.78,
                "score_components": {"coverage": 0.8},
                "notes": "front review",
                "viewpoint": {"direction": [0, 0, 1]},
                "pass_index": 1,
                "pass_id": "pass-1",
                "phase": "capturing",
                "source": "pass",
            }
        ],
        "runs": {
            "active_run_id": "run-1",
            "active": {"run_id": "run-1", "phase_label": "VERIFYING GEOMETRY", "current_score": 0.91},
            "recent": [{"run_id": "run-1", "phase": "capturing", "current_score": 0.91}],
            "index": {"run-1": {"run_id": "run-1", "phase": "capturing", "current_score": 0.91}},
        },
        "critic": {
            "prompt": "Critic prompt text",
            "summary": "Focus on tower-wall intersections first.",
            "next_prompt": "Trim tower crown before polish.",
            "issues": [{"severity": "high", "category": "geometry", "evidence": "tower intersects wall", "suggested_fix": "move tower crown up"}],
            "issue_signature": ["interpenetration:tower-wall"],
            "viewpoint_notes": ["Need a closer top view of battlements."],
            "delta_prompt": {"preserve": ["keep"], "forbid": ["rewrite the whole castle"]},
        },
        "timeline": [{"phase": "creating", "status": "done", "summary": "Creator pass complete"}],
        "visual_review": {
            "active_run": {"run_id": "run-1"},
            "recent_runs": [{"run_id": "run-1"}],
            "runs": {"active_run_id": "run-1"},
        },
    }
    server = WebConsoleServer(state_provider=lambda: dict(state), host="127.0.0.1", port=0, token="obs-token")

    try:
        started = server.start()
        _wait_for_ready(started.url, started.token)

        status_code, _, html_body = _request_text(started.url, f"?token={quote(started.token)}")
        assert status_code == 200
        assert "Live Review Console" in html_body
        for section_id in [
            'live-status',
            'prompt-timeline',
            'action-feed',
            'console-log',
            'scene-now',
            'geometry-checks',
            'screenshots',
            'issues',
            'critic',
            'raw-json',
        ]:
            assert f'id="{section_id}"' in html_body
        assert "Validate now" in html_body
        assert "Apply safe repair" in html_body
        assert "live: '/api/live'" in html_body
        assert "capabilities: '/api/capabilities'" in html_body
        assert "Capabilities" in html_body
        assert "setInterval(() => load(false), LIVE_REFRESH_MS)" in html_body
        assert "Promise.all(keys.map" not in html_body
        assert "TAB_ENDPOINT_KEYS" in html_body
        assert "setToolEventFilter" in html_body
        assert "<details open>" not in html_body

        live_status, _, live_payload = _request_json(started.url, f"api/live?token={quote(started.token)}")
        algorithms_status, _, algorithms_payload = _request_json(started.url, f"api/algorithms?token={quote(started.token)}")
        intent_status, _, intent_payload = _request_json(started.url, f"api/intent-manifest?token={quote(started.token)}")
        constraints_status, _, constraints_payload = _request_json(started.url, f"api/constraints?token={quote(started.token)}")
        repair_status, _, repair_payload = _request_json(started.url, f"api/repair-plan?token={quote(started.token)}")
        overlays_status, _, overlays_payload = _request_json(started.url, f"api/overlays?token={quote(started.token)}")
        logs_status, _, logs_payload = _request_json(started.url, f"api/logs?token={quote(started.token)}")
        screenshots_status, _, screenshots_payload = _request_json(started.url, f"api/screenshots?token={quote(started.token)}")
        runs_status, _, runs_payload = _request_json(started.url, f"api/runs?token={quote(started.token)}")
        run_status, _, run_payload = _request_json(started.url, f"api/runs/run-1?token={quote(started.token)}")
        critic_status, _, critic_payload = _request_json(started.url, f"api/critic?token={quote(started.token)}")
        capabilities_status, _, capabilities_payload = _request_json(started.url, f"api/capabilities?token={quote(started.token)}")

        assert live_status == 200
        assert live_payload["sequence"] == 7
        assert live_payload["scene_snapshot"]["scene_name"] == "Castle Scene"
        assert live_payload["prompt_events"][0]["label"] == "Prompt entered"
        assert live_payload["automation_events"][0]["label"] == "CREATING"
        assert algorithms_status == 200
        assert algorithms_payload["algorithms"][0]["id"] == "evaluated_geometry"
        assert intent_status == 200
        assert intent_payload["intent_manifest"]["asset_name"] == "castle"
        assert constraints_status == 200
        assert constraints_payload["constraints"]["nodes"][0]["id"] == "keep"
        assert repair_status == 200
        assert repair_payload["repair_plan"]["safe_actions"][0]["action"]["op"] == "snap_to_support"
        assert overlays_status == 200
        assert overlays_payload["overlays"]["issue_markers"][0]["type"] == "interpenetration"
        assert logs_status == 200
        assert logs_payload["logs"][0]["label"] == "WEB CONSOLE STARTED"
        assert logs_payload["startup_trace"][1]["label"] == "SERVICE STARTING"
        assert screenshots_status == 200
        assert screenshots_payload["screenshots"][0]["view_id"] == "view-1"
        assert runs_status == 200
        assert runs_payload["runs"]["active_run_id"] == "run-1"
        assert run_status == 200
        assert run_payload["run"]["run_id"] == "run-1"
        assert critic_status == 200
        assert critic_payload["critic"]["summary"] == "Focus on tower-wall intersections first."
        assert capabilities_status == 200
        assert capabilities_payload["capabilities"][0]["id"] == "image_generation"
        assert capabilities_payload["tool_events"][0]["label"] == "Tool running: validate_gpt_asset"
    finally:
        server.stop()


def test_web_console_live_state_survives_provider_failure() -> None:
    def failing_provider() -> dict[str, Any]:
        raise RuntimeError("payload builder exploded")

    server = WebConsoleServer(state_provider=failing_provider, host="127.0.0.1", port=0, token="fail-token")

    try:
        started = server.start()
        _wait_for_ready(started.url, started.token)

        status_code, _, payload = _request_json(started.url, f"api/live?token={quote(started.token)}")
        assert status_code == 200
        assert payload["error"] == "payload builder exploded"
        assert payload["web_console"]["running"] is True
        assert payload["sequence"] >= 1
    finally:
        server.stop()


def test_web_console_control_accepts_safe_action_names() -> None:
    actions: list[str] = []

    def control_handler(action: str) -> dict[str, Any]:
        actions.append(action)
        return {"ok": True, "action": action}

    server = WebConsoleServer(state_provider=lambda: {}, control_handler=control_handler, host="127.0.0.1", port=0, token="safe-token")

    try:
        started = server.start()
        _wait_for_ready(started.url, started.token)

        response = server.execute_control("validate-now")
        assert response == {"ok": True, "action": "validate_now"}
        assert actions == ["validate_now"]

        response = server.execute_control("show_overlays")
        assert response == {"ok": True, "action": "show_overlays"}
        assert actions == ["validate_now", "show_overlays"]

        unsupported = WebConsoleServer(state_provider=lambda: {}, host="127.0.0.1", port=0, token="no-handler").execute_control("apply_safe_repair")
        assert unsupported["ok"] is False
        assert "Unsupported web console action" in unsupported["error"]
    finally:
        server.stop()


def test_web_console_screenshot_path_guard_allows_only_configured_roots(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    blocked_root = tmp_path / "blocked"
    allowed_root.mkdir()
    blocked_root.mkdir()

    allowed_file = allowed_root / "shot.png"
    allowed_file.write_bytes(b"\x89PNG\r\n\x1a\nallowed")
    blocked_file = blocked_root / "shot.png"
    blocked_file.write_bytes(b"\x89PNG\r\n\x1a\nblocked")

    state = {"allowed_screenshot_roots": [str(allowed_root)]}
    server = WebConsoleServer(state_provider=lambda: dict(state), host="127.0.0.1", port=0, token="shot-token")

    try:
        started = server.start()
        _wait_for_ready(started.url, started.token)

        status_code, _, payload = _request_json(
            started.url,
            f"api/screenshot?token={quote(started.token)}&path={quote(str(blocked_file))}",
        )
        assert status_code == 403
        assert payload == {"error": "path_not_allowed", "ok": False}

        status_code, response_headers, data = _request_bytes(
            started.url,
            f"api/screenshot?token={quote(started.token)}&path={quote(str(allowed_file))}",
        )
        assert status_code == 200
        assert data == allowed_file.read_bytes()
        assert response_headers["Content-Type"] == "image/png"
        assert response_headers["Cache-Control"] == "no-store"
    finally:
        server.stop()
