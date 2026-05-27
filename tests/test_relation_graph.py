import unittest

from my_ai_novel.relation_graph import build_character_graph, build_event_graph


def edge_exists(graph, source, target, kind):
    return any(edge["source"] == source and edge["target"] == target and edge["kind"] == kind for edge in graph["edges"])


class RelationGraphTests(unittest.TestCase):
    def test_character_graph_reads_explicit_dict_and_string_relationships(self) -> None:
        world_items = [
            {
                "id": 1,
                "kind": "character",
                "name": "Alice",
                "summary": "Investigator",
                "details": {
                    "role_flags": {"protagonist": True},
                    "relationships": [
                        {"target": "Bob", "type": "ally", "label": "Partner", "summary": "Works with Bob"},
                        "Keeps a professional rivalry with Cara",
                    ],
                },
                "tags": "lead",
                "status": "active",
            },
            {"id": 2, "kind": "character", "name": "Bob", "summary": "", "details": {}, "tags": "", "status": ""},
            {"id": 3, "kind": "character", "name": "Cara", "summary": "", "details": {}, "tags": "", "status": ""},
        ]

        graph = build_character_graph(world_items)

        self.assertEqual(len(graph["nodes"]), 3)
        self.assertTrue(edge_exists(graph, "character:1", "character:2", "ally"))
        self.assertTrue(edge_exists(graph, "character:1", "character:3", "relationship"))
        string_edge = next(edge for edge in graph["edges"] if edge["target"] == "character:3")
        self.assertEqual(string_edge["confidence"], "text_match")
        self.assertEqual(graph["warnings"], [])

    def test_character_graph_reads_chapter_memory_relationship_delta(self) -> None:
        world_items = [
            {
                "id": 1,
                "kind": "character",
                "name": "Alice",
                "details": {
                    "chapter_memory": [
                        {
                            "summary": "Chapter 2 aftermath",
                            "relationship_delta": {"target": "Bob", "type": "trust_shift", "change": "Trust improves"},
                        }
                    ]
                },
            },
            {"id": 2, "kind": "character", "name": "Bob", "details": {}},
        ]

        graph = build_character_graph(world_items)

        self.assertTrue(edge_exists(graph, "character:1", "character:2", "trust_shift"))
        edge = next(edge for edge in graph["edges"] if edge["kind"] == "trust_shift")
        self.assertIn("chapter_memory", edge["evidence"][0])

    def test_character_graph_includes_organizations_but_not_locations(self) -> None:
        world_items = [
            {
                "id": 1,
                "kind": "character",
                "name": "Alice",
                "details": {"affiliation": "Clock Academy"},
            },
            {
                "id": 2,
                "kind": "organization",
                "name": "Clock Academy",
                "details": {"members": ["Alice"], "leader": "Bob"},
            },
            {"id": 3, "kind": "character", "name": "Bob", "details": {}},
            {"id": 4, "kind": "location", "name": "Old Hall", "details": {}},
        ]

        graph = build_character_graph(world_items)

        node_kinds = {node["kind"] for node in graph["nodes"]}
        self.assertIn("character", node_kinds)
        self.assertIn("organization", node_kinds)
        self.assertNotIn("location", node_kinds)
        self.assertTrue(edge_exists(graph, "character:1", "organization:2", "member_of"))
        self.assertTrue(edge_exists(graph, "character:3", "organization:2", "leader_of"))
        self.assertTrue(
            all(
                node_id.split(":", 1)[0] in {"character", "organization"}
                for edge in graph["edges"]
                for node_id in [edge["source"], edge["target"]]
            )
        )

    def test_character_graph_reads_organization_from_character_modules(self) -> None:
        world_items = [
            {
                "id": 1,
                "kind": "character",
                "name": "Alice",
                "details": {"modules": {"affiliation": {"organization": "Student Council", "role": "auditor"}}},
            },
            {"id": 2, "kind": "organization", "name": "Student Council", "details": {}},
        ]

        graph = build_character_graph(world_items)

        self.assertTrue(edge_exists(graph, "character:1", "organization:2", "member_of"))

    def test_character_relationships_can_target_organizations(self) -> None:
        world_items = [
            {
                "id": 1,
                "kind": "character",
                "name": "Elena",
                "details": {
                    "relationships": [
                        {"name": "Noah", "type": "ally", "label": "Childhood friend"},
                        {"name": "Clock Academy", "relation": "school pressure", "description": "Watched by academy rules"},
                        {
                            "name": "王国教会",
                            "relation": "潜在监视者与预言权威",
                            "description": "掌管星图系统并解释预言。",
                        },
                    ]
                },
            },
            {"id": 2, "kind": "character", "name": "Noah", "details": {}},
            {"id": 3, "kind": "organization", "name": "Clock Academy", "details": {}},
        ]

        graph = build_character_graph(world_items)

        self.assertTrue(edge_exists(graph, "character:1", "character:2", "ally"))
        self.assertTrue(edge_exists(graph, "character:1", "organization:3", "affiliated_with"))
        self.assertTrue(edge_exists(graph, "character:1", "organization:王国教会", "affiliated_with"))
        church_node = next(node for node in graph["nodes"] if node["id"] == "organization:王国教会")
        self.assertEqual(church_node["source"], "missing_reference")
        academy_edge = next(edge for edge in graph["edges"] if edge["target"] == "organization:3")
        self.assertEqual(academy_edge["label"], "school pressure")

    def test_event_graph_reads_causal_foreshadowing_and_participant_edges(self) -> None:
        world_items = [
            {
                "id": 10,
                "kind": "timeline_event",
                "name": "Old Fire",
                "details": {"causes": ["Night Escape"], "related_foreshadowing": ["Ash Mark"]},
            },
            {
                "id": 11,
                "kind": "timeline_event",
                "name": "Night Escape",
                "details": {
                    "caused_by": ["Old Fire"],
                    "participants": ["Alice"],
                    "location": "Harbor",
                    "related_rules": ["Curfew"],
                    "graph_links": [{"target_kind": "foreshadowing", "target": "Ash Mark", "type": "pays_off"}],
                },
            },
            {"id": 1, "kind": "character", "name": "Alice", "details": {}},
            {"id": 20, "kind": "location", "name": "Harbor", "details": {}},
            {"id": 30, "kind": "foreshadowing", "name": "Ash Mark", "details": {}},
            {"id": 40, "kind": "rule", "name": "Curfew", "details": {}},
        ]

        graph = build_event_graph(world_items)

        self.assertTrue(edge_exists(graph, "timeline_event:10", "timeline_event:11", "causes"))
        self.assertTrue(edge_exists(graph, "timeline_event:10", "timeline_event:11", "caused_by"))
        self.assertTrue(edge_exists(graph, "timeline_event:11", "character:1", "participant"))
        self.assertTrue(edge_exists(graph, "timeline_event:11", "location:20", "located_at"))
        self.assertTrue(edge_exists(graph, "timeline_event:11", "foreshadowing:30", "pays_off"))
        self.assertTrue(edge_exists(graph, "timeline_event:10", "foreshadowing:30", "foreshadow"))
        self.assertTrue(edge_exists(graph, "timeline_event:11", "rule:40", "rule_constraint"))
        self.assertEqual(graph["warnings"], [])

    def test_event_graph_exposes_ordering_and_sorts_real_events(self) -> None:
        world_items = [
            {
                "id": 30,
                "kind": "timeline_event",
                "name": "Act Two Opening",
                "details": {"phase": "act-2", "sequence": 1, "time_text": "Dawn", "status": "planned"},
            },
            {
                "id": 10,
                "kind": "timeline_event",
                "name": "Act One Late",
                "details": {"phase": "act-1", "sequence": 2, "time_text": "Night"},
                "status": "draft",
            },
            {
                "id": 20,
                "kind": "timeline_event",
                "name": "Act One Early",
                "details": {
                    "phase": "act-1",
                    "sequence": 1,
                    "time_text": "Morning",
                    "status": "locked",
                    "causes": ["Missing Aftermath"],
                },
            },
        ]
        chapters = [{"id": 100, "must_happen": ["Inferred Beat"]}]

        graph = build_event_graph(world_items, chapters, include_inferred=True)

        self.assertEqual(
            [node["id"] for node in graph["nodes"][:3]],
            ["timeline_event:20", "timeline_event:10", "timeline_event:30"],
        )
        early = next(node for node in graph["nodes"] if node["id"] == "timeline_event:20")
        self.assertEqual(
            early["ordering"],
            {
                "time_text": "Morning",
                "sequence": 1,
                "phase": "act-1",
                "status": "locked",
                "sort_key": ["act-1", 1, "Morning"],
            },
        )
        late = next(node for node in graph["nodes"] if node["id"] == "timeline_event:10")
        self.assertEqual(late["ordering"]["status"], "draft")
        self.assertTrue(any(node["id"] == "timeline_event:Missing-Aftermath" for node in graph["nodes"][3:]))
        self.assertTrue(any(node["source"] == "inferred" and node["kind"] == "timeline_event" for node in graph["nodes"][3:]))

    def test_missing_event_targets_emit_warnings_without_raising(self) -> None:
        graph = build_event_graph(
            [
                {
                    "id": 10,
                    "kind": "timeline_event",
                    "name": "Old Fire",
                    "details": {"causes": ["Unknown Escape"]},
                }
            ]
        )

        self.assertTrue(graph["warnings"])
        self.assertTrue(edge_exists(graph, "timeline_event:10", "timeline_event:Unknown-Escape", "causes"))
        missing_node = next(node for node in graph["nodes"] if node["id"] == "timeline_event:Unknown-Escape")
        self.assertEqual(missing_node["source"], "missing_reference")

    def test_inferred_edges_are_controlled_by_flag(self) -> None:
        world_items = [
            {"id": 1, "kind": "character", "name": "Alice", "details": {}},
            {"id": 2, "kind": "character", "name": "Bob", "details": {}},
            {"id": 20, "kind": "location", "name": "Harbor", "details": {}},
        ]
        chapters = [
            {"id": 100, "number": 1, "characters": ["Alice", "Bob"], "location": "Harbor", "must_happen": ["Alarm Rings"]}
        ]
        sections = {100: [{"number": 1, "characters": ["Alice", "Bob"], "location": "Harbor", "must_happen": ["Boat Leaves"]}]}

        character_without = build_character_graph(world_items, chapters, sections, include_inferred=False)
        character_with = build_character_graph(world_items, chapters, sections, include_inferred=True)
        event_without = build_event_graph(world_items, chapters, sections, include_inferred=False)
        event_with = build_event_graph(world_items, chapters, sections, include_inferred=True)

        self.assertFalse(any(edge["kind"] == "same_scene" for edge in character_without["edges"]))
        self.assertTrue(edge_exists(character_with, "character:1", "character:2", "same_scene"))
        self.assertFalse(any(edge["confidence"] == "inferred" for edge in event_without["edges"]))
        self.assertTrue(any(node["source"] == "inferred" and node["kind"] == "timeline_event" for node in event_with["nodes"]))
        self.assertTrue(any(edge["confidence"] == "inferred" and edge["kind"] == "participant" for edge in event_with["edges"]))


if __name__ == "__main__":
    unittest.main()
