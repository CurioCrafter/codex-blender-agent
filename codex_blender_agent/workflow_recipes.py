from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SUPPORTED_PIN_MODES = ("exact", "compatible", "latest_within_major")
SUPPORTED_PATCH_OPS = ("add_node", "remove_node", "set_property", "add_link", "remove_link", "move_node", "wrap_as_recipe")
SUPPORTED_RISK_PROFILES = ("none", "read_only", "write", "destructive", "publish")
SUPPORTED_RECIPE_FIELDS = (
    "recipe_id",
    "display_name",
    "version",
    "graph_hash",
    "input_schema",
    "output_schema",
    "required_tools",
    "risk_profile",
    "author",
    "changelog",
    "preview_image",
    "tests",
    "tags",
    "catalog_path",
    "compatibility_range",
)

SEMVER_RE = re.compile(
    r"^(?:v)?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecipeMetadataValidation:
    ok: bool
    issues: tuple[str, ...]
    normalized: dict[str, Any]
    manifest_hash: str


@dataclass(frozen=True)
class VersionPinResolution:
    requested_version: str
    pin_mode: str
    resolved_version: str
    candidates: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class GraphPatchValidationResult:
    ok: bool
    issues: tuple[str, ...]
    normalized: dict[str, Any]
    summary: str


def parse_semver(version: str | SemVer) -> SemVer:
    if isinstance(version, SemVer):
        return version
    text = str(version or "").strip()
    match = SEMVER_RE.match(text)
    if not match:
        raise ValueError(f"Invalid semantic version: {version!r}")
    prerelease = tuple(part for part in (match.group("prerelease") or "").split(".") if part)
    build = tuple(part for part in (match.group("build") or "").split(".") if part)
    return SemVer(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=prerelease,
        build=build,
    )


def format_semver(version: str | SemVer) -> str:
    semver = parse_semver(version)
    base = f"{semver.major}.{semver.minor}.{semver.patch}"
    if semver.prerelease:
        base += "-" + ".".join(semver.prerelease)
    if semver.build:
        base += "+" + ".".join(semver.build)
    return base


def compare_semver(left: str | SemVer, right: str | SemVer) -> int:
    a = parse_semver(left)
    b = parse_semver(right)
    if (a.major, a.minor, a.patch) != (b.major, b.minor, b.patch):
        return _compare_tuple((a.major, a.minor, a.patch), (b.major, b.minor, b.patch))
    if a.prerelease == b.prerelease:
        return 0
    if not a.prerelease:
        return 1
    if not b.prerelease:
        return -1
    return _compare_tuple(_prerelease_key(a.prerelease), _prerelease_key(b.prerelease))


def bump_semver(version: str | SemVer, part: str = "patch") -> str:
    semver = parse_semver(version)
    if part == "major":
        bumped = SemVer(semver.major + 1, 0, 0)
    elif part == "minor":
        bumped = SemVer(semver.major, semver.minor + 1, 0)
    elif part == "patch":
        bumped = SemVer(semver.major, semver.minor, semver.patch + 1)
    else:
        raise ValueError(f"Unsupported semver bump part: {part}")
    return format_semver(bumped)


def is_version_compatible(base_version: str | SemVer, candidate_version: str | SemVer) -> bool:
    base = parse_semver(base_version)
    candidate = parse_semver(candidate_version)
    return base.major == candidate.major and compare_semver(candidate, base) >= 0


def resolve_version_pin(
    available_versions: Sequence[str | SemVer],
    requested_version: str | SemVer | None,
    pin_mode: str = "compatible",
) -> VersionPinResolution:
    normalized_mode = _normalize_pin_mode(pin_mode)
    candidates = [format_semver(version) for version in available_versions]
    if not candidates:
        raise ValueError("No available versions were provided.")

    requested = format_semver(requested_version) if requested_version else ""
    ranked = sorted(candidates, key=_semver_sort_key, reverse=True)

    if normalized_mode == "exact":
        if not requested:
            raise ValueError("Exact pin mode requires a requested version.")
        if requested not in candidates:
            raise ValueError(f"Exact version not found: {requested}")
        return VersionPinResolution(requested, normalized_mode, requested, tuple(ranked), "Exact version match.")

    if not requested:
        resolved = ranked[0]
        return VersionPinResolution(requested, normalized_mode, resolved, tuple(ranked), "No requested version supplied; using latest available version.")

    requested_semver = parse_semver(requested)
    same_major = [candidate for candidate in candidates if parse_semver(candidate).major == requested_semver.major]
    if not same_major:
        raise ValueError(f"No versions available for major {requested_semver.major}.")

    if normalized_mode == "compatible":
        compatible = [candidate for candidate in same_major if compare_semver(candidate, requested_semver) >= 0]
        if not compatible:
            raise ValueError(f"No compatible version found for {requested}.")
        resolved = sorted(compatible, key=_semver_sort_key, reverse=True)[0]
        return VersionPinResolution(
            requested,
            normalized_mode,
            resolved,
            tuple(sorted(same_major, key=_semver_sort_key, reverse=True)),
            "Chosen from the same major and not older than the requested version.",
        )

    resolved = sorted(same_major, key=_semver_sort_key, reverse=True)[0]
    return VersionPinResolution(
        requested,
        normalized_mode,
        resolved,
        tuple(sorted(same_major, key=_semver_sort_key, reverse=True)),
        "Chosen as the latest available version within the same major line.",
    )


def validate_recipe_metadata(metadata: Mapping[str, Any]) -> RecipeMetadataValidation:
    issues: list[str] = []
    normalized = _normalize_mapping(metadata)

    if not isinstance(metadata, Mapping):
        issues.append("recipe metadata must be a mapping.")
        normalized = {}

    for field in SUPPORTED_RECIPE_FIELDS:
        if field not in normalized or _is_empty(normalized.get(field)):
            issues.append(f"missing required recipe field: {field}")

    recipe_id = _require_str(normalized, "recipe_id", issues)
    display_name = _require_str(normalized, "display_name", issues)
    version = _require_semver_field(normalized, "version", issues)
    graph_hash = _require_str(normalized, "graph_hash", issues).lower()
    if graph_hash and not HEX_SHA256_RE.match(graph_hash):
        issues.append("graph_hash must be a 64-character lowercase SHA-256 hex digest.")
    input_schema = normalized.get("input_schema")
    output_schema = normalized.get("output_schema")
    if not isinstance(input_schema, Mapping):
        issues.append("input_schema must be a mapping.")
    if not isinstance(output_schema, Mapping):
        issues.append("output_schema must be a mapping.")

    required_tools = _normalize_str_list(normalized.get("required_tools"))
    if not required_tools:
        issues.append("required_tools must be a non-empty list of tool IDs.")

    risk_profile = _require_str(normalized, "risk_profile", issues)
    if risk_profile and risk_profile not in SUPPORTED_RISK_PROFILES:
        issues.append(f"unsupported risk_profile: {risk_profile}")

    author = _require_str(normalized, "author", issues)
    changelog = _require_str(normalized, "changelog", issues)
    preview_image = _require_str(normalized, "preview_image", issues)
    tests = normalized.get("tests")
    if not isinstance(tests, list) or not tests:
        issues.append("tests must be a non-empty list.")
    tags = _normalize_str_list(normalized.get("tags"))
    catalog_path = _require_str(normalized, "catalog_path", issues)
    compatibility_range = normalized.get("compatibility_range")
    if _is_empty(compatibility_range):
        issues.append("compatibility_range must be provided.")
    else:
        compatibility_range = _normalize_compatibility_range(compatibility_range, issues)

    normalized_metadata = {
        **normalized,
        "recipe_id": recipe_id,
        "display_name": display_name,
        "version": version,
        "graph_hash": graph_hash,
        "input_schema": dict(input_schema) if isinstance(input_schema, Mapping) else input_schema,
        "output_schema": dict(output_schema) if isinstance(output_schema, Mapping) else output_schema,
        "required_tools": required_tools,
        "risk_profile": risk_profile,
        "author": author,
        "changelog": changelog,
        "preview_image": preview_image,
        "tests": list(tests) if isinstance(tests, list) else tests,
        "tags": tags,
        "catalog_path": catalog_path,
        "compatibility_range": compatibility_range,
    }
    manifest_hash = hash_recipe_manifest(normalized_metadata)
    return RecipeMetadataValidation(ok=not issues, issues=tuple(issues), normalized=normalized_metadata, manifest_hash=manifest_hash)


def hash_recipe_manifest(manifest: Mapping[str, Any] | Sequence[Any]) -> str:
    payload = _canonicalize(manifest)
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def validate_graph_patch_proposal(
    proposal: Mapping[str, Any],
    *,
    graph_state: Mapping[str, Any] | None = None,
) -> GraphPatchValidationResult:
    issues: list[str] = []
    normalized = _normalize_mapping(proposal)
    if not isinstance(proposal, Mapping):
        issues.append("graph patch proposal must be a mapping.")
        normalized = {}

    operations = normalized.get("operations")
    if not isinstance(operations, list) or not operations:
        issues.append("operations must be a non-empty list.")
        operations = []

    known_nodes = _known_graph_nodes(graph_state)
    known_nodes_from_ops: set[str] = set()
    normalized_ops: list[dict[str, Any]] = []

    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, Mapping):
            issues.append(f"operation {index} must be a mapping.")
            continue
        op = _normalize_op_name(operation.get("op", operation.get("operation", "")))
        if op not in SUPPORTED_PATCH_OPS:
            issues.append(f"operation {index} uses unsupported op: {op or operation.get('op')!r}.")
            continue

        normalized_operation = dict(operation)
        normalized_operation["op"] = op

        if op == "add_node":
            node_id = _require_nonempty_text(normalized_operation, "node_id", index, issues)
            _require_nonempty_text(normalized_operation, "node_type", index, issues)
            if node_id in known_nodes or node_id in known_nodes_from_ops:
                issues.append(f"operation {index} add_node reuses an existing node_id: {node_id}.")
            known_nodes_from_ops.add(node_id)

        elif op == "remove_node":
            node_id = _require_nonempty_text(normalized_operation, "node_id", index, issues)
            _require_known_node(node_id, index, known_nodes, known_nodes_from_ops, issues)
            known_nodes.discard(node_id)
            known_nodes_from_ops.discard(node_id)

        elif op == "set_property":
            node_id = _require_nonempty_text(normalized_operation, "node_id", index, issues)
            _require_known_node(node_id, index, known_nodes, known_nodes_from_ops, issues)
            _require_nonempty_text(normalized_operation, "property", index, issues)
            if "value" not in normalized_operation:
                issues.append(f"operation {index} set_property requires a value.")

        elif op in {"add_link", "remove_link"}:
            source = _require_nonempty_text(normalized_operation, "from_node", index, issues)
            target = _require_nonempty_text(normalized_operation, "to_node", index, issues)
            _require_nonempty_text(normalized_operation, "from_socket", index, issues)
            _require_nonempty_text(normalized_operation, "to_socket", index, issues)
            _require_known_node(source, index, known_nodes, known_nodes_from_ops, issues)
            _require_known_node(target, index, known_nodes, known_nodes_from_ops, issues)

        elif op == "move_node":
            node_id = _require_nonempty_text(normalized_operation, "node_id", index, issues)
            _require_known_node(node_id, index, known_nodes, known_nodes_from_ops, issues)
            location = normalized_operation.get("location")
            if not _is_numeric_pair(location):
                issues.append(f"operation {index} move_node requires a numeric 2-item location.")

        elif op == "wrap_as_recipe":
            recipe = normalized_operation.get("recipe")
            if not isinstance(recipe, Mapping):
                issues.append(f"operation {index} wrap_as_recipe requires a recipe mapping.")
            else:
                recipe_validation = validate_recipe_metadata(recipe)
                if not recipe_validation.ok:
                    issues.extend(f"operation {index} recipe: {issue}" for issue in recipe_validation.issues)
                normalized_operation["recipe"] = recipe_validation.normalized
            node_ids = normalized_operation.get("node_ids")
            if not isinstance(node_ids, list) or not node_ids:
                issues.append(f"operation {index} wrap_as_recipe requires a non-empty node_ids list.")
            else:
                missing = [node_id for node_id in node_ids if node_id not in known_nodes and node_id not in known_nodes_from_ops]
                if missing:
                    issues.append(f"operation {index} wrap_as_recipe references unknown node_ids: {', '.join(missing)}.")

        normalized_ops.append(normalized_operation)

    normalized_result = {**normalized, "operations": normalized_ops}
    summary = _summarize_patch_operations(normalized_ops)
    return GraphPatchValidationResult(ok=not issues, issues=tuple(issues), normalized=normalized_result, summary=summary)


