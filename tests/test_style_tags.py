import json
import unittest

from my_ai_novel.prompts import build_project_writing_constraints
from my_ai_novel.style_tags import build_prompt_modules, normalize_tag_ids
from my_ai_novel.world_modules import (
    character_basic_fields_from_details,
    dump_details,
    update_character_basic_fields,
)


class StyleTagTests(unittest.TestCase):
    def test_normalize_tag_ids_accepts_json_and_csv(self) -> None:
        self.assertEqual(normalize_tag_ids('["fantasy", "mystery"]'), ["fantasy", "mystery"])
        self.assertEqual(normalize_tag_ids("skill_system,ts"), ["skill_system", "ts"])

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
