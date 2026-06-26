from __future__ import annotations

import json
import math
import re
from itertools import combinations
from typing import Any, Iterable


Graph = dict[str, Any]


def build_character_graph(
    world_items: Iterable[dict[str, Any]],
    chapters: Iterable[dict[str, Any]] | None = None,
    sections_by_chapter: dict[Any, Iterable[dict[str, Any]]] | None = None,
    include_inferred: bool = False,
) -> Graph:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    items = [item for item in world_items if isinstance(item, dict)]
    characters = [item for item in items if item.get("kind") == "character"]
    organizations = [item for item in items if item.get("kind") == "organization"]
    character_index = _kind_name_index(characters).get("character", {})
    organization_index = _kind_name_index(organizations).get("organization", {})

    for item in characters:
        nodes[_node_id(item)] = _world_item_node(item, warnings)
    for item in organizations:
        nodes[_node_id(item)] = _world_item_node(item, warnings)

    for item in characters:
        source = _node_id(item)
        for index, relation in enumerate(_as_list(_details(item, warnings).get("relationships"))):
            edge = _character_relationship_edge(
                source,
                item,
                relation,
                index,
                character_index,
                organization_index,
                nodes,
                warnings,
            )
            if edge:
                _store_edge(edges, edge)
        _add_character_organization_edges(source, item, organization_index, nodes, edges, warnings)

    for item in organizations:
        _add_organization_member_edges(_node_id(item), item, character_index, nodes, edges, warnings)

    _add_chapter_memory_relationships(nodes, edges, items, character_index, warnings)

    if include_inferred:
        _add_same_scene_edges(nodes, edges, chapters or [], sections_by_chapter or {}, character_index)

    _bump_weights(nodes, edges.values())
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "warnings": warnings}


def build_event_graph(
    world_items: Iterable[dict[str, Any]],
    chapters: Iterable[dict[str, Any]] | None = None,
    sections_by_chapter: dict[Any, Iterable[dict[str, Any]]] | None = None,
    include_inferred: bool = False,
) -> Graph:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    items = [item for item in world_items if isinstance(item, dict)]
    by_kind_name = _kind_name_index(items)
    event_items = [item for item in items if item.get("kind") == "timeline_event"]

    for item in event_items:
        nodes[_node_id(item)] = _event_item_node(item, warnings)

    for item in event_items:
        source = _node_id(item)
        details = _details(item, warnings)
        _add_graph_links(nodes, edges, item, source, details.get("graph_links"), by_kind_name, warnings)
        _add_named_edges(nodes, edges, item, source, details.get("causes"), "timeline_event", "causes", by_kind_name, warnings)
        _add_named_edges(
            nodes,
            edges,
            item,
            source,
            details.get("caused_by"),
            "timeline_event",
            "caused_by",
            by_kind_name,
            warnings,
            reverse=True,
        )
        _add_named_edges(
            nodes,
            edges,
            item,
            source,
            details.get("participants", details.get("characters")),
            "character",
            "participant",
            by_kind_name,
            warnings,
        )
        _add_named_edges(
            nodes,
            edges,
            item,
            source,
            details.get("location", details.get("locations")),
            "location",
            "located_at",
            by_kind_name,
            warnings,
        )
        _add_named_edges(
            nodes,
            edges,
            item,
            source,
            details.get("related_organizations", details.get("organizations")),
            "organization",
            "member_action",
            by_kind_name,
            warnings,
        )
        _add_named_edges(
            nodes,
            edges,
            item,
            source,
            details.get("related_foreshadowing"),
            "foreshadowing",
            "foreshadow",
            by_kind_name,
            warnings,
        )
        _add_named_edges(
            nodes,
            edges,
            item,
            source,
            details.get("related_rules"),
            "rule",
            "rule_constraint",
            by_kind_name,
            warnings,
        )
        _add_named_edges(
            nodes,
            edges,
            item,
            source,
            details.get("forbidden"),
            "forbidden",
            "forbidden_constraint",
            by_kind_name,
            warnings,
        )

    if include_inferred:
        _add_inferred_events(nodes, edges, chapters or [], sections_by_chapter or {}, by_kind_name)

    _bump_weights(nodes, edges.values())
    return {"nodes": _event_graph_nodes(nodes), "edges": list(edges.values()), "warnings": warnings}


