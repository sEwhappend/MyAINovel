from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_PROJECTS_ROOT = Path("projects")
PROJECT_DIRS = ("outline", "library", "chapters", "versions", "exports")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename(value: Any, fallback: str = "untitled", max_length: int = 80) -> str:
    text = str(value or "").strip()
    text = _INVALID_FILENAME_CHARS.sub("-", text)
    text = _WHITESPACE.sub("-", text)
    text = text.strip(" .-_")
    if not text:
        text = fallback
    if text.upper() in WINDOWS_RESERVED_NAMES:
        text = f"{text}-file"
    if len(text) > max_length:
        text = text[:max_length].rstrip(" .-_")
    return text or fallback


def project_folder_name(project: Mapping[str, Any]) -> str:
    project_id = _required_int(project, "id")
    title = sanitize_filename(project.get("title"), fallback="untitled")
    return f"project-{project_id}-{title}"


def project_path(project: Mapping[str, Any], root: Path = DEFAULT_PROJECTS_ROOT) -> Path:
    root = Path(root)
    existing = find_project_path(project, root)
    if existing is not None:
        return existing
    return root / project_folder_name(project)


def find_project_path(project: Mapping[str, Any], root: Path = DEFAULT_PROJECTS_ROOT) -> Path | None:
    project_id = _required_int(project, "id")
    root = Path(root)
    if not root.exists():
        return None
    prefix = f"project-{project_id}-"
    for path in sorted(root.iterdir()):
        if path.is_dir() and path.name.startswith(prefix):
            return path
    return None


