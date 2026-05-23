import json
import unittest

from my_ai_novel.prompts import build_project_writing_constraints
from my_ai_novel.style_tags import (
    build_prompt_modules,
    list_style_tag_catalog,
    normalize_tag_ids,
    search_style_tags,
)
from my_ai_novel.world_modules import (
    character_basic_fields_from_details,
    dump_details,
    update_character_basic_fields,
)


class StyleTagTests(unittest.TestCase):
    def test_normalize_tag_ids_accepts_json_and_csv(self) -> None:
        self.assertEqual(normalize_tag_ids('["fantasy", "mystery"]'), ["fantasy", "mystery"])
        self.assertEqual(normalize_tag_ids("skill_system,ts"), ["skill_system", "ts"])
        self.assertEqual(normalize_tag_ids("skill_system，ts"), ["skill_system", "ts"])

    def test_catalog_covers_generation_categories_and_metadata(self) -> None:
        catalog = list_style_tag_catalog()
        self.assertEqual(
            set(catalog),
            {
                "genre_tags",
                "setting_tags",
                "character_tags",
                "structure_tags",
                "style_tags",
                "forbidden_tags",
            },
        )
        self.assertGreaterEqual(sum(len(tags) for tags in catalog.values()), 100)

        for category, tags in catalog.items():
            self.assertGreater(len(tags), 0, category)
            for tag in tags:
                self.assertIsInstance(tag["id"], str)
                self.assertIsInstance(tag["label"], str)
                self.assertIsInstance(tag["style_rule"], str)
                self.assertIsInstance(tag["usage_rule"], str)
                self.assertIn("requires_memory", tag)
                self.assertIn("memory_kinds", tag)

    def test_catalog_has_no_duplicate_ids_or_labels(self) -> None:
        catalog = list_style_tag_catalog()
        seen_ids: set[str] = set()
        seen_labels: set[str] = set()
        duplicate_ids: list[str] = []
        duplicate_labels: list[str] = []
        for tags in catalog.values():
            for tag in tags:
                tag_id = tag["id"]
                label = tag["label"]
                if tag_id in seen_ids:
                    duplicate_ids.append(tag_id)
                if label in seen_labels:
                    duplicate_labels.append(label)
                seen_ids.add(tag_id)
                seen_labels.add(label)

        self.assertEqual(duplicate_ids, [])
        self.assertEqual(duplicate_labels, [])

    def test_stateful_tags_are_identified_by_requires_memory(self) -> None:
        modules = build_prompt_modules(
            {
                "selected_setting_tags": json.dumps(["level_system", "time_loop"], ensure_ascii=False),
                "selected_character_tags": ["relationship_slow_burn", "identity_secret"],
                "selected_structure_tags": ["bbs", "foreshadowing_heavy"],
                "selected_forbidden_tags": ["no_relationship_reset"],
            }
        )

        selected = {tag["id"]: tag for tag in modules["selected_tags"]}
        self.assertTrue(selected["level_system"]["requires_memory"])
        self.assertTrue(selected["time_loop"]["requires_memory"])
        self.assertTrue(selected["relationship_slow_burn"]["requires_memory"])
        self.assertTrue(selected["identity_secret"]["requires_memory"])
        self.assertTrue(selected["bbs"]["requires_memory"])
        self.assertTrue(selected["foreshadowing_heavy"]["requires_memory"])
        self.assertTrue(selected["no_relationship_reset"]["requires_memory"])
        self.assertIn("character", selected["level_system"]["memory_kinds"])
        self.assertTrue(any("modules.level_system" in rule for rule in modules["continuity_rules"]))
        self.assertTrue(any("modules.relationship_state" in rule for rule in modules["continuity_rules"]))

    def test_prompt_modules_include_selected_tags_and_quote_style(self) -> None:
        modules = build_prompt_modules(
            {
                "selected_setting_tags": json.dumps(["level_system"], ensure_ascii=False),
                "selected_structure_tags": json.dumps(["bbs"], ensure_ascii=False),
                "dialogue_quote_style": "corner_quotes",
            }
        )

        selected_ids = [tag["id"] for tag in modules["selected_tags"]]
        self.assertEqual(selected_ids, ["level_system", "bbs"])
        self.assertIn("「」", modules["dialogue_quote_style"]["rule"])
        self.assertTrue(any("等级变化" in rule for rule in modules["continuity_rules"]))

    def test_existing_build_prompt_modules_shape_is_compatible(self) -> None:
        modules = build_prompt_modules(
            {
                "selected_genre_tags": ["fantasy"],
                "selected_setting_tags": ["skill_system"],
                "selected_structure_tags": ["slow_burn"],
                "selected_style_tags": ["jp_light_novel"],
            }
        )

        self.assertEqual(
            set(modules),
            {"selected_tags", "dialogue_quote_style", "style_rules", "continuity_rules"},
        )
        self.assertEqual(
            set(modules["selected_tags"][0]),
            {
                "category",
                "id",
                "label",
                "requires_memory",
                "memory_kinds",
                "style_rule",
                "usage_rule",
            },
        )

    def test_search_style_tags_filters_by_keyword_and_category(self) -> None:
        matches = search_style_tags("等级", category="setting_tags")
        self.assertIn("level_system", {tag["id"] for tag in matches})
        self.assertTrue(all(tag["category"] == "setting_tags" for tag in matches))

    def test_project_writing_constraints_embed_prompt_modules(self) -> None:
        constraints = build_project_writing_constraints(
            {
                "title": "模块化提示词项目",
                "selected_setting_tags": ["skill_system"],
                "dialogue_quote_style": "corner_quotes",
            }
        )

        self.assertIn("prompt_modules", constraints)
        self.assertEqual(json.loads(constraints["selected_setting_tags"]), ["skill_system"])
        self.assertEqual(
            constraints["prompt_modules"]["selected_tags"][0]["id"],
            "skill_system",
        )

    def test_character_basic_fields_preserve_modules_json(self) -> None:
        details = {
            "modules": {"level_system": {"level": 5}},
            "identity": "旧身份",
        }
        updated = update_character_basic_fields(
            details,
            identity="冒险者",
            personality="谨慎",
            motivation="寻找真相",
            speech_style="短句",
            role_flags={"protagonist": True, "ensemble_main": True},
        )

        self.assertEqual(updated["modules"]["level_system"]["level"], 5)
        fields = character_basic_fields_from_details(dump_details(updated))
        self.assertEqual(fields["identity"], "冒险者")
        self.assertTrue(fields["role_flags"]["protagonist"])
        self.assertTrue(fields["role_flags"]["ensemble_main"])


if __name__ == "__main__":
    unittest.main()
