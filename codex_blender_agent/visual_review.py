from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .visual_geometry import (
    DEFAULT_CRITIC_SCORE_WEIGHT,
    DEFAULT_GEOMETRY_SCORE_WEIGHT,
    delta_prompt_to_text,
    detect_plateau as geometry_detect_plateau,
    hard_gates,
    hybrid_score,
    sanitize_delta_prompt,
)


DEFAULT_MAX_ITERATIONS = 5
DEFAULT_TARGET_SCORE = 0.85
DEFAULT_SCREENSHOT_RESOLUTION = 1024
DEFAULT_CAPTURE_MODE = "viewport"
PLATEAU_EPSILON = 0.03

PHASE_IDLE = "idle"
PHASE_CREATOR_RUNNING = "creator_running"
PHASE_CAPTURING = "capturing"
PHASE_CRITIC_RUNNING = "critic_running"
PHASE_PLANNING_NEXT = "planning_next"
PHASE_COMPLETE = "complete"
PHASE_STOPPED = "stopped"
PHASE_FAILED = "failed"

MUTATION_BLOCKED_PHASES = {PHASE_CRITIC_RUNNING, PHASE_PLANNING_NEXT}

SEMANTIC_DETAIL_TERMS = (
    "gate",
    "wall",
    "tower",
    "keep",
    "bridge",
    "courtyard",
    "roof",
    "banner",
    "doorway",
    "door",
)


@dataclass(frozen=True)
class Bounds:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]

    @property
    def center(self) -> tuple[float, float, float]:
        return tuple((self.minimum[index] + self.maximum[index]) / 2.0 for index in range(3))

    @property
    def size(self) -> tuple[float, float, float]:
        return tuple(max(self.maximum[index] - self.minimum[index], 0.001) for index in range(3))

    @property
    def radius(self) -> float:
        return max(math.sqrt(sum(value * value for value in self.size)) / 2.0, 1.0)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_run_id() -> str:
    return f"visual-review-{uuid.uuid4().hex[:12]}"


def slugify(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in (value or "").strip())
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "visual-review"