def _details(item: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    raw = item.get("details_json", item.get("details", {}))
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            warnings.append(f"Invalid details JSON for {_item_ref(item)}")
            return {}
        if isinstance(loaded, dict):
            return loaded
        warnings.append(f"Details JSON is not an object for {_item_ref(item)}")
        return {}
    warnings.append(f"Unsupported details value for {_item_ref(item)}")
    return {}


def _world_item_node(item: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    details = _details(item, warnings)
    role_flags = details.get("role_flags") if isinstance(details.get("role_flags"), dict) else {}
    tags = _split_values(item.get("tags"))
    return {
        "id": _node_id(item),
        "kind": str(item.get("kind") or ""),
        "source_id": item.get("id"),
        "name": _item_name(item),
        "label": _item_name(item),
        "summary": str(item.get("summary") or ""),
        "tags": tags,
        "weight": 1 + len(tags) + (3 if role_flags.get("protagonist") else 0),
        "status": str(item.get("status") or ""),
        "source": "world_item",
    }


def _event_item_node(item: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    node = _world_item_node(item, warnings)
    details = _details(item, warnings)
    node["ordering"] = _event_ordering(item, details)
    return node


def _event_ordering(item: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    phase = str(details.get("phase") or "").strip()
    time_text = str(details.get("time_text") or "").strip()
    status = str(details.get("status") or item.get("status") or "").strip()
    sequence = details.get("sequence")
    explicit_sort_key = details.get("sort_key")
    sort_key = explicit_sort_key if explicit_sort_key not in (None, "") else [phase, sequence, time_text]
    return {
        "time_text": time_text,
        "sequence": sequence,
        "phase": phase,
        "status": status,
        "sort_key": sort_key,
    }


def _event_graph_nodes(nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    real_events = [
        (index, node)
        for index, node in enumerate(nodes.values())
        if node.get("kind") == "timeline_event" and node.get("source") == "world_item"
    ]
    real_event_ids = {node["id"] for _, node in real_events}
    sorted_events = [node for _, node in sorted(real_events, key=lambda indexed: _event_node_sort_key(*indexed))]
    remaining = [node for node in nodes.values() if node.get("id") not in real_event_ids]
    return [*sorted_events, *remaining]


def _event_node_sort_key(index: int, node: dict[str, Any]) -> tuple[Any, ...]:
    ordering = node.get("ordering") if isinstance(node.get("ordering"), dict) else {}
    phase = str(ordering.get("phase") or "")
    sequence = ordering.get("sequence")
    time_text = str(ordering.get("time_text") or "")
    return (
        0 if phase else 1,
        phase.casefold(),
        0 if sequence not in (None, "") else 1,
        _sequence_sort_value(sequence),
        time_text.casefold(),
        index,
    )


def _sequence_sort_value(value: Any) -> tuple[int, Any]:
    if value in (None, ""):
        return (1, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, int) or isinstance(value, float):
        return (0, value)
    text = str(value).strip()
    try:
        return (0, float(text))
    except ValueError:
        return (0, text.casefold())


def _character_relationship_edge(
    source: str,
    item: dict[str, Any],
    relation: Any,
    index: int,
    character_index: dict[str, dict[str, Any]],
    organization_index: dict[str, dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any] | None:
    evidence = f"{_item_name(item)}.details.relationships[{index}]"
    if isinstance(relation, dict):
        target_name = (
            relation.get("target")
            or relation.get("target_name")
            or relation.get("character")
            or relation.get("organization")
            or relation.get("faction")
            or relation.get("name")
        )
        kind = str(relation.get("type") or relation.get("kind") or relation.get("relation") or "relationship")
        label = str(relation.get("label") or relation.get("relation") or relation.get("status") or kind)
        summary = str(relation.get("summary") or relation.get("description") or "")
        confidence = "explicit"
    else:
        summary = str(relation or "").strip()
        target_name = _find_known_name(summary, character_index, exclude=_item_name(item))
        if not target_name:
            target_name = _find_known_name(summary, organization_index)
        kind = "relationship"
        label = summary
        confidence = "text_match"

    target_kind, target_index = _relationship_target_kind(target_name, character_index, organization_index)
    target = _resolve_node(nodes, target_kind, target_name, target_index, item, evidence, warnings)
    if not target:
        return None
    if target_kind == "organization":
        kind = "affiliated_with"
    return _edge(source, target, kind, label, summary, 2 if confidence == "explicit" else 1, confidence, [evidence])


def _relationship_target_kind(
    target_name: Any,
    character_index: dict[str, dict[str, Any]],
    organization_index: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]]]:
    key = _name_key(target_name)
    if key in character_index:
        return "character", character_index
    if key in organization_index:
        return "organization", organization_index
    if _looks_like_organization_name(target_name):
        return "organization", organization_index
    return "character", character_index


def _add_chapter_memory_relationships(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    character_index: dict[str, dict[str, Any]],
    warnings: list[str],
) -> None:
    for item in items:
        details = _details(item, warnings)
        for memory_index, memory in enumerate(_as_list(details.get("chapter_memory"))):
            if not isinstance(memory, dict):
                continue
            evidence = f"{_item_name(item)}.details.chapter_memory[{memory_index}].relationship_delta"
            for delta in _as_list(memory.get("relationship_delta")):
                if isinstance(delta, dict):
                    source_name = delta.get("source") or delta.get("from") or (_item_name(item) if item.get("kind") == "character" else "")
                    target_name = delta.get("target") or delta.get("to") or delta.get("character")
                    source = _resolve_node(nodes, "character", source_name, character_index, item, evidence, warnings)
                    target = _resolve_node(nodes, "character", target_name, character_index, item, evidence, warnings)
                    if source and target:
                        kind = str(delta.get("type") or "relationship_delta")
                        label = str(delta.get("label") or delta.get("change") or kind)
                        summary = str(delta.get("summary") or delta.get("change") or "")
                        _store_edge(edges, _edge(source, target, kind, label, summary, 2, "explicit", [evidence]))
                    continue
                if item.get("kind") != "character":
                    continue
                text = str(delta or "").strip()
                target_name = _find_known_name(text, character_index, exclude=_item_name(item))
                source = _resolve_node(nodes, "character", _item_name(item), character_index, item, evidence, warnings)
                target = _resolve_node(nodes, "character", target_name, character_index, item, evidence, warnings) if target_name else None
                if source and target:
                    _store_edge(edges, _edge(source, target, "relationship_delta", text, text, 1, "text_match", [evidence]))


def _add_same_scene_edges(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    chapters: Iterable[dict[str, Any]],
    sections_by_chapter: dict[Any, Iterable[dict[str, Any]]],
    character_index: dict[str, dict[str, Any]],
) -> None:
    for chapter in chapters:
        groups = [(chapter.get("characters"), f"chapter:{chapter.get('id', chapter.get('number', '?'))}")]
        chapter_key = chapter.get("id", chapter.get("number"))
        for section in sections_by_chapter.get(chapter_key, []):
            groups.append((section.get("characters"), f"chapter:{chapter_key}:section:{section.get('id', section.get('number', '?'))}"))
        for names, evidence in groups:
            ids = []
            for name in _split_values(names):
                item = character_index.get(_name_key(name))
                if item:
                    node_id = _node_id(item)
                    nodes.setdefault(node_id, _world_item_node(item, []))
                    ids.append(node_id)
            for left, right in combinations(sorted(set(ids)), 2):
                _store_edge(edges, _edge(left, right, "same_scene", "同场", "", 1, "inferred", [evidence]))


def _add_character_organization_edges(
    source: str,
    item: dict[str, Any],
    organization_index: dict[str, dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    warnings: list[str],
) -> None:
    details = _details(item, warnings)
    for field in ["organization", "organizations", "faction", "affiliation", "affiliations"]:
        for index, value in enumerate(_as_list(details.get(field))):
            name = _organization_name(value)
            if not name:
                continue
            evidence = f"{_item_name(item)}.details.{field}[{index}]"
            target = _resolve_node(nodes, "organization", name, organization_index, item, evidence, warnings)
            if target:
                label = str(value.get("role") or value.get("label") or "member_of") if isinstance(value, dict) else "member_of"
                summary = str(value.get("summary") or "") if isinstance(value, dict) else ""
                _store_edge(edges, _edge(source, target, "member_of", label, summary, 2, "explicit", [evidence]))

    modules = details.get("modules")
    if isinstance(modules, dict):
        _add_module_organization_edges(source, item, modules, organization_index, nodes, edges, warnings, f"{_item_name(item)}.details.modules")


def _add_module_organization_edges(
    source: str,
    item: dict[str, Any],
    value: Any,
    organization_index: dict[str, dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    warnings: list[str],
    path: str,
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in {"organization", "organizations", "faction", "affiliation", "affiliations"}:
                for index, name_value in enumerate(_as_list(child)):
                    name = _organization_name(name_value)
                    if not name:
                        continue
                    evidence = f"{path}.{key}[{index}]"
                    target = _resolve_node(nodes, "organization", name, organization_index, item, evidence, warnings)
                    if target:
                        label = str(name_value.get("role") or name_value.get("label") or "member_of") if isinstance(name_value, dict) else "member_of"
                        summary = str(name_value.get("summary") or "") if isinstance(name_value, dict) else ""
                        _store_edge(edges, _edge(source, target, "member_of", label, summary, 1, "explicit", [evidence]))
                continue
            _add_module_organization_edges(source, item, child, organization_index, nodes, edges, warnings, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _add_module_organization_edges(source, item, child, organization_index, nodes, edges, warnings, f"{path}[{index}]")


def _add_organization_member_edges(
    organization_node_id: str,
    item: dict[str, Any],
    character_index: dict[str, dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    warnings: list[str],
) -> None:
    details = _details(item, warnings)
    member_fields = [("members", "member_of", "member"), ("member_names", "member_of", "member")]
    leader_fields = [("leader", "leader_of", "leader"), ("leaders", "leader_of", "leader")]
    for field, kind, label in [*member_fields, *leader_fields]:
        for index, value in enumerate(_as_list(details.get(field))):
            name = _target_name(value)
            if not name:
                continue
            evidence = f"{_item_name(item)}.details.{field}[{index}]"
            character = _resolve_node(nodes, "character", name, character_index, item, evidence, warnings)
            if character:
                summary = str(value.get("summary") or "") if isinstance(value, dict) else ""
                _store_edge(edges, _edge(character, organization_node_id, kind, label, summary, 2, "explicit", [evidence]))


def _add_graph_links(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    item: dict[str, Any],
    source: str,
    links: Any,
    by_kind_name: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    for index, link in enumerate(_as_list(links)):
        evidence = f"{_item_name(item)}.details.graph_links[{index}]"
        if isinstance(link, dict):
            target_kind = str(link.get("target_kind") or link.get("kind") or "timeline_event")
            target_name = link.get("target") or link.get("name")
            kind = str(link.get("type") or link.get("relation") or "related")
            label = str(link.get("label") or kind)
            summary = str(link.get("summary") or "")
            confidence = str(link.get("confidence") or "explicit")
        else:
            target_kind = "timeline_event"
            target_name = link
            kind = "related"
            label = "related"
            summary = ""
            confidence = "text_match"
        target = _resolve_node(nodes, target_kind, target_name, by_kind_name.get(target_kind, {}), item, evidence, warnings)
        if target:
            _store_edge(edges, _edge(source, target, kind, label, summary, 2, confidence, [evidence]))


def _add_named_edges(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    item: dict[str, Any],
    source: str,
    values: Any,
    target_kind: str,
    kind: str,
    by_kind_name: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
    reverse: bool = False,
) -> None:
    for index, value in enumerate(_as_list(values)):
        evidence = f"{_item_name(item)}.details.{kind}[{index}]"
        target_name = _target_name(value)
        target = _resolve_node(nodes, target_kind, target_name, by_kind_name.get(target_kind, {}), item, evidence, warnings)
        if not target:
            continue
        source_id, target_id = (target, source) if reverse else (source, target)
        summary = str(value.get("summary", "")) if isinstance(value, dict) else ""
        _store_edge(edges, _edge(source_id, target_id, kind, kind, summary, 2, "explicit", [evidence]))


def _add_inferred_events(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    chapters: Iterable[dict[str, Any]],
    sections_by_chapter: dict[Any, Iterable[dict[str, Any]]],
    by_kind_name: dict[str, dict[str, dict[str, Any]]],
) -> None:
    for chapter in chapters:
        chapter_key = chapter.get("id", chapter.get("number"))
        _add_inferred_event_group(nodes, edges, chapter, chapter, by_kind_name, f"chapter:{chapter_key}")
        for section in sections_by_chapter.get(chapter_key, []):
            context = {
                "characters": section.get("characters", chapter.get("characters")),
                "location": section.get("location", chapter.get("location")),
            }
            evidence = f"chapter:{chapter_key}:section:{section.get('id', section.get('number', '?'))}"
            _add_inferred_event_group(nodes, edges, section, context, by_kind_name, evidence)


def _add_inferred_event_group(
    nodes: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    source_data: dict[str, Any],
    context: dict[str, Any],
    by_kind_name: dict[str, dict[str, dict[str, Any]]],
    evidence: str,
) -> None:
    for index, name in enumerate(_split_values(source_data.get("must_happen"))):
        event_id = f"timeline_event:inferred:{_slug(evidence)}:{index}"
        nodes.setdefault(event_id, _synthetic_node(event_id, "timeline_event", name, "inferred", "planned", evidence))
        for character in _split_values(context.get("characters")):
            target = _existing_or_inferred_node(nodes, "character", character, by_kind_name, evidence)
            if target:
                _store_edge(edges, _edge(event_id, target, "participant", "participant", "", 1, "inferred", [evidence]))
        for location in _split_values(context.get("location")):
            target = _existing_or_inferred_node(nodes, "location", location, by_kind_name, evidence)
            if target:
                _store_edge(edges, _edge(event_id, target, "located_at", "located at", "", 1, "inferred", [evidence]))


def _resolve_node(
    nodes: dict[str, dict[str, Any]],
    kind: str,
    name: Any,
    index: dict[str, dict[str, Any]],
    source_item: dict[str, Any],
    evidence: str,
    warnings: list[str],
) -> str | None:
    clean = str(name or "").strip()
    if not clean:
        warnings.append(f"Missing {kind} target referenced by {_item_ref(source_item)} at {evidence}")
        return None
    item = index.get(_name_key(clean))
    if item:
        node_id = _node_id(item)
        nodes.setdefault(node_id, _world_item_node(item, warnings))
        return node_id
    warnings.append(f"Missing {kind} target '{clean}' referenced by {_item_ref(source_item)} at {evidence}")
    node_id = f"{kind}:{_slug(clean)}"
    nodes.setdefault(node_id, _synthetic_node(node_id, kind, clean, "missing_reference", "missing", evidence))
    return node_id


def _existing_or_inferred_node(
    nodes: dict[str, dict[str, Any]],
    kind: str,
    name: Any,
    by_kind_name: dict[str, dict[str, dict[str, Any]]],
    evidence: str,
) -> str | None:
    clean = str(name or "").strip()
    if not clean:
        return None
    item = by_kind_name.get(kind, {}).get(_name_key(clean))
    if item:
        node_id = _node_id(item)
        nodes.setdefault(node_id, _world_item_node(item, []))
        return node_id
    node_id = f"{kind}:inferred:{_slug(clean)}"
    nodes.setdefault(node_id, _synthetic_node(node_id, kind, clean, "inferred", "candidate", evidence))
    return node_id


def _synthetic_node(node_id: str, kind: str, name: str, source: str, status: str, evidence: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "source_id": None,
        "name": name,
        "label": name,
        "summary": "",
        "tags": [],
        "weight": 1,
        "status": status,
        "source": source,
        "evidence": [evidence],
    }


def _edge(
    source: str,
    target: str,
    kind: str,
    label: str,
    summary: str,
    weight: int,
    confidence: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "id": f"edge:{source}->{target}:{kind}",
        "source": source,
        "target": target,
        "kind": kind,
        "label": label,
        "summary": summary,
        "weight": weight,
        "confidence": confidence,
        "evidence": evidence,
    }


def _store_edge(edges: dict[str, dict[str, Any]], edge: dict[str, Any]) -> None:
    existing = edges.get(edge["id"])
    if not existing:
        edges[edge["id"]] = edge
        return
    existing["weight"] = max(int(existing.get("weight", 1)), int(edge.get("weight", 1)))
    existing["evidence"] = _unique([*existing.get("evidence", []), *edge.get("evidence", [])])


def _bump_weights(nodes: dict[str, dict[str, Any]], edges: Iterable[dict[str, Any]]) -> None:
    for edge in edges:
        if edge["source"] in nodes:
            nodes[edge["source"]]["weight"] = int(nodes[edge["source"]].get("weight", 1)) + 1
        if edge["target"] in nodes:
            nodes[edge["target"]]["weight"] = int(nodes[edge["target"]].get("weight", 1)) + 1


def _kind_name_index(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for item in items:
        kind = str(item.get("kind") or "").strip()
        name = _item_name(item)
        if kind and name:
            result.setdefault(kind, {})[_name_key(name)] = item
    return result


def _node_id(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "item")
    if item.get("id") not in (None, ""):
        return f"{kind}:{item.get('id')}"
    return f"{kind}:{_slug(_item_name(item))}"


def _item_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or "").strip()


def _item_ref(item: dict[str, Any]) -> str:
    return f"{item.get('kind', 'item')}:{_item_name(item) or item.get('id', '<unnamed>')}"


def _name_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _target_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("target") or value.get("name") or value.get("title") or "").strip()
    return str(value or "").strip()


def _organization_name(value: Any) -> str:
    if isinstance(value, dict):
        for key in ["organization", "organization_name", "faction", "affiliation", "target", "name", "title"]:
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return _target_name(value)


def _looks_like_organization_name(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    keywords = [
        "公爵家",
        "侯爵家",
        "伯爵家",
        "王家",
        "家族",
        "王室",
        "教会",
        "学院",
        "协会",
        "公会",
        "组织",
        "势力",
        "骑士团",
        "军团",
        "商会",
        "社交圈",
        "王国",
        "帝国",
        "共和国",
        "同盟",
        "联盟",
        "House",
        "Academy",
        "Church",
        "Guild",
        "Council",
        "Order",
        "Kingdom",
        "Empire",
        "Faction",
    ]
    return any(keyword.casefold() in text.casefold() for keyword in keywords)


def _split_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple) or isinstance(value, set):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[,，、;；\n]", str(value)) if part.strip()]


def _as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    if isinstance(value, str):
        return _split_values(value)
    return [value]


def _find_known_name(text: str, index: dict[str, dict[str, Any]], exclude: str = "") -> str:
    exclude_key = _name_key(exclude)
    for item in sorted(index.values(), key=lambda candidate: len(_item_name(candidate)), reverse=True):
        name = _item_name(item)
        if _name_key(name) != exclude_key and name in text:
            return name
    return ""


def _slug(value: Any) -> str:
    text = re.sub(r"\s+", "-", str(value or "").strip())
    text = re.sub(r"[^0-9A-Za-z_.:\-\u4e00-\u9fff]+", "", text)
    return text or "unnamed"


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


# ── 绘制层纯逻辑（无 Qt）：关系颜色/标签/方向、节点尺寸、布局坐标。供 PySide 关系图调用并可单测。──

EDGE_RELATION_LABELS = {
    "ally": "盟友", "rival": "对手", "conflict": "冲突", "relationship": "关系",
    "trust_shift": "信任变化", "relationship_delta": "关系变化", "childhood_friend": "青梅竹马",
    "same_scene": "同场", "member_of": "隶属", "leader_of": "领导", "affiliated_with": "从属",
    "causes": "导致", "caused_by": "源于", "before": "先于", "after": "后于",
    "involves": "涉及", "mentions_character": "提及", "forbidden_constraint": "禁止",
    # RG-006 语义独立的规范 kind（同义词经 normalize 归并到这些键），各自有准确中文名
    "friend": "朋友", "enemy": "敌人", "family": "家人", "lover": "恋人",
    "mentor": "导师", "student": "门徒", "related": "关联",
}

# RG-006 英文/变体关系词 → 规范 kind。normalize 先做格式归一，再查这张同义词表。
_RELATION_ALIASES = {
    # 盟友/朋友
    "friends": "friend", "best_friend": "friend", "bestfriend": "friend", "bff": "friend",
    "buddy": "friend", "companion": "friend", "comrade": "friend", "pal": "friend",
    "allies": "ally", "allied": "ally", "ally_of": "ally", "partner": "ally",
    "teammate": "ally", "colleague": "ally", "coworker": "ally", "co_worker": "ally",
    # 对手/敌人/冲突
    "enemies": "enemy", "foe": "enemy", "nemesis": "enemy", "adversary": "enemy", "antagonist": "enemy",
    "opponent": "rival", "competitor": "rival",
    "hostile": "conflict", "feud": "conflict", "hatred": "conflict",
    # 家人/恋人/情感
    "relative": "family", "kin": "family", "sibling": "family", "brother": "family",
    "sister": "family", "parent": "family", "father": "family", "mother": "family",
    "son": "family", "daughter": "family", "child": "family",
    "lovers": "lover", "couple": "lover", "spouse": "lover", "wife": "lover",
    "husband": "lover", "romance": "lover", "crush": "lover",
    "relation": "related", "connected": "related", "acquaintance": "related", "knows": "related",
    # 师徒/上下级（有向）
    "teacher": "mentor", "master": "mentor", "tutor": "mentor",
    "disciple": "student", "apprentice": "student", "pupil": "student",
    "boss": "leader_of", "superior": "leader_of", "leader": "leader_of", "leads": "leader_of",
    "commands": "leader_of",
    "subordinate": "member_of", "servant": "member_of", "follower": "member_of",
    "underling": "member_of", "member": "member_of", "belongs_to": "member_of", "memberof": "member_of",
    "affiliated": "affiliated_with",
    # 事件
    "cause": "causes", "leads_to": "causes", "results_in": "causes",
    "due_to": "caused_by", "precedes": "before", "follows": "after",
    "mentions": "mentions_character",
}

DIRECTED_EDGE_KINDS = {
    "member_of", "leader_of", "affiliated_with", "causes", "caused_by", "before", "after",
    "trust_shift", "mentor", "student",
}

EDGE_COLORS = {
    "ally": "#3f9b54", "rival": "#e56b73", "conflict": "#d23b46", "relationship": "#6fa8ff",
    "childhood_friend": "#5fb0c9", "trust_shift": "#c98a2b", "relationship_delta": "#caa23a",
    "same_scene": "#9aa8ba", "member_of": "#7b61d9", "leader_of": "#5a3fd0", "affiliated_with": "#a08ae0",
    "causes": "#9b7ede", "caused_by": "#b39ae6", "before": "#8a9bb5", "after": "#8a9bb5",
    "involves": "#76b3ff", "mentions_character": "#9fc6ff", "forbidden_constraint": "#d23b46",
    # RG-006 规范 kind 配色（与同族关系同色系）
    "friend": "#3f9b54", "enemy": "#d23b46", "family": "#6fa8ff", "lover": "#e58fb3",
    "mentor": "#5a3fd0", "student": "#a08ae0", "related": "#9aa8ba",
}
_EDGE_COLOR_DEFAULT = "#9aa8ba"

# RG-007 这些关系默认不画文字标签（靠颜色/图例表达），降低密集图重叠
_UNLABELED_EDGE_KINDS = {"same_scene"}

CHARACTER_NODE_SIZE = (84.0, 84.0)
DEFAULT_NODE_SIZE = (132.0, 48.0)


def normalize_relation_kind(kind: Any) -> str:
    """把自由文本关系类型归一：拆驼峰、小写、空格/连字符→下划线，再按同义词表归并到规范 kind。"""
    raw = str(kind or "")
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", raw)  # camelCase → camel_Case
    key = re.sub(r"[\s\-]+", "_", spaced.strip().lower())
    key = re.sub(r"_+", "_", key).strip("_")
    return _RELATION_ALIASES.get(key, key)


def edge_relation_label(kind: Any) -> str:
    key = normalize_relation_kind(kind)
    return EDGE_RELATION_LABELS.get(key, "关联")  # RG-006 未知一律中文兜底，绝不露英文


def edge_is_directed(kind: Any) -> bool:
    return normalize_relation_kind(kind) in DIRECTED_EDGE_KINDS


def edge_color_hex(kind: Any) -> str:
    return EDGE_COLORS.get(normalize_relation_kind(kind), _EDGE_COLOR_DEFAULT)


def edge_label_visible(kind: Any, confidence: Any) -> bool:
    """RG-007 是否给该边画文字标签：仅显式且非「同场」关系显示，弱推断默认隐藏以减重叠。"""
    if normalize_relation_kind(kind) in _UNLABELED_EDGE_KINDS:
        return False
    return str(confidence) == "explicit"


def assign_edge_lanes(edges: list[dict[str, Any]]) -> list[float]:
    """RG-008 同一对节点间的多条边分配不同「车道」，扇形展开避免曲线完全重合。

    返回与 ``edges`` 顺序对齐的 lane 列表：同一对节点（无向）内对称分布在主轴两侧，
    独边走中线 lane=0（直线）。lane 之后在绘制层乘以步长换算成弯曲量。
    """
    groups: dict[frozenset[str], list[int]] = {}
    for index, edge in enumerate(edges):
        pair = frozenset((str(edge.get("source")), str(edge.get("target"))))
        groups.setdefault(pair, []).append(index)
    lanes = [0.0] * len(edges)
    for indices in groups.values():
        ordered = sorted(
            indices,
            key=lambda i: (str(edges[i].get("kind")), str(edges[i].get("id")), i),
        )
        count = len(ordered)
        for rank, i in enumerate(ordered):
            lanes[i] = rank - (count - 1) / 2.0
    return lanes


def label_collides_node(
    label_box: tuple[float, float, float, float],
    node_boxes: Iterable[tuple[float, float, float, float]],
    gap: float = 0.0,
) -> bool:
    """RG-007 标签包围盒是否与任一节点包围盒重叠（重叠超过 gap 才算撞）。"""
    lx0, ly0, lx1, ly1 = label_box
    for nx0, ny0, nx1, ny1 in node_boxes:
        ox = min(lx1, nx1) - max(lx0, nx0)
        oy = min(ly1, ny1) - max(ly0, ny0)
        if ox > gap and oy > gap:
            return True
    return False


def node_size(kind: Any) -> tuple[float, float]:
    return CHARACTER_NODE_SIZE if str(kind) == "character" else DEFAULT_NODE_SIZE


def node_boundary_point(
    center: tuple[float, float], kind: Any, toward: tuple[float, float]
) -> tuple[float, float]:
    """从节点中心朝 toward 方向，落在节点边界(圆/矩形)上的点，用于连线端点贴边而非穿心。"""
    cx, cy = center
    tx, ty = toward
    dx, dy = tx - cx, ty - cy
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return (cx, cy)
    ux, uy = dx / length, dy / length
    if str(kind) == "character":
        radius = CHARACTER_NODE_SIZE[0] / 2
        return (cx + ux * radius, cy + uy * radius)
    half_w, half_h = DEFAULT_NODE_SIZE[0] / 2, DEFAULT_NODE_SIZE[1] / 2
    scale_x = half_w / abs(ux) if abs(ux) > 1e-6 else float("inf")
    scale_y = half_h / abs(uy) if abs(uy) > 1e-6 else float("inf")
    t = min(scale_x, scale_y)
    return (cx + ux * t, cy + uy * t)


def layout_character_positions(nodes: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """人物图：主角/配角左侧分层、组织右列、其它最右列；列间距足够避免重叠。"""
    characters = sorted(
        [n for n in nodes if str(n.get("kind")) == "character"],
        key=lambda n: int(n.get("weight", 1) or 1),
        reverse=True,
    )
    organizations = [n for n in nodes if str(n.get("kind")) == "organization"]
    others = [n for n in nodes if str(n.get("kind")) not in {"character", "organization"}]
    positions: dict[str, tuple[float, float]] = {}
    primary_count = min(2, len(characters)) if len(characters) > 3 else min(1, len(characters))
    primary = characters[:primary_count]
    secondary = characters[primary_count:]
    for index, node in enumerate(primary):
        positions[str(node.get("id"))] = (-300.0, (index - (len(primary) - 1) / 2) * 170.0)
    for index, node in enumerate(secondary):
        column = index % 2
        row = index // 2
        x = -40.0 + column * 220.0
        y = (row - max(0, (len(secondary) - 1) // 2) / 2) * 170.0
        positions[str(node.get("id"))] = (x, y)
    for index, node in enumerate(organizations):
        positions[str(node.get("id"))] = (450.0, (index - (len(organizations) - 1) / 2) * 180.0)
    for index, node in enumerate(others):
        positions[str(node.get("id"))] = (680.0, (index - (len(others) - 1) / 2) * 160.0)
    return positions


def layout_event_positions(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, tuple[float, float]]:
    """事件图：事件沿时间主轴；辅助节点按类型分 lane，锚定到关联事件附近并向纵向展开（避免跨锚点水平重叠）。"""
    events = [n for n in nodes if str(n.get("kind")) == "timeline_event"]
    helpers = [n for n in nodes if str(n.get("kind")) != "timeline_event"]
    event_ids = {str(n.get("id")): i for i, n in enumerate(events)}
    positions: dict[str, tuple[float, float]] = {}
    event_gap = 320.0
    for index, node in enumerate(events):
        positions[str(node.get("id"))] = (index * event_gap, 0.0)
    helper_lanes = {
        "character": -230.0, "organization": -420.0, "location": 230.0,
        "foreshadowing": 420.0, "rule": 610.0, "forbidden": 800.0,
    }
    connected: dict[str, list[int]] = {}
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source in event_ids and target not in event_ids:
            connected.setdefault(target, []).append(event_ids[source])
        if target in event_ids and source not in event_ids:
            connected.setdefault(source, []).append(event_ids[target])
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    loose: list[dict[str, Any]] = []
    for node in helpers:
        node_id = str(node.get("id"))
        anchors = connected.get(node_id, [])
        if not anchors:
            loose.append(node)
            continue
        anchor = round(sum(anchors) / len(anchors))
        grouped.setdefault((str(node.get("kind")), anchor), []).append(node)
    # 关键修复：每组只用窄 2 列(±75，远小于 event_gap/2=160)，多了向纵深堆行，杜绝跨相邻锚点水平重叠。
    for (kind, anchor), group in grouped.items():
        lane_y = helper_lanes.get(kind, 990.0)
        direction = -1.0 if lane_y < 0 else 1.0
        for index, node in enumerate(group):
            column = index % 2
            row = index // 2
            offset_x = (column - 0.5) * 150.0
            positions[str(node.get("id"))] = (anchor * event_gap + offset_x, lane_y + direction * row * 95.0)
    # 无连边的游离辅助节点：放到主轴下方独立带，避免与事件 lane 交叠。
    base_y = 1150.0
    for index, node in enumerate(loose):
        column = index % 6
        row = index // 6
        positions[str(node.get("id"))] = (column * 180.0, base_y + row * 110.0)
    return positions


def legend_entries() -> list[dict[str, Any]]:
    """RG-005 图例条目：颜色=关系族、形状=节点类型、线型/箭头=方向与置信度。

    每条目含 ``category``(relation/shape/style)、``label``、``color``(hex 或 None)，
    形状条目额外含 ``shape``，弱推断条目含 ``dashed``。供 UI 渲染色块、供测试断言。
    """
    return [
        {"category": "relation", "label": "盟友", "color": EDGE_COLORS["ally"]},
        {"category": "relation", "label": "对手/冲突", "color": EDGE_COLORS["rival"]},
        {"category": "relation", "label": "隶属/从属", "color": EDGE_COLORS["member_of"]},
        {"category": "relation", "label": "领导", "color": EDGE_COLORS["leader_of"]},
        {"category": "relation", "label": "关系/情感", "color": EDGE_COLORS["relationship"]},
        {"category": "relation", "label": "信任变化", "color": EDGE_COLORS["trust_shift"]},
        {"category": "relation", "label": "因果", "color": EDGE_COLORS["causes"]},
        {"category": "relation", "label": "同场/出场", "color": EDGE_COLORS["same_scene"]},
        {"category": "relation", "label": "时间先后", "color": EDGE_COLORS["before"]},
        {"category": "shape", "label": "角色（圆形）", "shape": "ellipse", "color": None},
        {"category": "shape", "label": "事件/设定（方形）", "shape": "rect", "color": None},
        {"category": "style", "label": "箭头＝有向关系（指向被指方）", "color": None},
        {"category": "style", "label": "虚线＝弱推断关系", "color": None, "dashed": True},
    ]


def neighborhood_subgraph(
    graph: dict[str, Any], node_id: Any, depth: int = 1
) -> dict[str, Any]:
    """RG-005 大图分段：只保留 ``node_id`` 及其 ``depth`` 跳邻域内的节点与它们之间的边。

    其余图字段（warnings 等）原样保留。``node_id`` 不在图中时返回空节点/空边的子图。
    """
    nodes = list(graph.get("nodes", []))
    edges = list(graph.get("edges", []))
    target = str(node_id)
    keep = {target}
    frontier = {target}
    for _ in range(max(0, int(depth))):
        nxt: set[str] = set()
        for edge in edges:
            source = str(edge.get("source"))
            sink = str(edge.get("target"))
            if source in frontier:
                nxt.add(sink)
            if sink in frontier:
                nxt.add(source)
        frontier = nxt - keep
        keep |= nxt
        if not frontier:
            break
    result = dict(graph)
    result["nodes"] = [n for n in nodes if str(n.get("id")) in keep]
    result["edges"] = [
        e for e in edges
        if str(e.get("source")) in keep and str(e.get("target")) in keep
    ]
    return result


__all__ = [
    "build_character_graph", "build_event_graph",
    "edge_relation_label", "edge_is_directed", "edge_color_hex", "node_size", "node_boundary_point",
    "normalize_relation_kind", "edge_label_visible", "label_collides_node", "assign_edge_lanes",
    "layout_character_positions", "layout_event_positions",
    "legend_entries", "neighborhood_subgraph",
]
