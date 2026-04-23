from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .validation_manifest import AssetIntentManifest, build_constraint_graph as _build_constraint_graph
from .validation_manifest import infer_asset_intent_manifest, normalize_asset_intent_manifest
from .visual_geometry import clamp, record_bounds_points, scene_aabb, vector3


@dataclass(frozen=True)
class ConstraintGraph:
    data: dict[str, Any]

    @classmethod
    def from_records(
        cls,
        records: Iterable[dict[str, Any]],
        *,
        manifest: dict[str, Any] | AssetIntentManifest | None = None,
        prompt: str = "",
    ) -> "ConstraintGraph":
        return cls(build_constraint_graph(records, manifest=manifest, prompt=prompt))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(self.data)

    @property
    def nodes(self) -> list[dict[str, Any]]:
        return list(self.data.get("nodes", []) or [])

    @property
    def edges(self) -> list[dict[str, Any]]:
        return list(self.data.get("edges", []) or [])

    @property
    def summary(self) -> dict[str, Any]:
        return dict(self.data.get("summary", {}) or {})


def build_constraint_graph(
    records: Iterable[dict[str, Any]],
    *,
    manifest: dict[str, Any] | AssetIntentManifest | None = None,
    prompt: str = "",
) -> dict[str, Any]:
    manifest_data = _manifest_dict(manifest, records=records, prompt=prompt)
    graph = _build_constraint_graph(records, manifest_data)
    for item in manifest_data.get("objects", []) or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("name", "")).strip()
        if not source:
            continue
        for target in item.get("must_touch", []) or []:
            graph.setdefault("edges", []).append(_edge(source, str(target), "must_touch", "manifest", {"source": "manifest_object"}))
        for target in item.get("must_not_intersect", []) or []:
            graph.setdefault("edges", []).append(_edge(source, str(target), "must_not_intersect", "manifest", {"source": "manifest_object"}))
        for target in item.get("centered_on", []) or []:
            graph.setdefault("edges", []).append(_edge(source, str(target), "centered_on", "manifest", {"source": "manifest_object"}))
        for target in item.get("flush_with", []) or []:
            graph.setdefault("edges", []).append(_edge(source, str(target), "flush_with", "manifest", {"source": "manifest_object"}))
        for target in item.get("support", []) or []:
            graph.setdefault("edges", []).append(_edge(source, str(target), "supported_by", "manifest", {"source": "manifest_object"}))
        symmetry_group = str(item.get("symmetry_group", "")).strip()
        if symmetry_group:
            graph.setdefault("edges", []).append(_edge(source, symmetry_group, "symmetry_member", "manifest", {"source": "manifest_object"}))
        origin_pivot = str(item.get("origin_pivot", "")).strip()
        if origin_pivot:
            graph.setdefault("edges", []).append(_edge(source, origin_pivot, "origin_pivot", "manifest", {"source": "manifest_object"}))
    symmetry_groups = manifest_data.get("symmetry_groups", {}) or {}
    if isinstance(symmetry_groups, dict):
        for group_name, members in symmetry_groups.items():
            members_list = [str(member).strip() for member in members or [] if str(member).strip()]
            for index, left in enumerate(members_list):
                for right in members_list[index + 1 :]:
                    graph.setdefault("edges", []).append(_edge(left, right, "symmetry_peer", "manifest", {"group": group_name}))
    normalized_edges: list[dict[str, Any]] = []
    for edge in graph.get("edges", []) or []:
        edge = dict(edge)
        edge.setdefault("type", str(edge.get("relation", "")))
        edge.setdefault("source_kind", str(edge.get("constraint_source", "")))
        normalized_edges.append(edge)
    graph["edges"] = normalized_edges
    graph.setdefault("summary", {})
    graph["summary"].setdefault("node_count", len(graph.get("nodes", []) or []))
    graph["summary"].setdefault("edge_count", len(graph.get("edges", []) or []))
    graph["summary"]["relation_types"] = _count_by(graph.get("edges", []) or [], "type")
    graph["summary"]["source_kinds"] = _count_by(graph.get("edges", []) or [], "source_kind")
    return graph


def infer_constraint_graph(
    records: Iterable[dict[str, Any]],
    *,
    prompt: str = "",
) -> dict[str, Any]:
    return build_constraint_graph(records, prompt=prompt)


def summarize_constraint_graph(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = list(graph.get("nodes", []) or [])
    edges = list(graph.get("edges", []) or [])
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "relation_types": _count_by(edges, "type"),
        "source_kinds": _count_by(edges, "source_kind"),
    }


def manifest_object_roles(manifest: dict[str, Any] | AssetIntentManifest | None) -> dict[str, str]:
    manifest_data = _manifest_dict(manifest)
    roles: dict[str, str] = {}
    for item in manifest_data.get("objects", []) or []:
        name = str(item.get("name", "")).strip()
        if name:
            roles[name] = str(item.get("role", "")).strip()
    return roles


def _manifest_dict(
    manifest: dict[str, Any] | AssetIntentManifest | None,
    *,
    records: Iterable[dict[str, Any]] | None = None,
    prompt: str = "",
) -> dict[str, Any]:
    if manifest is None:
        return infer_asset_intent_manifest(records or [], prompt=prompt).to_dict()
    if isinstance(manifest, AssetIntentManifest):
        return manifest.to_dict()
    return normalize_asset_intent_manifest(manifest, records=records, prompt=prompt)


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "")).strip() or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda row: row[0]))


def _edge(source: str, target: str, relation: str, source_kind: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"{relation}:{source}->{target}",
        "source": source,
        "target": target,
        "relation": relation,
        "type": relation,
        "constraint_source": source_kind,
        "source_kind": source_kind,
        "confidence": 0.95 if source_kind == "manifest" else 0.65,
        "evidence": _json_safe(evidence),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