def object_record_from_any(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return dict(obj)
    name = str(getattr(obj, "name", "") or "")
    location = _vector(getattr(obj, "location", (0.0, 0.0, 0.0)))
    dimensions = _vector(getattr(obj, "dimensions", (1.0, 1.0, 1.0)), default=(1.0, 1.0, 1.0))
    obj_type = str(getattr(obj, "type", "") or "")
    return {"name": name, "type": obj_type, "location": location, "dimensions": dimensions}


def bounds_from_objects(objects: Iterable[Any]) -> Bounds:
    records = [object_record_from_any(obj) for obj in objects]
    mins: list[tuple[float, float, float]] = []
    maxs: list[tuple[float, float, float]] = []
    for record in records:
        if record.get("bounds"):
            bound_values = [_vector(item) for item in record.get("bounds", [])]
            if bound_values:
                mins.append(tuple(min(point[index] for point in bound_values) for index in range(3)))
                maxs.append(tuple(max(point[index] for point in bound_values) for index in range(3)))
                continue
        location = _vector(record.get("location", (0.0, 0.0, 0.0)))
        dimensions = _vector(record.get("dimensions", (1.0, 1.0, 1.0)), default=(1.0, 1.0, 1.0))
        half = tuple(max(abs(value), 0.001) / 2.0 for value in dimensions)
        mins.append(tuple(location[index] - half[index] for index in range(3)))
        maxs.append(tuple(location[index] + half[index] for index in range(3)))
    if not mins:
        return Bounds((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
    return Bounds(
        tuple(min(point[index] for point in mins) for index in range(3)),
        tuple(max(point[index] for point in maxs) for index in range(3)),
    )


def plan_viewpoints(objects: Iterable[Any], *, max_detail_views: int = 4) -> list[dict[str, Any]]:
    records = [object_record_from_any(obj) for obj in objects]
    bounds = bounds_from_objects(records)
    center = bounds.center
    radius = bounds.radius
    base_specs = (
        ("front", "Front", (0.0, -1.0, 0.32)),
        ("back", "Back", (0.0, 1.0, 0.32)),
        ("left", "Left", (-1.0, 0.0, 0.28)),
        ("right", "Right", (1.0, 0.0, 0.28)),
        ("three_quarter", "Three-quarter", (1.0, -1.0, 0.45)),
        ("top", "Top", (0.0, 0.0, 1.0)),
    )
    viewpoints = [
        _viewpoint(view_id, label, "coverage", center, direction, radius, f"Coverage view: {label.lower()}.")
        for view_id, label, direction in base_specs
    ]
    for detail in _semantic_detail_records(records, max_detail_views):
        viewpoints.append(detail)
    return viewpoints


def build_critic_prompt(
    manifest: dict[str, Any],
    screenshots: list[str],
    scene_digest: str = "",
    geometry_payload: dict[str, Any] | None = None,
) -> str:
    iteration = int(manifest.get("current_iteration", 0))
    score_history = [round(float(item.get("score", 0.0)), 3) for item in manifest.get("passes", [])]
    geometry_payload = geometry_payload or {}
    metric_vector = geometry_payload.get("metric_vector") or geometry_payload.get("geometry_digest", {}).get("metric_vector") or {}
    defects = geometry_payload.get("defects") or geometry_payload.get("geometry_digest", {}).get("defects") or []
    hard_gate_payload = geometry_payload.get("hard_gates") or geometry_payload.get("geometry_digest", {}).get("hard_gates") or {}
    view_scores = geometry_payload.get("view_scores", [])
    validation_report = geometry_payload.get("asset_validation_report") if isinstance(geometry_payload.get("asset_validation_report"), dict) else {}
    best_score = max(score_history or [0.0])
    return (
        "You are the critic/planner phase of a Blender game-creation self-review loop.\n"
        "Do not mutate the scene in this phase. Inspect the screenshots, geometry metrics, and scene context, then decide whether another bounded creator patch is needed.\n"
        "Keep the original user goal immutable. Do not rewrite the whole task or expand scope.\n"
        "Validation-first defects outrank screenshot polish: critical geometry, contact, containment, support, or intersection problems must be fixed before composition or detail tweaks.\n\n"
        f"Original goal: {manifest.get('original_prompt', '')}\n"
        f"Current creator prompt: {manifest.get('current_prompt', '')}\n"
        f"Asset intent manifest: {json.dumps(manifest.get('asset_intent_manifest', {}), ensure_ascii=True, sort_keys=True)}\n"
        f"Iteration: {iteration} of {manifest.get('max_iterations', DEFAULT_MAX_ITERATIONS)}\n"
        f"Target score: {manifest.get('target_score', DEFAULT_TARGET_SCORE)}\n"
        f"Previous scores: {score_history}\n"
        f"Best score so far: {best_score}\n"
        f"Screenshots attached: {len(screenshots)}\n"
        f"Metric vector: {json.dumps(metric_vector, ensure_ascii=True, sort_keys=True)}\n"
        f"Hard gates: {json.dumps(hard_gate_payload, ensure_ascii=True, sort_keys=True)}\n"
        f"Defects: {json.dumps(defects[:12], ensure_ascii=True, sort_keys=True)}\n"
        f"Asset validation report: {json.dumps({'report_id': validation_report.get('report_id', ''), 'asset_score': validation_report.get('asset_score', 0), 'summary': validation_report.get('validation_summary', ''), 'top_issues': validation_report.get('top_issues', [])[:8]}, ensure_ascii=True, sort_keys=True)}\n"
        f"View scores: {json.dumps(view_scores[:12], ensure_ascii=True, sort_keys=True)}\n"
        f"Scene digest:\n{scene_digest.strip() or 'No scene digest available.'}\n\n"
        "Reply with concise JSON only using this shape:\n"
        "{\n"
        '  "critic_score": 0.0,\n'
        '  "pairwise_vs_best": {"label": "better | tie | worse", "confidence": 0.0},\n'
        '  "satisfied": false,\n'
        '  "issues": [{"id": "issue_01", "category": "geometry | coverage | camera | defect | material", "severity": "low | medium | high | critical", "evidence": "specific evidence", "target": "object or part", "suggested_safe_fix": "bounded fix"}],\n'
        '  "issue_signature": ["defect:type_target"],\n'
        '  "delta_prompt": {"mode": "patch", "owner_metric": "geometry", "targets": ["defect_id"], "preserve": ["object identity", "style", "materials unless targeted"], "forbid": ["delete", "external import", "global restyle"], "max_edits": 2, "edits": [{"target": "part", "op": "bounded edit"}], "acceptance_tests": ["metric or visual check"]},\n'
        '  "next_prompt": "optional plain-language patch prompt, or empty if done",\n'
        '  "summary": "what improved and what remains",\n'
        '  "viewpoint_notes": ["front view shows...", "top view shows..."]\n'
        "}\n"
    )


def parse_critique(text: str) -> dict[str, Any]:
    raw = text or ""
    data: dict[str, Any] = {}
    for candidate in _json_candidates(raw):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                data = parsed
                break
        except json.JSONDecodeError:
            continue
    critic_score = _clamp_float(data.get("critic_score", data.get("gpt_score", data.get("score", _score_from_text(raw)))), 0.0, 1.0)
    issues = data.get("issues", [])
    if isinstance(issues, str):
        issues = [issues]
    if not isinstance(issues, list):
        issues = []
    issue_signature = data.get("issue_signature", [])
    if isinstance(issue_signature, str):
        issue_signature = [issue_signature]
    if not isinstance(issue_signature, list):
        issue_signature = []
    viewpoint_notes = data.get("viewpoint_notes", [])
    if isinstance(viewpoint_notes, str):
        viewpoint_notes = [viewpoint_notes]
    if not isinstance(viewpoint_notes, list):
        viewpoint_notes = []
    pairwise = data.get("pairwise_vs_best", {})
    if not isinstance(pairwise, dict):
        pairwise = {}
    delta_prompt_raw = data.get("delta_prompt", {})
    delta_prompt = sanitize_delta_prompt(delta_prompt_raw, allow_destructive=False) if isinstance(delta_prompt_raw, dict) else None
    next_prompt = str(data.get("next_prompt", "") or "").strip()
    if not next_prompt and delta_prompt:
        next_prompt = delta_prompt_to_text(delta_prompt)
    summary = str(data.get("summary", "") or "").strip() or _plain_summary(raw)
    satisfied = bool(data.get("satisfied", False)) or critic_score >= DEFAULT_TARGET_SCORE
    return {
        "score": critic_score,
        "critic_score": critic_score,
        "pairwise_vs_best": {
            "label": str(pairwise.get("label", "tie") or "tie"),
            "confidence": _clamp_float(pairwise.get("confidence", 0.0), 0.0, 1.0),
        },
        "satisfied": satisfied,
        "issues": [_issue_payload(item) for item in issues if str(item).strip()],
        "issue_signature": [str(item) for item in issue_signature if str(item).strip()],
        "delta_prompt": delta_prompt,
        "next_prompt": next_prompt,
        "summary": summary,
        "viewpoint_notes": [str(item) for item in viewpoint_notes if str(item).strip()],
        "raw": raw,
    }


def should_stop(manifest: dict[str, Any]) -> tuple[bool, str]:
    if manifest.get("stop_requested"):
        return True, "user_stopped"
    if manifest.get("status") in {PHASE_FAILED, PHASE_STOPPED, PHASE_COMPLETE}:
        return True, str(manifest.get("stop_reason") or manifest.get("status"))
    passes = list(manifest.get("passes", []) or [])
    if not passes:
        return False, ""
    latest = passes[-1]
    target_score = float(manifest.get("target_score", DEFAULT_TARGET_SCORE))
    max_iterations = int(manifest.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    metric_vector = latest.get("metric_vector")
    defects = latest.get("defects", [])
    if isinstance(metric_vector, dict) and metric_vector:
        score = hybrid_score(
            metric_vector,
            critic_score=float(latest.get("critic_score", latest.get("score", 0.0)) or 0.0),
            geometry_weight=float(latest.get("geometry_score_weight", DEFAULT_GEOMETRY_SCORE_WEIGHT) or DEFAULT_GEOMETRY_SCORE_WEIGHT),
            critic_weight=float(latest.get("critic_score_weight", DEFAULT_CRITIC_SCORE_WEIGHT) or DEFAULT_CRITIC_SCORE_WEIGHT),
        )
        gates = hard_gates(metric_vector, defects if isinstance(defects, list) else [], target_score=target_score, hybrid=score["hybrid_score"])
        if gates.get("can_complete") and (bool(latest.get("satisfied", False)) or score["hybrid_score"] >= target_score):
            return True, "target_score_reached"
    elif bool(latest.get("satisfied")) or float(latest.get("score", 0.0)) >= target_score:
        return True, "target_score_reached"
    if int(manifest.get("current_iteration", len(passes))) >= max_iterations:
        return True, "max_iterations_reached"
    if len(passes) >= 3 and any(isinstance(item.get("metric_vector"), dict) for item in passes):
        if geometry_detect_plateau(passes):
            return True, "score_plateau"
    elif len(passes) >= 3:
        a = float(passes[-3].get("score", 0.0))
        b = float(passes[-2].get("score", 0.0))
        c = float(passes[-1].get("score", 0.0))
        if (b - a) < PLATEAU_EPSILON and (c - b) < PLATEAU_EPSILON:
            return True, "score_plateau"
    if latest.get("capture_failed") and manifest.get("capture_failed_once"):
        return True, "capture_failed"
    return False, ""


class VisualReviewStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def create_run(
        self,
        *,
        prompt: str,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        target_score: float = DEFAULT_TARGET_SCORE,
        resolution: int = DEFAULT_SCREENSHOT_RESOLUTION,
        capture_mode: str = DEFAULT_CAPTURE_MODE,
        thread_id: str = "",
        action_id: str = "",
    ) -> dict[str, Any]:
        run_id = make_run_id()
        run_dir = self.run_dir(run_id)
        manifest = {
            "run_id": run_id,
            "status": PHASE_CREATOR_RUNNING,
            "phase": PHASE_CREATOR_RUNNING,
            "original_prompt": prompt,
            "current_prompt": prompt,
            "max_iterations": max(1, int(max_iterations or DEFAULT_MAX_ITERATIONS)),
            "target_score": _clamp_float(target_score, 0.0, 1.0),
            "resolution": max(128, int(resolution or DEFAULT_SCREENSHOT_RESOLUTION)),
            "capture_mode": capture_mode or DEFAULT_CAPTURE_MODE,
            "current_iteration": 1,
            "passes": [],
            "thread_id": thread_id,
            "action_id": action_id,
            "stop_requested": False,
            "stop_reason": "",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "run_dir": str(run_dir),
        }
        self.save_run(manifest)
        return manifest

    def run_dir(self, run_id: str) -> Path:
        return self.root / slugify(run_id)

    def manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "manifest.json"

    def captures_dir(self, run_id: str, iteration: int) -> Path:
        return self.run_dir(run_id) / "captures" / f"pass_{max(int(iteration), 1):02d}"

    def save_run(self, manifest: dict[str, Any]) -> dict[str, Any]:
        run_id = str(manifest.get("run_id", "") or make_run_id())
        manifest["run_id"] = run_id
        manifest["updated_at"] = now_iso()
        path = self.manifest_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        return manifest

    def load_run(self, run_id: str) -> dict[str, Any]:
        path = self.manifest_path(run_id)
        if not path.exists():
            raise KeyError(f"Visual review run not found: {run_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "run_id": run_id,
                "status": PHASE_FAILED,
                "phase": PHASE_FAILED,
                "stop_reason": "manifest_corrupt",
                "error": str(exc),
                "manifest_path": str(path),
                "passes": [],
            }
        if not isinstance(data, dict):
            raise ValueError(f"Visual review manifest is not an object: {path}")
        return data

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        rows = []
        for path in self.root.glob("*/manifest.json"):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                rows.append({"run_id": path.parent.name, "status": PHASE_FAILED, "phase": PHASE_FAILED, "stop_reason": "manifest_corrupt", "passes": []})
        rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return rows[: max(limit, 1)]

    def append_pass(self, run_id: str, pass_data: dict[str, Any]) -> dict[str, Any]:
        manifest = self.load_run(run_id)
        passes = list(manifest.get("passes", []) or [])
        passes.append(dict(pass_data))
        manifest["passes"] = passes
        manifest["current_score"] = float(pass_data.get("score", 0.0))
        if pass_data.get("next_prompt"):
            manifest["current_prompt"] = str(pass_data.get("next_prompt"))
        stop, reason = should_stop(manifest)
        if pass_data.get("capture_failed"):
            manifest["capture_failed_once"] = True
        if stop:
            manifest["status"] = PHASE_COMPLETE if reason == "target_score_reached" else PHASE_STOPPED
            manifest["phase"] = manifest["status"]
            manifest["stop_reason"] = reason
        else:
            manifest["current_iteration"] = int(manifest.get("current_iteration", len(passes))) + 1
            manifest["status"] = PHASE_CREATOR_RUNNING
            manifest["phase"] = PHASE_CREATOR_RUNNING
        return self.save_run(manifest)

    def request_stop(self, run_id: str, reason: str = "user_stopped") -> dict[str, Any]:
        manifest = self.load_run(run_id)
        manifest["stop_requested"] = True
        manifest["stop_reason"] = reason
        manifest["status"] = PHASE_STOPPED
        manifest["phase"] = PHASE_STOPPED
        return self.save_run(manifest)


def _semantic_detail_records(records: list[dict[str, Any]], max_detail_views: int) -> list[dict[str, Any]]:
    details: list[tuple[int, dict[str, Any]]] = []
    scene_bounds = bounds_from_objects(records)
    radius = scene_bounds.radius
    for record in records:
        name = str(record.get("name", ""))
        lowered = name.lower()
        dimensions = _vector(record.get("dimensions", (1.0, 1.0, 1.0)), default=(1.0, 1.0, 1.0))
        score = 0
        matched = ""
        for term in SEMANTIC_DETAIL_TERMS:
            if term in lowered:
                score += 5
                matched = term
                break
        if dimensions[2] > max(dimensions[0], dimensions[1]) * 1.7:
            score += 3
            matched = matched or "vertical structure"
        if score <= 0:
            continue
        target = _vector(record.get("location", scene_bounds.center))
        local_radius = max(math.sqrt(sum(value * value for value in dimensions)) / 2.0, radius * 0.25, 0.75)
        view_id = f"detail_{slugify(matched)}_{slugify(name)[:18]}"
        detail = _viewpoint(
            view_id,
            f"Detail: {name}",
            "detail",
            target,
            (1.0, -1.0, 0.35),
            local_radius,
            f"Semantic detail view for {matched or name}.",
        )
        detail["object_name"] = name
        detail["semantic_term"] = matched
        details.append((score, detail))
    details.sort(key=lambda item: (-item[0], item[1].get("object_name", "")))
    return [item[1] for item in details[: max(max_detail_views, 0)]]


def _viewpoint(view_id: str, label: str, kind: str, target: tuple[float, float, float], direction: tuple[float, float, float], radius: float, notes: str) -> dict[str, Any]:
    direction = _normalize_direction(direction)
    distance = max(radius * (2.35 if kind == "coverage" else 1.65), 2.0)
    camera_location = tuple(target[index] + direction[index] * distance for index in range(3))
    return {
        "id": view_id,
        "label": label,
        "kind": kind,
        "target": list(target),
        "direction": list(direction),
        "distance": distance,
        "camera_location": list(camera_location),
        "focal_length": 38.0 if kind == "coverage" else 50.0,
        "notes": notes,
    }


def _normalize_direction(direction: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in direction)) or 1.0
    return tuple(value / length for value in direction)


def _vector(value: Any, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    try:
        if isinstance(value, dict):
            return (float(value.get("x", default[0])), float(value.get("y", default[1])), float(value.get("z", default[2])))
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return (float(value[0]), float(value[1]), float(value[2]))
        if hasattr(value, "__iter__"):
            items = list(value)
            if len(items) >= 3:
                return (float(items[0]), float(items[1]), float(items[2]))
    except (TypeError, ValueError):
        return default
    return default


def _json_candidates(text: str) -> list[str]:
    candidates = []
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE):
        candidates.append(match.group(1))
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    candidates.append(text)
    return candidates


def _score_from_text(text: str) -> float:
    match = re.search(r"(?:score|rating)\s*[:=]?\s*(0(?:\.\d+)?|1(?:\.0+)?|\d{1,3})", text, flags=re.IGNORECASE)
    if not match:
        return 0.0
    value = float(match.group(1))
    if value > 1.0:
        value = value / 100.0
    return value


def _plain_summary(text: str) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= 400:
        return compact
    return compact[:397] + "..."


def _issue_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            "id": str(value.get("id", value.get("issue_id", "")) or ""),
            "category": str(value.get("category", "") or ""),
            "severity": str(value.get("severity", "") or ""),
            "evidence": str(value.get("evidence", value.get("summary", "")) or ""),
            "target": str(value.get("target", "") or ""),
            "suggested_safe_fix": str(value.get("suggested_safe_fix", value.get("fix", "")) or ""),
        }
    return str(value)


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return max(min(number, maximum), minimum)
