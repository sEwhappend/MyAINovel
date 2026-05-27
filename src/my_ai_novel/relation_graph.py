from __future__ import annotations

import json
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
                _store_edge(edges, _edge(left, right, "same_scene", "same scene", "", 1, "inferred", [evidence]))


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


__all__ = ["build_character_graph", "build_event_graph"]