def ensure_project_structure(
    project: Mapping[str, Any],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> Path:
    base = project_path(project, root)
    base.mkdir(parents=True, exist_ok=True)
    for dirname in PROJECT_DIRS:
        (base / dirname).mkdir(parents=True, exist_ok=True)
    return base


def sync_project_core(
    project: Mapping[str, Any],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> Path:
    base = ensure_project_structure(project, root)
    write_project_json(project, root)
    write_worldbook(project, root)
    write_style(project, root)
    return base


def write_project_json(
    project: Mapping[str, Any],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> Path:
    base = ensure_project_structure(project, root)
    return _write_json(base / "project.json", project)


def write_worldbook(
    project: Mapping[str, Any],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> Path:
    base = ensure_project_structure(project, root)
    sections = [
        ("世界概述", project.get("world_summary", "")),
        ("角色简述", project.get("character_brief", "")),
        ("全局概念", project.get("global_concept", "")),
    ]
    return _write_text(base / "worldbook.md", _markdown_document("Worldbook", sections))


def write_style(
    project: Mapping[str, Any],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> Path:
    base = ensure_project_structure(project, root)
    sections = [
        ("类型", project.get("genre", "")),
        ("风格", project.get("style", "")),
        ("目标读者", project.get("target_readers", "")),
        ("篇幅目标", project.get("length_target", "")),
        ("叙事视角", project.get("pov", "")),
        ("写作风格指南", project.get("writing_style_guide", "")),
    ]
    return _write_text(base / "style.md", _markdown_document("Style Guide", sections))


def sync_library(
    project: Mapping[str, Any],
    items: Iterable[Mapping[str, Any]],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> list[Path]:
    library_dir = ensure_project_structure(project, root) / "library"
    _clear_directory(library_dir)
    return [write_library_item(project, item, root) for item in items]


def write_library_item(
    project: Mapping[str, Any],
    item: Mapping[str, Any],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> Path:
    base = ensure_project_structure(project, root) / "library"
    kind = sanitize_filename(item.get("kind"), fallback="item", max_length=40)
    name = sanitize_filename(item.get("name"), fallback="unnamed")
    item_id = item.get("id")
    prefix = f"{int(item_id):04d}-" if _is_int_like(item_id) else ""
    path = base / kind
    path.mkdir(parents=True, exist_ok=True)
    return _write_json(path / f"{prefix}{name}.json", _library_file_payload(item))


def sync_chapters(
    project: Mapping[str, Any],
    chapters: Iterable[Mapping[str, Any]],
    sections_by_chapter: Mapping[int, Iterable[Mapping[str, Any]]] | None = None,
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> list[Path]:
    chapters_dir = ensure_project_structure(project, root) / "chapters"
    _clear_directory(chapters_dir)
    written: list[Path] = []
    for chapter in chapters:
        chapter_path = write_chapter(project, chapter, root)
        written.append(chapter_path)
        chapter_id = chapter.get("id")
        if sections_by_chapter is not None and _is_int_like(chapter_id):
            for section in sections_by_chapter.get(int(chapter_id), ()):
                written.append(write_section(project, chapter, section, root))
    return written


def write_chapter(
    project: Mapping[str, Any],
    chapter: Mapping[str, Any],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> Path:
    chapter_dir = _chapter_dir(project, chapter, root)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    _write_json(chapter_dir / "chapter.json", chapter)
    outline = _markdown_document(
        str(chapter.get("title") or f"Chapter {chapter.get('number', '')}").strip(),
        [
            ("故事时间", chapter.get("story_time", "")),
            ("地点", chapter.get("location", "")),
            ("目标", chapter.get("goal", "")),
            ("大纲", chapter.get("outline", "")),
            ("状态", chapter.get("status", "")),
        ],
    )
    return _write_text(chapter_dir / "outline.md", outline)


def write_section(
    project: Mapping[str, Any],
    chapter: Mapping[str, Any],
    section: Mapping[str, Any],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> Path:
    chapter_dir = _chapter_dir(project, chapter, root)
    chapter_dir.mkdir(parents=True, exist_ok=True)
    number = _number_prefix(section.get("number"))
    title = sanitize_filename(section.get("title"), fallback="section")
    path = chapter_dir / f"section-{number}-{title}.json"
    return _write_json(path, section)


def sync_versions(
    project: Mapping[str, Any],
    versions: Iterable[Mapping[str, Any]],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> list[Path]:
    versions_dir = ensure_project_structure(project, root) / "versions"
    _clear_directory(versions_dir)
    return [write_version(project, version, root) for version in versions]


def load_projects(root: Path = DEFAULT_PROJECTS_ROOT) -> list[dict[str, Any]]:
    root = Path(root)
    if not root.exists():
        return []
    projects: list[dict[str, Any]] = []
    for base in sorted(root.iterdir()):
        if not base.is_dir():
            continue
        project_json = base / "project.json"
        if not project_json.exists():
            continue
        project = _read_json(project_json)
        if not project:
            continue
        projects.append(
            {
                "project": project,
                "world_items": _load_library(base),
                "chapters": _load_chapters(base),
                "versions": _load_versions(base),
            }
        )
    return projects


def write_version(
    project: Mapping[str, Any],
    version: Mapping[str, Any],
    root: Path = DEFAULT_PROJECTS_ROOT,
) -> Path:
    base = ensure_project_structure(project, root) / "versions"
    kind = sanitize_filename(version.get("kind"), fallback="version", max_length=40)
    version_id = version.get("id")
    label = sanitize_filename(version.get("label"), fallback="content")
    prefix = f"{int(version_id):04d}-" if _is_int_like(version_id) else ""
    path = base / kind
    path.mkdir(parents=True, exist_ok=True)

    content_path = path / f"{prefix}{label}.md"
    content = str(version.get("content") or "")
    _write_text(content_path, content)
    _write_json(content_path.with_suffix(".json"), _version_file_payload(version))
    return content_path


def _load_library(base: Path) -> list[dict[str, Any]]:
    library_dir = base / "library"
    if not library_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(library_dir.glob("*/*.json")):
        item = _read_json(path)
        if not item:
            continue
        if "details_json" not in item and "details" in item:
            item["details_json"] = item["details"]
        elif "details_json" in item:
            item["details_json"] = _json_string(item["details_json"])
        items.append(item)
    return items


def _load_chapters(base: Path) -> list[dict[str, Any]]:
    chapters_dir = base / "chapters"
    if not chapters_dir.exists():
        return []
    chapters: list[dict[str, Any]] = []
    for chapter_dir in sorted(chapters_dir.iterdir()):
        if not chapter_dir.is_dir():
            continue
        chapter = _read_json(chapter_dir / "chapter.json")
        if not chapter:
            continue
        sections = []
        for section_path in sorted(chapter_dir.glob("section-*.json")):
            section = _read_json(section_path)
            if section:
                sections.append(section)
        chapter["_sections"] = sections
        chapters.append(chapter)
    return chapters


def _load_versions(base: Path) -> list[dict[str, Any]]:
    versions_dir = base / "versions"
    if not versions_dir.exists():
        return []
    versions: list[dict[str, Any]] = []
    for metadata_path in sorted(versions_dir.glob("*/*.json")):
        version = _read_json(metadata_path)
        if not version:
            continue
        content_path = metadata_path.with_suffix(".md")
        if content_path.exists():
            version["content"] = content_path.read_text(encoding="utf-8").removesuffix("\n")
        if "metadata_json" in version:
            version["metadata_json"] = _json_string(version["metadata_json"])
        elif "metadata" in version:
            version["metadata_json"] = version["metadata"]
        versions.append(version)
    return versions


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _json_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _library_file_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    if "details" not in payload and "details_json" in payload:
        payload["details"] = _json_value(payload["details_json"]) or {}
    payload.pop("details_json", None)
    return payload


def _version_file_payload(version: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(version)
    if "metadata" not in payload and "metadata_json" in payload:
        payload["metadata"] = _json_value(payload["metadata_json"]) or {}
    payload.pop("metadata_json", None)
    return payload


def _chapter_dir(
    project: Mapping[str, Any],
    chapter: Mapping[str, Any],
    root: Path,
) -> Path:
    base = ensure_project_structure(project, root) / "chapters"
    number = _number_prefix(chapter.get("number"))
    title = sanitize_filename(chapter.get("title"), fallback="chapter")
    return base / f"chapter-{number}-{title}"


def _number_prefix(value: Any) -> str:
    if _is_int_like(value):
        return f"{int(value):03d}"
    return "000"


def _required_int(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if not _is_int_like(value):
        raise ValueError(f"{key} is required and must be an integer")
    return int(value)


def _is_int_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return True


def _write_json(path: Path, data: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(data), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def _clear_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError:
            continue


def _markdown_document(title: str, sections: Iterable[tuple[str, Any]]) -> str:
    lines = [f"# {title}", ""]
    for heading, value in sections:
        lines.extend([f"## {heading}", "", str(value or "").strip(), ""])
    return "\n".join(lines)
