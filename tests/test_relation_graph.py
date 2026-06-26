import unittest
from itertools import combinations

from my_ai_novel.relation_graph import (
    build_character_graph,
    build_event_graph,
    edge_color_hex,
    edge_is_directed,
    assign_edge_lanes,
    edge_label_visible,
    edge_relation_label,
    label_collides_node,
    layout_character_positions,
    layout_event_positions,
    legend_entries,
    neighborhood_subgraph,
    node_boundary_point,
    node_size,
    normalize_relation_kind,
)


def _node(node_id, kind, weight=1):
    return {"id": node_id, "kind": kind, "weight": weight, "name": str(node_id)}


def _no_node_overlap(test, positions, nodes, gap=1.0):
    boxes = {}
    for n in nodes:
        x, y = positions[str(n["id"])]
        w, h = node_size(str(n["kind"]))
        boxes[str(n["id"])] = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    for a, b in combinations([str(n["id"]) for n in nodes], 2):
        ax0, ay0, ax1, ay1 = boxes[a]
        bx0, by0, bx1, by1 = boxes[b]
        ox = min(ax1, bx1) - max(ax0, bx0)
        oy = min(ay1, by1) - max(ay0, by0)
        test.assertFalse(ox > gap and oy > gap, f"node {a} overlaps {b} (ox={ox:.0f}, oy={oy:.0f})")