def summarize_graph_patch_diff(before: Mapping[str, Any] | Sequence[Any], after: Mapping[str, Any] | Sequence[Any]) -> str:
    before_nodes = _graph_node_map(before)
    after_nodes = _graph_node_map(after)
    before_links = _graph_link_set(before)
    after_links = _graph_link_set(after)

    added_nodes = sorted(set(after_nodes) - set(before_nodes))
    removed_nodes = sorted(set(before_nodes) - set(after_nodes))
    changed_nodes = sorted(node_id for node_id in set(before_nodes) & set(after_nodes) if before_nodes[node_id] != after_nodes[node_id])
    added_links = sorted(after_links - before_links)
    removed_links = sorted(before_links - after_links)

    lines = []
    if added_nodes:
        lines.append(f"Added nodes: {', '.join(added_nodes)}")
    if removed_nodes:
        lines.append(f"Removed nodes: {', '.join(removed_nodes)}")
    if changed_nodes:
        details = []
        for node_id in changed_nodes:
            detail = _summarize_mapping_diff(before_nodes[node_id], after_nodes[node_id], limit=3)
            details.append(f"{node_id} ({detail})")
        lines.append(f"Changed nodes: {'; '.join(details)}")
    if added_links:
        lines.append(f"Added links: {', '.join(_format_link(link) for link in added_links)}")
    if removed_links:
        lines.append(f"Removed links: {', '.join(_format_link(link) for link in removed_links)}")
    if not lines:
        return "No graph changes."
    return " | ".join(lines)


