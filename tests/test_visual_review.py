from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from codex_blender_agent.visual_review import (
    PHASE_COMPLETE,
    PHASE_CREATOR_RUNNING,
    PHASE_FAILED,
    PHASE_STOPPED,
    build_critic_prompt,
    VisualReviewStore,
    parse_critique,
    plan_viewpoints,
)


def test_plan_viewpoints_empty_scene_has_coverage_views():
    views = plan_viewpoints([])
    ids = {view["id"] for view in views}
    assert {"front", "back", "left", "right", "three_quarter", "top"}.issubset(ids)
    assert all("camera_location" in view and "target" in view for view in views)


def test_plan_viewpoints_castle_objects_adds_semantic_details():
    records = [
        {"name": "Castle_Gate", "location": [0, -2, 1], "dimensions": [3, 1, 2]},
        {"name": "North_Tower", "location": [4, 0, 4], "dimensions": [1, 1, 8]},
        {"name": "Stone_Wall", "location": [0, 3, 1], "dimensions": [8, 1, 2]},
    ]
    views = plan_viewpoints(records, max_detail_views=4)
    detail_terms = {view.get("semantic_term") for view in views if view.get("kind") == "detail"}
    assert {"gate", "tower", "wall"}.issubset(detail_terms)


def test_parse_critique_accepts_json_and_fenced_json():
    data = parse_critique('{"score": 0.9, "satisfied": true, "issues": [], "next_prompt": "", "summary": "done"}')
    assert data["score"] == 0.9
    assert data["satisfied"] is True

    fenced = parse_critique("""```json
{"score": 0.42, "issues": "too plain", "next_prompt": "add towers", "summary": "needs silhouette"}
```""")
    assert fenced["score"] == 0.42
    assert fenced["issues"] == ["too plain"]
    assert fenced["next_prompt"] == "add towers"


def test_parse_critique_accepts_geometry_critic_schema():
    data = parse_critique(
        json.dumps(
            {
                "critic_score": 0.81,
                "pairwise_vs_best": {"label": "better", "confidence": 0.77},
                "issues": [{"id": "geometry_01", "severity": "medium", "evidence": "floating shard"}],
                "issue_signature": ["floating_part:shard"],
                "delta_prompt": {
                    "owner_metric": "geometry",
                    "targets": ["defect_floating_part"],
                    "preserve": ["style", "object identity"],
                    "forbid": ["delete", "external import"],
                    "max_edits": 1,
                    "edits": [{"target": "shard", "op": "snap_to_support"}],
                },
                "summary": "needs one local fix",
            }
        )
    )
    assert data["critic_score"] == 0.81
    assert data["pairwise_vs_best"]["label"] == "better"
    assert data["issue_signature"] == ["floating_part:shard"]
    assert data["delta_prompt"]["mode"] == "patch"
    assert "bounded visual-review patch" in data["next_prompt"]


def test_build_critic_prompt_mentions_intent_manifest_and_validation_priority():
    prompt = build_critic_prompt(
        {
            "original_prompt": "make a castle",
            "current_prompt": "make a castle",
            "asset_intent_manifest": {"objects": [{"name": "Keep", "role": "support"}]},
        },
        [],
        geometry_payload={
            "metric_vector": {},
            "hard_gates": {},
            "defects": [],
            "asset_validation_report": {"report_id": "report-1", "asset_score": 88.0, "validation_summary": "ok", "top_issues": []},
        },
    )
    assert "Asset intent manifest" in prompt
    assert "Validation-first defects outrank screenshot polish" in prompt


def test_parse_critique_plain_text_fallback():
    data = parse_critique("Score: 74. The silhouette is readable. Next: add gate detail.")
    assert data["score"] == 0.74
    assert "silhouette" in data["summary"]


def test_visual_review_store_manifest_lifecycle(tmp_path):
    store = VisualReviewStore(tmp_path)
    run = store.create_run(prompt="make a castle", max_iterations=2, target_score=0.85)
    assert run["status"] == PHASE_CREATOR_RUNNING

    run = store.append_pass(
        run["run_id"],
        {"iteration": 1, "score": 0.5, "summary": "rough", "next_prompt": "add towers", "screenshots": []},
    )
    assert run["status"] == PHASE_CREATOR_RUNNING
    assert run["current_iteration"] == 2
    assert run["current_prompt"] == "add towers"

    run = store.append_pass(
        run["run_id"],
        {"iteration": 2, "score": 0.9, "summary": "good", "next_prompt": "", "screenshots": []},
    )
    assert run["status"] == PHASE_COMPLETE
    assert run["stop_reason"] == "target_score_reached"


def test_visual_review_store_stop_and_corrupt_manifest(tmp_path):
    store = VisualReviewStore(tmp_path)
    run = store.create_run(prompt="make a castle")
    stopped = store.request_stop(run["run_id"])
    assert stopped["status"] == PHASE_STOPPED
    assert stopped["stop_reason"] == "user_stopped"

    path = store.manifest_path(run["run_id"])
    path.write_text("{not-json", encoding="utf-8")
    corrupt = store.load_run(run["run_id"])
    assert corrupt["status"] == PHASE_FAILED
    assert corrupt["stop_reason"] == "manifest_corrupt"


def test_visual_review_store_plateau_stops(tmp_path):
    store = VisualReviewStore(tmp_path)
    run = store.create_run(prompt="make a castle", max_iterations=5, target_score=0.99)
    scores = [0.4, 0.41, 0.42]
    for index, score in enumerate(scores, start=1):
        run = store.append_pass(run["run_id"], {"iteration": index, "score": score, "summary": f"pass {index}", "next_prompt": "try again"})
    assert run["status"] == PHASE_STOPPED
    assert run["stop_reason"] == "score_plateau"


def test_creator_prompt_mentions_intent_manifest_and_validation_priority():
    runtime_source = (ROOT / "codex_blender_agent" / "runtime.py").read_text(encoding="utf-8")
    start = runtime_source.index("def _visual_review_creator_prompt")
    end = runtime_source.find("\n    def ", start + 1)
    creator_prompt_source = runtime_source[start:end]

    assert "Asset intent manifest" in creator_prompt_source
    assert "Validation-first defects outrank screenshot polish" in creator_prompt_source