class RelationGraphDrawHelpersTests(unittest.TestCase):
    def test_edge_relation_label_known_and_fallback(self) -> None:
        self.assertEqual(edge_relation_label("member_of"), "隶属")
        self.assertEqual(edge_relation_label("ally"), "盟友")
        self.assertEqual(edge_relation_label("causes"), "导致")
        self.assertTrue(edge_relation_label("totally_unknown"))  # 不为空

    def test_edge_is_directed(self) -> None:
        for k in ("member_of", "leader_of", "affiliated_with", "causes", "caused_by", "before", "after", "trust_shift"):
            self.assertTrue(edge_is_directed(k), k)
        for k in ("ally", "rival", "same_scene", "relationship", "conflict"):
            self.assertFalse(edge_is_directed(k), k)

    def test_edge_color_distinguishes_key_kinds(self) -> None:
        ally = edge_color_hex("ally")
        self.assertNotEqual(ally, edge_color_hex("rival"))
        self.assertNotEqual(ally, edge_color_hex("member_of"))
        self.assertNotEqual(ally, edge_color_hex("causes"))
        self.assertNotEqual(edge_color_hex("member_of"), edge_color_hex("causes"))
        self.assertNotEqual(edge_color_hex("rival"), edge_color_hex("__unknown__"))  # rival 不落默认灰

    def test_node_boundary_point(self) -> None:
        # 圆形角色：朝右 → 圆周半径 42
        x, y = node_boundary_point((0.0, 0.0), "character", (100.0, 0.0))
        self.assertAlmostEqual(x, 42.0, delta=0.5)
        self.assertAlmostEqual(y, 0.0, delta=0.5)
        # 矩形：朝右 → 半宽 66；朝上 → 半高 24
        self.assertAlmostEqual(node_boundary_point((0.0, 0.0), "location", (100.0, 0.0))[0], 66.0, delta=0.5)
        self.assertAlmostEqual(node_boundary_point((0.0, 0.0), "location", (0.0, 100.0))[1], 24.0, delta=0.5)
        # 退化：同点返回中心
        self.assertEqual(node_boundary_point((5.0, 5.0), "character", (5.0, 5.0)), (5.0, 5.0))

    def test_character_layout_no_overlap(self) -> None:
        nodes = [_node(f"character:{i}", "character", weight=10 - i) for i in range(8)]
        nodes += [_node(f"organization:{i}", "organization") for i in range(4)]
        nodes += [_node(f"location:{i}", "location") for i in range(3)]
        _no_node_overlap(self, layout_character_positions(nodes), nodes)

    def test_event_layout_no_overlap_across_anchors(self) -> None:
        events = [_node(f"timeline_event:{i}", "timeline_event") for i in range(5)]
        helpers = [_node(f"character:{i}", "character") for i in range(10)]
        nodes = events + helpers
        # 每个 helper 连到相邻事件，触发跨锚点同 lane 重叠场景
        edges = [{"source": f"timeline_event:{i % 5}", "target": f"character:{i}", "kind": "involves"} for i in range(10)]
        _no_node_overlap(self, layout_event_positions(nodes, edges), nodes)

    def test_normalize_relation_kind(self) -> None:
        # 大小写/空格/连字符/驼峰统一
        self.assertEqual(normalize_relation_kind("Best Friend"), normalize_relation_kind("best-friend"))
        self.assertEqual(normalize_relation_kind("memberOf"), "member_of")
        self.assertEqual(normalize_relation_kind("  ALLY  "), "ally")
        # 同义词归并到规范 kind
        self.assertEqual(normalize_relation_kind("foe"), normalize_relation_kind("enemy"))
        self.assertEqual(normalize_relation_kind("teacher"), normalize_relation_kind("mentor"))

    def test_edge_relation_label_translates_english_and_never_leaks_english(self) -> None:
        # 常见英文关系词 → 中文
        for raw in ["friend", "enemy", "family", "lover", "mentor", "rival", "ally", "related"]:
            label = edge_relation_label(raw)
            self.assertFalse(any("a" <= ch.lower() <= "z" for ch in label), f"{raw}->{label} 含英文")
        # 完全未知 kind → 中文兜底「关联」，不再露原英文
        self.assertEqual(edge_relation_label("__totally_unknown_xyz__"), "关联")
        self.assertEqual(edge_relation_label("frobnicate"), "关联")

    def test_edge_color_and_direction_follow_normalized_kind(self) -> None:
        # 同义词复用合理配色，且不落默认灰
        self.assertEqual(edge_color_hex("friend"), edge_color_hex("Friend"))
        self.assertNotEqual(edge_color_hex("enemy"), edge_color_hex("__unknown__"))
        # 师徒有向
        self.assertTrue(edge_is_directed("mentor"))
        self.assertTrue(edge_is_directed("memberOf"))
        self.assertFalse(edge_is_directed("friend"))

    def test_edge_label_visible(self) -> None:
        # 显式且非同场 → 显示
        self.assertTrue(edge_label_visible("ally", "explicit"))
        # 同场 → 永不显示（靠颜色/图例）
        self.assertFalse(edge_label_visible("same_scene", "explicit"))
        # 弱推断 → 默认不显示，降低重叠
        self.assertFalse(edge_label_visible("relationship", "inferred"))
        self.assertFalse(edge_label_visible("relationship", "text_match"))

    def test_assign_edge_lanes_separates_parallel_edges(self) -> None:
        edges = [
            {"source": "a", "target": "b", "kind": "ally", "id": "e1"},
            {"source": "a", "target": "b", "kind": "mentor", "id": "e2"},  # 同对、不同关系
            {"source": "b", "target": "a", "kind": "enemy", "id": "e3"},   # 反向，仍是同一对节点
            {"source": "c", "target": "d", "kind": "ally", "id": "e4"},    # 独边
        ]
        lanes = assign_edge_lanes(edges)
        self.assertEqual(len(lanes), len(edges))  # 与输入对齐
        ab = [lanes[0], lanes[1], lanes[2]]
        self.assertEqual(len(set(ab)), 3)          # 同一对的三条边 lane 互不相同 → 不重合
        self.assertAlmostEqual(sum(ab), 0.0)       # 对称分布在主轴两侧
        self.assertEqual(lanes[3], 0.0)            # 独边走中线（直线）

    def test_label_collides_node(self) -> None:
        node_boxes = [(0.0, 0.0, 100.0, 50.0)]
        # 标签盒落在节点内 → 撞
        self.assertTrue(label_collides_node((10.0, 10.0, 40.0, 30.0), node_boxes))
        # 标签盒在远处 → 不撞
        self.assertFalse(label_collides_node((200.0, 200.0, 240.0, 220.0), node_boxes))
        # 仅贴边（间隙阈值内不算撞）
        self.assertFalse(label_collides_node((100.0, 0.0, 130.0, 20.0), node_boxes, gap=1.0))

    def test_legend_entries(self) -> None:
        entries = legend_entries()
        self.assertTrue(entries)
        # 关系条目都带合法十六进制颜色
        relations = [e for e in entries if e["category"] == "relation"]
        self.assertGreaterEqual(len(relations), 6)
        for e in relations:
            self.assertTrue(str(e["color"]).startswith("#") and len(e["color"]) == 7)
            self.assertTrue(e["label"])
        # 盟友与对手颜色可辨（同 RG-001 配色）
        ally = next(e for e in relations if e["label"] == "盟友")
        rival = next(e for e in relations if "对手" in e["label"])
        self.assertEqual(ally["color"], edge_color_hex("ally"))
        self.assertNotEqual(ally["color"], rival["color"])
        # 含形状与线型说明
        cats = {e["category"] for e in entries}
        self.assertIn("shape", cats)
        self.assertIn("style", cats)

    def test_neighborhood_subgraph(self) -> None:
        graph = {
            "nodes": [_node(f"character:{i}", "character") for i in range(4)],
            "edges": [
                {"source": "character:0", "target": "character:1", "kind": "ally"},
                {"source": "character:1", "target": "character:2", "kind": "rival"},
                {"source": "character:2", "target": "character:3", "kind": "ally"},
            ],
            "warnings": ["保留"],
        }
        # depth=1：0 的邻域 = {0,1}，只保留两者之间的边
        sub = neighborhood_subgraph(graph, "character:0", depth=1)
        self.assertEqual({str(n["id"]) for n in sub["nodes"]}, {"character:0", "character:1"})
        self.assertEqual(len(sub["edges"]), 1)
        self.assertEqual(sub["warnings"], ["保留"])  # 其余字段原样保留
        # depth=2：扩到 {0,1,2}
        sub2 = neighborhood_subgraph(graph, "character:0", depth=2)
        self.assertEqual({str(n["id"]) for n in sub2["nodes"]}, {"character:0", "character:1", "character:2"})
        # 不存在的节点 → 空子图
        empty = neighborhood_subgraph(graph, "character:99", depth=1)
        self.assertEqual(empty["nodes"], [])
        self.assertEqual(empty["edges"], [])


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