def summarize_recipe_manifest_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    summary = _summarize_mapping_diff(before, after, limit=6)
    return summary or "No recipe manifest changes."


def _normalize_pin_mode(pin_mode: str) -> str:
    mode = (pin_mode or "").strip()
    if mode not in SUPPORTED_PIN_MODES:
        valid = ", ".join(SUPPORTED_PIN_MODES)
        raise ValueError(f"Unsupported pin mode: {pin_mode}. Valid modes: {valid}")
    return mode


def _normalize_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(val) for key, val in value.items()}
    return {}


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_compatibility_range(value: Any, issues: list[str]) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            issues.append("compatibility_range cannot be empty.")
        return text
    if isinstance(value, Mapping):
        normalized = {str(key): _canonicalize(item) for key, item in value.items()}
        if not normalized:
            issues.append("compatibility_range cannot be empty.")
        for key in ("min", "max", "addon_min", "addon_max", "major"):
            if key in normalized and not _is_empty(normalized[key]):
                if key == "major":
                    try:
                        normalized[key] = int(normalized[key])
                    except Exception:
                        issues.append("compatibility_range.major must be an integer.")
                elif key != "major":
                    try:
                        normalized[key] = format_semver(normalized[key])
                    except Exception as exc:
                        issues.append(f"compatibility_range.{key} is not a valid semantic version: {exc}")
        return normalized
    issues.append("compatibility_range must be a string or mapping.")
    return value


