from __future__ import annotations

import json
from typing import Any


CHARACTER_BASIC_FIELDS = ("identity", "personality", "motivation", "speech_style")
CHARACTER_ROLE_FLAGS = ("protagonist", "pov", "ensemble_main", "supporting")
SPEECH_STYLE_PROFILE_FIELDS = (
    "sentence_length",
    "formality",
    "tone",
    "addressing_habits",
    "catchphrases",
    "taboo_words",
    "emotion_leak",
    "information_style",
    "conflict_style",
    "dialogue_examples",
    "anti_voice_rules",
)
SPEECH_STYLE_PROFILE_LIST_FIELDS = {
    "tone",
    "addressing_habits",
    "catchphrases",
    "taboo_words",
    "dialogue_examples",
    "anti_voice_rules",
}


def load_details(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def dump_details(details: dict[str, Any]) -> str:
    return json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True)


def default_speech_style_profile() -> dict[str, Any]:
    return {
        field: [] if field in SPEECH_STYLE_PROFILE_LIST_FIELDS else ""
        for field in SPEECH_STYLE_PROFILE_FIELDS
    }


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def normalize_speech_style_profile(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    profile = default_speech_style_profile()
    for field in SPEECH_STYLE_PROFILE_FIELDS:
        if field in SPEECH_STYLE_PROFILE_LIST_FIELDS:
            profile[field] = _text_list(raw.get(field))
        else:
            profile[field] = str(raw.get(field, "") or "").strip()
    for key, extra_value in raw.items():
        if key not in profile:
            profile[key] = extra_value
    return profile


def _speech_style_summary(value: Any, profile: dict[str, Any] | None = None) -> str:
    if isinstance(value, dict):
        for key in ("summary", "description", "style", "voice", "speech_style"):
            text = str(value.get(key, "") or "").strip()
            if text:
                return text
        parts: list[str] = []
        for key in ("sentence_length", "formality", "emotion_leak", "information_style", "conflict_style"):
            text = str(value.get(key, "") or "").strip()
            if text:
                parts.append(text)
        for key in ("tone", "catchphrases"):
            parts.extend(_text_list(value.get(key)))
        return "；".join(parts[:4])
    if isinstance(value, list):
        return "；".join(_text_list(value))
    text = str(value or "").strip()
    if text:
        return text
    if profile:
        parts = []
        for key in ("sentence_length", "formality", "emotion_leak", "information_style", "conflict_style"):
            item = str(profile.get(key, "") or "").strip()
            if item:
                parts.append(item)
        for key in ("tone", "catchphrases"):
            parts.extend(_text_list(profile.get(key)))
        return "；".join(parts[:4])
    return ""


def normalize_character_card_details(details: Any) -> dict[str, Any]:
    data = load_details(details)
    modules = data.get("modules")
    if not isinstance(modules, dict):
        data["modules"] = {}
    role_flags = data.get("role_flags")
    if not isinstance(role_flags, dict):
        data["role_flags"] = {}
    for flag in CHARACTER_ROLE_FLAGS:
        data["role_flags"][flag] = bool(data["role_flags"].get(flag, False))
    speech_style_value = data.get("speech_style")
    profile_value = data.get("speech_style_profile")
    if isinstance(speech_style_value, dict):
        profile_source = {**speech_style_value, **(profile_value if isinstance(profile_value, dict) else {})}
    else:
        profile_source = profile_value if isinstance(profile_value, dict) else {}
    profile = normalize_speech_style_profile(profile_source)
    data["speech_style"] = _speech_style_summary(speech_style_value, profile)
    data["speech_style_profile"] = profile
    return data


def normalize_character_details(details: Any) -> dict[str, Any]:
    return normalize_character_card_details(details)


def character_basic_fields_from_details(details: Any) -> dict[str, Any]:
    data = normalize_character_details(details)
    result = {field: str(data.get(field, "") or "") for field in CHARACTER_BASIC_FIELDS}
    role_flags = data.get("role_flags", {})
    result["role_flags"] = {
        flag: bool(role_flags.get(flag, False))
        for flag in CHARACTER_ROLE_FLAGS
    }
    return result


def update_character_basic_fields(
    details: Any,
    identity: Any = "",
    personality: Any = "",
    motivation: Any = "",
    speech_style: Any = "",
    role_flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = normalize_character_details(details)
    values = {
        "identity": identity,
        "personality": personality,
        "motivation": motivation,
        "speech_style": speech_style,
    }
    for key, value in values.items():
        text = str(value or "").strip()
        if text:
            data[key] = text
        else:
            data.pop(key, None)
    merged_flags = dict(data.get("role_flags", {}))
    for flag in CHARACTER_ROLE_FLAGS:
        merged_flags[flag] = bool((role_flags or {}).get(flag, False))
    data["role_flags"] = merged_flags
    data.setdefault("modules", {})
    return data


def merge_module_patches(details: Any, module_patches: dict[str, Any] | None = None) -> dict[str, Any]:
    data = load_details(details)
    modules = data.get("modules")
    if not isinstance(modules, dict):
        modules = {}
    for module_id, patch in (module_patches or {}).items():
        if not isinstance(patch, dict):
            modules[str(module_id)] = patch
            continue
        existing = modules.get(str(module_id))
        if isinstance(existing, dict):
            modules[str(module_id)] = {**existing, **patch}
        else:
            modules[str(module_id)] = dict(patch)
    data["modules"] = modules
    return data


def extract_required_state_modules(
    world_items: list[dict[str, Any]],
    active_tags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    active_ids = {
        str(tag.get("id", "")).strip()
        for tag in active_tags
        if tag.get("requires_memory") and str(tag.get("id", "")).strip()
    }
    if not active_ids:
        return []
    extracted: list[dict[str, Any]] = []
    for item in world_items:
        details = load_details(item.get("details_json", item.get("details")))
        modules = details.get("modules")
        if not isinstance(modules, dict):
            continue
        matched = {
            module_id: value
            for module_id, value in modules.items()
            if module_id in active_ids
        }
        if matched:
            extracted.append(
                {
                    "kind": item.get("kind", ""),
                    "name": item.get("name", ""),
                    "modules": matched,
                }
            )
    return extracted