def _require_str(mapping: Mapping[str, Any], key: str, issues: list[str]) -> str:
    value = mapping.get(key, "")
    text = str(value).strip()
    if not text:
        issues.append(f"{key} must be a non-empty string.")
    return text


def _require_semver_field(mapping: Mapping[str, Any], key: str, issues: list[str]) -> str:
    value = _require_str(mapping, key, issues)
    if value:
        try:
            value = format_semver(value)
        except Exception as exc:
            issues.append(f"{key} is not a valid semantic version: {exc}")
    return value


def _require_nonempty_text(operation: Mapping[str, Any], key: str, index: int, issues: list[str]) -> str:
    text = str(operation.get(key, "")).strip()
    if not text:
        issues.append(f"operation {index} requires {key}.")
    return text


def _require_known_node(node_id: str, index: int, known_nodes: set[str], known_nodes_from_ops: set[str], issues: list[str]) -> None:
    if node_id not in known_nodes and node_id not in known_nodes_from_ops:
        issues.append(f"operation {index} references unknown node_id: {node_id}.")


def _is_numeric_pair(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    try:
        float(value[0])
        float(value[1])
    except Exception:
        return False
    return True


def _canonicalize(value: Any) -> Any:
    if is_dataclass(value):
        return _canonicalize(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, set):
        items = [_canonicalize(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=True, sort_keys=True, default=str))
    if isinstance(value, Path):
        return str(value)
    return value


def _compare_tuple(left: Sequence[Any], right: Sequence[Any]) -> int:
    return (left > right) - (left < right)


def _prerelease_key(parts: tuple[str, ...]) -> tuple[tuple[int, Any], ...]:
    key = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


def _semver_sort_key(value: str | SemVer) -> tuple[Any, ...]:
    semver = parse_semver(value)
    release_flag = 1 if not semver.prerelease else 0
    return (
        semver.major,
        semver.minor,
        semver.patch,
        release_flag,
        _prerelease_key(semver.prerelease),
        _prerelease_key(semver.build),
    )


def _known_graph_nodes(graph_state: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(graph_state, Mapping):
        return set()
    candidates: set[str] = set()
    node_ids = graph_state.get("node_ids")
    if isinstance(node_ids, list):
        candidates.update(str(node_id) for node_id in node_ids if str(node_id).strip())
    nodes = graph_state.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, Mapping):
                node_id = str(node.get("node_id") or node.get("id") or node.get("name") or "").strip()
                if node_id:
                    candidates.add(node_id)
    return candidates


def _normalize_op_name(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text


def _graph_node_map(graph: Mapping[str, Any] | Sequence[Any]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    if isinstance(graph, Mapping):
        raw_nodes = graph.get("nodes", [])
    else:
        raw_nodes = graph
    if not isinstance(raw_nodes, list):
        return nodes
    for index, node in enumerate(raw_nodes):
        if not isinstance(node, Mapping):
            continue
        node_id = str(node.get("node_id") or node.get("id") or node.get("name") or f"node_{index}").strip()
        if not node_id:
            continue
        nodes[node_id] = {str(key): _canonicalize(val) for key, val in node.items()}
    return nodes


def _graph_link_set(graph: Mapping[str, Any] | Sequence[Any]) -> set[tuple[str, str, str, str]]:
    if isinstance(graph, Mapping):
        raw_links = graph.get("links", [])
    else:
        raw_links = []
    if not isinstance(raw_links, list):
        return set()
    links: set[tuple[str, str, str, str]] = set()
    for link in raw_links:
        if not isinstance(link, Mapping):
            continue
        links.add(
            (
                str(link.get("from_node", "")).strip(),
                str(link.get("from_socket", "")).strip(),
                str(link.get("to_node", "")).strip(),
                str(link.get("to_socket", "")).strip(),
            )
        )
    return links


def _format_link(link: tuple[str, str, str, str]) -> str:
    from_node, from_socket, to_node, to_socket = link
    return f"{from_node}:{from_socket} -> {to_node}:{to_socket}"


def _summarize_patch_operations(operations: Sequence[Mapping[str, Any]]) -> str:
    if not operations:
        return "No patch operations."
    parts = []
    for operation in operations[:6]:
        op = str(operation.get("op", ""))
        if op == "add_node":
            parts.append(f"add {operation.get('node_id', '<node>')}:{operation.get('node_type', '<type>')}")
        elif op == "remove_node":
            parts.append(f"remove {operation.get('node_id', '<node>')}")
        elif op == "set_property":
            parts.append(f"set {operation.get('node_id', '<node>')}.{operation.get('property', '<property>')}")
        elif op in {"add_link", "remove_link"}:
            parts.append(f"{op} {operation.get('from_node', '<from>')} -> {operation.get('to_node', '<to>')}")
        elif op == "move_node":
            parts.append(f"move {operation.get('node_id', '<node>')}")
        elif op == "wrap_as_recipe":
            recipe = operation.get("recipe", {})
            title = recipe.get("display_name", "recipe") if isinstance(recipe, Mapping) else "recipe"
            parts.append(f"wrap as recipe {title}")
    summary = ", ".join(parts)
    if len(operations) > 6:
        summary += f", +{len(operations) - 6} more"
    return summary


def _summarize_mapping_diff(before: Mapping[str, Any], after: Mapping[str, Any], *, limit: int = 6) -> str:
    changes: list[str] = []
    _collect_mapping_diff(_canonicalize(before), _canonicalize(after), "", changes, limit)
    if not changes:
        return "no field changes"
    return "; ".join(changes[:limit])


def _collect_mapping_diff(before: Any, after: Any, prefix: str, changes: list[str], limit: int) -> None:
    if len(changes) >= limit:
        return
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        keys = sorted(set(before) | set(after), key=str)
        for key in keys:
            if len(changes) >= limit:
                return
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                changes.append(f"+ {path}")
            elif key not in after:
                changes.append(f"- {path}")
            else:
                _collect_mapping_diff(before[key], after[key], path, changes, limit)
        return
    if isinstance(before, list) and isinstance(after, list):
        if before != after:
            changes.append(f"~ {prefix}: list changed")
        return
    if before != after:
        changes.append(f"~ {prefix}: {before!r} -> {after!r}")


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


__all__ = [
    "GraphPatchValidationResult",
    "RecipeMetadataValidation",
    "SemVer",
    "SUPPORTED_PATCH_OPS",
    "SUPPORTED_PIN_MODES",
    "SUPPORTED_RECIPE_FIELDS",
    "SUPPORTED_RISK_PROFILES",
    "VersionPinResolution",
    "bump_semver",
    "compare_semver",
    "format_semver",
    "hash_recipe_manifest",
    "is_version_compatible",
    "parse_semver",
    "resolve_version_pin",
    "summarize_graph_patch_diff",
    "summarize_recipe_manifest_diff",
    "validate_graph_patch_proposal",
    "validate_recipe_metadata",
]
