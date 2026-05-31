from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import DEFAULT_LLM_CONFIG, validate_status, validate_version_status, validate_world_kind
from .project_files import (
    DEFAULT_PROJECTS_ROOT,
    load_projects,
    sync_chapters,
    sync_library,
    sync_project_core,
    sync_versions,
)
from .style_tags import PROJECT_STYLE_TAG_FIELDS, dump_tag_ids


DEFAULT_DB_PATH = Path(os.environ.get("MY_AI_NOVEL_DB", "data/my_ai_novel.db"))


def _now_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _normalized_world_name(name: Any) -> str:
    text = str(name or "").strip().casefold()
    text = re.sub(r"（[^）]*）|\([^)]*\)|\[[^\]]*\]|【[^】]*】", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^[：:【\[]?(主角|角色|人物|地点|场景|组织|势力|规则|设定|伏笔|时间线|事件|禁止事项)[：:】\]]?", "", text)
    text = re.sub(r"[，,。.!！?？;；:：、·\-—_《》\"“”'‘’]", "", text)
    return text


def _merge_non_empty(existing: Any, incoming: Any) -> str:
    incoming_text = str(incoming or "")
    if incoming_text:
        return incoming_text
    return str(existing or "")


def _merge_text(existing: Any, incoming: Any) -> str:
    existing_text = str(existing or "").strip()
    incoming_text = str(incoming or "").strip()
    if not incoming_text:
        return existing_text
    if not existing_text:
        return incoming_text
    if existing_text == incoming_text:
        return existing_text
    return f"{existing_text}\n{incoming_text}"


def _merge_details_json(existing: Any, incoming: Any) -> str:
    existing_text = str(existing or "")
    incoming_text = _json(incoming)
    if not incoming_text:
        return existing_text
    try:
        existing_data = json.loads(existing_text) if existing_text else {}
        incoming_data = json.loads(incoming_text)
    except json.JSONDecodeError:
        return incoming_text
    if isinstance(existing_data, dict) and isinstance(incoming_data, dict):
        merged = dict(existing_data)
        for key, value in incoming_data.items():
            if value in ("", None):
                continue
            if key == "chapter_memory" and isinstance(value, list):
                existing_memory = merged.get("chapter_memory")
                if isinstance(existing_memory, list):
                    merged["chapter_memory"] = [*existing_memory, *value]
                else:
                    merged["chapter_memory"] = value
                continue
            merged[key] = value
        return _json(merged)
    return incoming_text


def _merge_tags(existing: Any, incoming: Any) -> str:
    tags: list[str] = []
    seen: set[str] = set()
    for source in (existing, incoming):
        for tag in str(source or "").split(","):
            clean = tag.strip()
            key = clean.casefold()
            if clean and key not in seen:
                tags.append(clean)
                seen.add(key)
    return ",".join(tags)


def _parse_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 0 else None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "").replace("，", "").replace(" ", "").lower()
    unit_match = re.search(r"(\d+(?:\.\d+)?)(?:万|w)", text)
    if unit_match:
        number = int(float(unit_match.group(1)) * 10000)
        return number if number > 0 else None
    number_match = re.search(r"\d+(?:\.\d+)?", text)
    if not number_match:
        return None
    number = int(float(number_match.group(0)))
    return number if number > 0 else None


def _default_section_words_from_project(data: dict[str, Any]) -> str:
    total_words = _parse_positive_int(data.get("length_target"))
    section_count = _parse_positive_int(data.get("estimated_total_sections"))
    if not total_words or not section_count:
        return ""
    return str(max(1, round(total_words / section_count)))


def _apply_project_word_defaults(data: dict[str, Any]) -> None:
    if str(data.get("default_section_target_words", "") or "").strip():
        return
    calculated = _default_section_words_from_project(data)
    if calculated:
        data["default_section_target_words"] = calculated


def _dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


class NovelStore:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        projects_root: str | Path = DEFAULT_PROJECTS_ROOT,
    ) -> None:
        self.db_path = Path(db_path)
        self.projects_root = Path(projects_root)
        init_db(self.db_path)
        self._migrate_missing_sqlite_projects_to_files()
        self.rebuild_cache_from_project_files()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=OFF")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create_project(self, data: dict[str, Any]) -> int:
        fields = {
            "title": "",
            "genre": "",
            "style": "",
            "target_readers": "",
            "length_target": "",
            "estimated_total_sections": "",
            "default_section_target_words": "",
            "pov": "",
            "selected_genre_tags": "[]",
            "selected_setting_tags": "[]",
            "selected_character_tags": "[]",
            "selected_structure_tags": "[]",
            "selected_style_tags": "[]",
            "selected_forbidden_tags": "[]",
            "dialogue_quote_style": "cn_quotes",
            "generation_profile_json": "",
            "world_summary": "",
            "character_brief": "",
            "writing_style_guide": "",
            "global_concept": "",
        }
        fields.update({key: value for key, value in data.items() if key in fields})
        for key in PROJECT_STYLE_TAG_FIELDS:
            fields[key] = dump_tag_ids(fields.get(key))
        fields["dialogue_quote_style"] = str(fields.get("dialogue_quote_style") or "cn_quotes")
        fields["generation_profile_json"] = _json(fields.get("generation_profile_json"))
        _apply_project_word_defaults(fields)
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO projects (
                    title, genre, style, target_readers, length_target,
                    estimated_total_sections, default_section_target_words, pov,
                    selected_genre_tags, selected_setting_tags,
                    selected_character_tags, selected_structure_tags,
                    selected_style_tags, selected_forbidden_tags, dialogue_quote_style,
                    generation_profile_json,
                    world_summary, character_brief, writing_style_guide,
                    global_concept, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                tuple(fields[name] for name in fields),
            )
            project_id = int(cur.lastrowid)
        self.sync_project_files(project_id)
        return project_id

    def update_project(self, project_id: int, data: dict[str, Any]) -> None:
        allowed = {
            "title",
            "genre",
            "style",
            "target_readers",
            "length_target",
            "estimated_total_sections",
            "default_section_target_words",
            "pov",
            "selected_genre_tags",
            "selected_setting_tags",
            "selected_character_tags",
            "selected_structure_tags",
            "selected_style_tags",
            "selected_forbidden_tags",
            "dialogue_quote_style",
            "generation_profile_json",
            "world_summary",
            "character_brief",
            "writing_style_guide",
            "global_concept",
        }
        updates = {key: value for key, value in data.items() if key in allowed}
        if not updates:
            return
        for key in PROJECT_STYLE_TAG_FIELDS:
            if key in updates:
                updates[key] = dump_tag_ids(updates.get(key))
        if "dialogue_quote_style" in updates:
            updates["dialogue_quote_style"] = str(updates.get("dialogue_quote_style") or "cn_quotes")
        if "generation_profile_json" in updates:
            updates["generation_profile_json"] = _json(updates.get("generation_profile_json"))
        current = self.get_project(project_id) or {}
        merged = dict(current)
        merged.update(updates)
        if not str(merged.get("default_section_target_words", "") or "").strip():
            calculated = _default_section_words_from_project(merged)
            if calculated:
                updates["default_section_target_words"] = calculated
        assignments = ", ".join(f"{key}=?" for key in updates) + ", updated_at=datetime('now')"
        with self.connection() as conn:
            conn.execute(
                f"UPDATE projects SET {assignments} WHERE id=?",
                [*updates.values(), project_id],
            )
        self.sync_project_files(project_id)

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return _dict(row) if row else None

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC, id DESC").fetchall()
            return [_dict(row) for row in rows]

    def save_world_item(self, project_id: int, item: dict[str, Any]) -> int:
        kind = validate_world_kind(item.get("kind", "character"))
        values = {
            "id": item.get("id"),
            "project_id": project_id,
            "kind": kind,
            "name": item.get("name", ""),
            "summary": item.get("summary", ""),
            "details_json": _json(item.get("details_json", item.get("details", {}))),
            "tags": item.get("tags", ""),
            "status": item.get("status", ""),
            "embedding_json": _json(item.get("embedding_json", item.get("embedding"))),
        }
        with self.connection() as conn:
            if values["id"]:
                conn.execute(
                    """
                    UPDATE world_items
                    SET kind=?, name=?, summary=?, details_json=?, tags=?, status=?,
                        embedding_json=?, updated_at=datetime('now')
                    WHERE id=? AND project_id=?
                    """,
                    (
                        values["kind"],
                        values["name"],
                        values["summary"],
                        values["details_json"],
                        values["tags"],
                        values["status"],
                        values["embedding_json"],
                        values["id"],
                        project_id,
                    ),
                )
                item_id = int(values["id"])
            else:
                cur = conn.execute(
                    """
                    INSERT INTO world_items (
                        project_id, kind, name, summary, details_json, tags, status,
                        embedding_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        project_id,
                        values["kind"],
                        values["name"],
                        values["summary"],
                        values["details_json"],
                        values["tags"],
                        values["status"],
                        values["embedding_json"],
                    ),
                )
                item_id = int(cur.lastrowid)
        self.sync_project_files(project_id)
        return item_id

    def upsert_world_item(self, project_id: int, item: dict[str, Any]) -> int:
        kind = validate_world_kind(item.get("kind", "character"))
        normalized_name = _normalized_world_name(item.get("name", ""))
        if not normalized_name:
            return self.save_world_item(project_id, item)

        values = {
            "kind": kind,
            "name": item.get("name", ""),
            "summary": item.get("summary", ""),
            "details_json": _json(item.get("details_json", item.get("details", {}))),
            "tags": item.get("tags", ""),
            "status": item.get("status", ""),
            "embedding_json": _json(item.get("embedding_json", item.get("embedding"))),
        }
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM world_items
                WHERE project_id=? AND kind=?
                ORDER BY id
                """,
                (project_id, kind),
            ).fetchall()
            existing = next(
                (
                    row
                    for row in rows
                    if _normalized_world_name(row["name"]) == normalized_name
                ),
                None,
            )
            if existing is None:
                cur = conn.execute(
                    """
                    INSERT INTO world_items (
                        project_id, kind, name, summary, details_json, tags, status,
                        embedding_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        project_id,
                        values["kind"],
                        values["name"],
                        values["summary"],
                        values["details_json"],
                        values["tags"],
                        values["status"],
                        values["embedding_json"],
                    ),
                )
                item_id = int(cur.lastrowid)
            else:
                item_id = int(existing["id"])
                status = values["status"]
                if status == "candidate" and not self._is_outline_split_candidate(
                    existing["details_json"],
                    existing["status"],
                ):
                    status = existing["status"]
                conn.execute(
                    """
                    UPDATE world_items
                    SET name=?, summary=?, details_json=?, tags=?, status=?,
                        embedding_json=?, updated_at=datetime('now')
                    WHERE id=? AND project_id=?
                    """,
                    (
                        _merge_non_empty(existing["name"], values["name"]),
                        _merge_text(existing["summary"], values["summary"]),
                        _merge_details_json(existing["details_json"], values["details_json"]),
                        _merge_tags(existing["tags"], values["tags"]),
                        _merge_non_empty(existing["status"], status),
                        _merge_non_empty(existing["embedding_json"], values["embedding_json"]),
                        item_id,
                        project_id,
                    ),
                )
        self.sync_project_files(project_id)
        return item_id

    def list_world_items(self, project_id: int, kind: str | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if kind:
                validate_world_kind(kind)
                rows = conn.execute(
                    "SELECT * FROM world_items WHERE project_id=? AND kind=? ORDER BY kind, name",
                    (project_id, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM world_items WHERE project_id=? ORDER BY kind, name",
                    (project_id,),
                ).fetchall()
            return [_dict(row) for row in rows]

    def get_world_item(self, project_id: int, item_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM world_items WHERE id=? AND project_id=?",
                (item_id, project_id),
            ).fetchone()
            return _dict(row) if row else None

    def delete_world_item(self, project_id: int, item_id: int) -> None:
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM world_items WHERE id=? AND project_id=?",
                (item_id, project_id),
            )
        self.sync_project_files(project_id)

    def reset_outline_split_content(self, project_id: int) -> None:
        with self.connection() as conn:
            chapter_rows = conn.execute(
                "SELECT id FROM chapters WHERE project_id=?",
                (project_id,),
            ).fetchall()
            chapter_ids = [int(row["id"]) for row in chapter_rows]
            if chapter_ids:
                placeholders = ",".join("?" for _ in chapter_ids)
                section_rows = conn.execute(
                    f"SELECT id FROM sections WHERE chapter_id IN ({placeholders})",
                    chapter_ids,
                ).fetchall()
                section_ids = [int(row["id"]) for row in section_rows]
                if section_ids:
                    section_placeholders = ",".join("?" for _ in section_ids)
                    conn.execute(
                        f"DELETE FROM versions WHERE section_id IN ({section_placeholders})",
                        section_ids,
                    )
                conn.execute(
                    f"DELETE FROM versions WHERE chapter_id IN ({placeholders})",
                    chapter_ids,
                )
                conn.execute(
                    f"DELETE FROM sections WHERE chapter_id IN ({placeholders})",
                    chapter_ids,
                )
                conn.execute(
                    "DELETE FROM chapters WHERE project_id=?",
                    (project_id,),
                )

            world_rows = conn.execute(
                "SELECT id, details_json, status FROM world_items WHERE project_id=?",
                (project_id,),
            ).fetchall()
            outline_item_ids = [
                int(row["id"])
                for row in world_rows
                if self._is_outline_split_candidate(row["details_json"], row["status"])
            ]
            if outline_item_ids:
                placeholders = ",".join("?" for _ in outline_item_ids)
                conn.execute(
                    f"DELETE FROM world_items WHERE id IN ({placeholders}) AND project_id=?",
                    [*outline_item_ids, project_id],
                )
        self.sync_project_files(project_id)

    def save_chapter(self, project_id: int, data: dict[str, Any]) -> int:
        status = validate_status(data.get("status", "planned"))
        values = {
            "id": data.get("id"),
            "project_id": project_id,
            "number": int(data.get("number", 1)),
            "title": data.get("title", ""),
            "story_time": data.get("story_time", ""),
            "location": data.get("location", ""),
            "characters_json": _json(data.get("characters_json", data.get("characters", []))),
            "goal": data.get("goal", ""),
            "outline": data.get("outline", ""),
            "status": status,
        }
        with self.connection() as conn:
            if values["id"]:
                conn.execute(
                    """
                    UPDATE chapters
                    SET number=?, title=?, story_time=?, location=?, characters_json=?,
                        goal=?, outline=?, status=?
                    WHERE id=? AND project_id=?
                    """,
                    (
                        values["number"],
                        values["title"],
                        values["story_time"],
                        values["location"],
                        values["characters_json"],
                        values["goal"],
                        values["outline"],
                        values["status"],
                        values["id"],
                        project_id,
                    ),
                )
                chapter_id = int(values["id"])
            else:
                cur = conn.execute(
                    """
                    INSERT INTO chapters (
                        project_id, number, title, story_time, location, characters_json,
                        goal, outline, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        values["number"],
                        values["title"],
                        values["story_time"],
                        values["location"],
                        values["characters_json"],
                        values["goal"],
                        values["outline"],
                        values["status"],
                    ),
                )
                chapter_id = int(cur.lastrowid)
        self.sync_project_files(project_id)
        return chapter_id

    def get_chapter(self, chapter_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
            return _dict(row) if row else None

    def list_chapters(self, project_id: int) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE project_id=? ORDER BY number, id",
                (project_id,),
            ).fetchall()
            return [_dict(row) for row in rows]

    def move_chapter(self, project_id: int, chapter_id: int, direction: int) -> None:
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or 1")
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM chapters WHERE project_id=? ORDER BY number, id",
                (project_id,),
            ).fetchall()
            chapter_ids = [int(row["id"]) for row in rows]
            if chapter_id not in chapter_ids:
                raise ValueError("chapter not found")
            index = chapter_ids.index(chapter_id)
            target_index = index + direction
            if target_index < 0:
                raise ValueError("已经是第一章")
            if target_index >= len(chapter_ids):
                raise ValueError("已经是最后一章")
            chapter_ids[index], chapter_ids[target_index] = chapter_ids[target_index], chapter_ids[index]
            for number, current_id in enumerate(chapter_ids, 1):
                conn.execute(
                    "UPDATE chapters SET number=? WHERE id=? AND project_id=?",
                    (number, current_id, project_id),
                )
        self.sync_project_files(project_id)

    def delete_chapter(self, project_id: int, chapter_id: int) -> None:
        with self.connection() as conn:
            chapter = conn.execute(
                "SELECT id FROM chapters WHERE id=? AND project_id=?",
                (chapter_id, project_id),
            ).fetchone()
            if chapter is None:
                raise ValueError("chapter not found")
            section_rows = conn.execute(
                "SELECT id FROM sections WHERE chapter_id=?",
                (chapter_id,),
            ).fetchall()
            section_ids = [int(row["id"]) for row in section_rows]
            if section_ids:
                placeholders = ",".join("?" for _ in section_ids)
                conn.execute(
                    f"DELETE FROM versions WHERE section_id IN ({placeholders})",
                    section_ids,
                )
            conn.execute("DELETE FROM versions WHERE chapter_id=?", (chapter_id,))
            conn.execute("DELETE FROM sections WHERE chapter_id=?", (chapter_id,))
            conn.execute("DELETE FROM chapters WHERE id=? AND project_id=?", (chapter_id, project_id))
            self._renumber_project_chapters(conn, project_id)
        self.sync_project_files(project_id)

    def save_section(self, chapter_id: int, data: dict[str, Any]) -> int:
        status = validate_status(data.get("status", "planned"))
        values = {
            "id": data.get("id"),
            "chapter_id": chapter_id,
            "number": int(data.get("number", 1)),
            "title": data.get("title", ""),
            "story_time": data.get("story_time", ""),
            "scene": data.get("scene", ""),
            "location": data.get("location", ""),
            "characters_json": _json(data.get("characters_json", data.get("characters", []))),
            "goal": data.get("goal", ""),
            "conflict": data.get("conflict", ""),
            "emotion_shift": data.get("emotion_shift", ""),
            "must_happen_json": _json(data.get("must_happen_json", data.get("must_happen", []))),
            "forbidden_json": _json(data.get("forbidden_json", data.get("forbidden", []))),
            "target_words": int(data.get("target_words", 1200) or 1200),
            "status": status,
            "finalized_version_id": data.get("finalized_version_id"),
        }
        project_id = self._project_id_for_chapter(chapter_id)
        with self.connection() as conn:
            if values["id"]:
                conn.execute(
                    """
                    UPDATE sections
                    SET number=?, title=?, story_time=?, scene=?, location=?, characters_json=?,
                        goal=?, conflict=?, emotion_shift=?, must_happen_json=?,
                        forbidden_json=?, target_words=?, status=?, finalized_version_id=?
                    WHERE id=? AND chapter_id=?
                    """,
                    (
                        values["number"],
                        values["title"],
                        values["story_time"],
                        values["scene"],
                        values["location"],
                        values["characters_json"],
                        values["goal"],
                        values["conflict"],
                        values["emotion_shift"],
                        values["must_happen_json"],
                        values["forbidden_json"],
                        values["target_words"],
                        values["status"],
                        values["finalized_version_id"],
                        values["id"],
                        chapter_id,
                    ),
                )
                section_id = int(values["id"])
            else:
                cur = conn.execute(
                    """
                    INSERT INTO sections (
                        chapter_id, number, title, story_time, scene, location, characters_json,
                        goal, conflict, emotion_shift, must_happen_json, forbidden_json,
                        target_words, status, finalized_version_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chapter_id,
                        values["number"],
                        values["title"],
                        values["story_time"],
                        values["scene"],
                        values["location"],
                        values["characters_json"],
                        values["goal"],
                        values["conflict"],
                        values["emotion_shift"],
                        values["must_happen_json"],
                        values["forbidden_json"],
                        values["target_words"],
                        values["status"],
                        values["finalized_version_id"],
                    ),
                )
                section_id = int(cur.lastrowid)
        if project_id is not None:
            self.sync_project_files(project_id)
        return section_id

    def get_section(self, section_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM sections WHERE id=?", (section_id,)).fetchone()
            return _dict(row) if row else None

    def list_sections(self, chapter_id: int) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sections WHERE chapter_id=? ORDER BY number, id",
                (chapter_id,),
            ).fetchall()
            return [_dict(row) for row in rows]

    def list_finalized_section_versions(self, chapter_id: int) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    sections.id AS section_id,
                    sections.number AS section_number,
                    sections.title AS section_title,
                    versions.id AS version_id,
                    versions.content AS content,
                    versions.metadata_json AS metadata_json
                FROM sections
                JOIN versions ON versions.id = sections.finalized_version_id
                WHERE sections.chapter_id=?
                    AND sections.status='finalized'
                    AND sections.finalized_version_id IS NOT NULL
                ORDER BY sections.number, sections.id
                """,
                (chapter_id,),
            ).fetchall()
            return [_dict(row) for row in rows]

    def delete_section(self, section_id: int) -> None:
        project_id = self._project_id_for_section(section_id)
        section = self.get_section(section_id)
        if section is None:
            raise ValueError("section not found")
        chapter_id = int(section["chapter_id"])
        with self.connection() as conn:
            conn.execute("DELETE FROM versions WHERE section_id=?", (section_id,))
            conn.execute("DELETE FROM sections WHERE id=?", (section_id,))
            self._renumber_chapter_sections(conn, chapter_id)
        if project_id is not None:
            self.sync_project_files(project_id)

    def move_section(self, chapter_id: int, section_id: int, direction: int) -> None:
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or 1")
        project_id = self._project_id_for_chapter(chapter_id)
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM sections WHERE chapter_id=? ORDER BY number, id",
                (chapter_id,),
            ).fetchall()
            section_ids = [int(row["id"]) for row in rows]
            if section_id not in section_ids:
                raise ValueError("section not found")
            index = section_ids.index(section_id)
            target_index = index + direction
            if target_index < 0:
                raise ValueError("已经是第一节")
            if target_index >= len(section_ids):
                raise ValueError("已经是最后一节")
            section_ids[index], section_ids[target_index] = section_ids[target_index], section_ids[index]
            for number, current_id in enumerate(section_ids, 1):
                conn.execute(
                    "UPDATE sections SET number=? WHERE id=? AND chapter_id=?",
                    (number, current_id, chapter_id),
                )
        if project_id is not None:
            self.sync_project_files(project_id)

    def update_section_status(self, section_id: int, status: str) -> None:
        validate_status(status)
        project_id = self._project_id_for_section(section_id)
        with self.connection() as conn:
            conn.execute("UPDATE sections SET status=? WHERE id=?", (status, section_id))
        if project_id is not None:
            self.sync_project_files(project_id)

    def finalize_section(self, section_id: int, version_id: int) -> None:
        project_id = self._project_id_for_section(section_id)
        with self.connection() as conn:
            conn.execute("UPDATE versions SET status='usable' WHERE section_id=?", (section_id,))
            conn.execute("UPDATE versions SET status='final' WHERE id=?", (version_id,))
            conn.execute(
                "UPDATE sections SET status='finalized', finalized_version_id=? WHERE id=?",
                (version_id, section_id),
            )
        if project_id is not None:
            self.sync_project_files(project_id)

    def unfinalize_section(self, section_id: int) -> None:
        project_id = self._project_id_for_section(section_id)
        with self.connection() as conn:
            conn.execute(
                "UPDATE versions SET status='usable' WHERE id=(SELECT finalized_version_id FROM sections WHERE id=?)",
                (section_id,),
            )
            conn.execute(
                "UPDATE sections SET status='review_pending', finalized_version_id=NULL WHERE id=?",
                (section_id,),
            )
        if project_id is not None:
            self.sync_project_files(project_id)

    def save_version(self, data: dict[str, Any]) -> int:
        status = validate_version_status(data.get("status", "usable"))
        values = {
            "project_id": data["project_id"],
            "chapter_id": data.get("chapter_id"),
            "section_id": data.get("section_id"),
            "kind": data.get("kind", "draft"),
            "label": data.get("label", ""),
            "content": data.get("content", ""),
            "metadata_json": _json(data.get("metadata_json", data.get("metadata", {}))),
            "status": status,
        }
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO versions (
                    project_id, chapter_id, section_id, kind, label, content,
                    metadata_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    values["project_id"],
                    values["chapter_id"],
                    values["section_id"],
                    values["kind"],
                    values["label"],
                    values["content"],
                    values["metadata_json"],
                    values["status"],
                ),
            )
            version_id = int(cur.lastrowid)
        self.sync_project_files(int(values["project_id"]))
        return version_id

    def delete_version(self, version_id: int) -> None:
        project_id = self._project_id_for_version(version_id)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id FROM versions WHERE id=?",
                (version_id,),
            ).fetchone()
            if row is None:
                raise ValueError("version not found")
            finalized = conn.execute(
                "SELECT id FROM sections WHERE finalized_version_id=?",
                (version_id,),
            ).fetchone()
            if finalized is not None:
                raise ValueError("定稿版本不能直接删除，请先取消定稿")
            conn.execute("DELETE FROM versions WHERE id=?", (version_id,))
        if project_id is not None:
            self.sync_project_files(project_id)

    def sync_all_projects(self) -> None:
        for project in self.list_projects():
            self.sync_project_files(int(project["id"]))

    def _migrate_missing_sqlite_projects_to_files(self) -> None:
        for project in self.list_projects():
            project_id = int(project["id"])
            has_files = any(
                file_project.get("project", {}).get("id") == project_id
                for file_project in load_projects(self.projects_root)
            )
            if not has_files:
                self.sync_project_files(project_id)

    def rebuild_cache_from_project_files(self) -> None:
        file_projects = load_projects(self.projects_root)
        with self.connection() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DELETE FROM versions")
            conn.execute("DELETE FROM sections")
            conn.execute("DELETE FROM chapters")
            conn.execute("DELETE FROM world_items")
            conn.execute("DELETE FROM projects")
            conn.execute("PRAGMA foreign_keys=ON")
            for bundle in file_projects:
                self._insert_file_project(conn, bundle)

    def _insert_file_project(self, conn: sqlite3.Connection, bundle: dict[str, Any]) -> None:
        project = dict(bundle["project"])
        _apply_project_word_defaults(project)
        for key in PROJECT_STYLE_TAG_FIELDS:
            project[key] = dump_tag_ids(project.get(key))
        project["dialogue_quote_style"] = str(project.get("dialogue_quote_style") or "cn_quotes")
        project["generation_profile_json"] = _json(project.get("generation_profile_json"))
        project_id = int(project["id"])
        conn.execute(
            """
            INSERT INTO projects (
                id, title, genre, style, target_readers, length_target,
                estimated_total_sections, default_section_target_words, pov,
                selected_genre_tags, selected_setting_tags,
                selected_character_tags, selected_structure_tags,
                selected_style_tags, selected_forbidden_tags, dialogue_quote_style,
                generation_profile_json,
                world_summary, character_brief, writing_style_guide,
                global_concept, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                project.get("title", ""),
                project.get("genre", ""),
                project.get("style", ""),
                project.get("target_readers", ""),
                project.get("length_target", ""),
                project.get("estimated_total_sections", ""),
                project.get("default_section_target_words", ""),
                project.get("pov", ""),
                project.get("selected_genre_tags", "[]"),
                project.get("selected_setting_tags", "[]"),
                project.get("selected_character_tags", "[]"),
                project.get("selected_structure_tags", "[]"),
                project.get("selected_style_tags", "[]"),
                project.get("selected_forbidden_tags", "[]"),
                project.get("dialogue_quote_style", "cn_quotes"),
                project.get("generation_profile_json", ""),
                project.get("world_summary", ""),
                project.get("character_brief", ""),
                project.get("writing_style_guide", ""),
                project.get("global_concept", ""),
                project.get("created_at") or _now_sql(),
                project.get("updated_at") or _now_sql(),
            ),
        )

        for item in bundle.get("world_items", []):
            self._insert_file_world_item(conn, project_id, item)
        for chapter in bundle.get("chapters", []):
            self._insert_file_chapter(conn, project_id, chapter)
        for version in bundle.get("versions", []):
            self._insert_file_version(conn, project_id, version)

    def _insert_file_world_item(
        self,
        conn: sqlite3.Connection,
        project_id: int,
        item: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO world_items (
                id, project_id, kind, name, summary, details_json, tags, status,
                embedding_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(item["id"]),
                project_id,
                validate_world_kind(item.get("kind", "character")),
                item.get("name", ""),
                item.get("summary", ""),
                _json(item.get("details_json", item.get("details", {}))),
                item.get("tags", ""),
                item.get("status", ""),
                _json(item.get("embedding_json", item.get("embedding"))),
                item.get("updated_at") or _now_sql(),
            ),
        )

    def _insert_file_chapter(
        self,
        conn: sqlite3.Connection,
        project_id: int,
        chapter: dict[str, Any],
    ) -> None:
        chapter_id = int(chapter["id"])
        conn.execute(
            """
            INSERT INTO chapters (
                id, project_id, number, title, story_time, location,
                characters_json, goal, outline, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chapter_id,
                project_id,
                int(chapter.get("number", 1)),
                chapter.get("title", ""),
                chapter.get("story_time", ""),
                chapter.get("location", ""),
                _json(chapter.get("characters_json", chapter.get("characters", []))),
                chapter.get("goal", ""),
                chapter.get("outline", ""),
                validate_status(chapter.get("status", "planned")),
            ),
        )
        for section in chapter.get("_sections", []):
            self._insert_file_section(conn, chapter_id, section)

    def _insert_file_section(
        self,
        conn: sqlite3.Connection,
        chapter_id: int,
        section: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO sections (
                id, chapter_id, number, title, story_time, scene, location,
                characters_json, goal, conflict, emotion_shift, must_happen_json,
                forbidden_json, target_words, status, finalized_version_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(section["id"]),
                chapter_id,
                int(section.get("number", 1)),
                section.get("title", ""),
                section.get("story_time", ""),
                section.get("scene", ""),
                section.get("location", ""),
                _json(section.get("characters_json", section.get("characters", []))),
                section.get("goal", ""),
                section.get("conflict", ""),
                section.get("emotion_shift", ""),
                _json(section.get("must_happen_json", section.get("must_happen", []))),
                _json(section.get("forbidden_json", section.get("forbidden", []))),
                int(section.get("target_words", 1200) or 1200),
                validate_status(section.get("status", "planned")),
                section.get("finalized_version_id"),
            ),
        )

    def _insert_file_version(
        self,
        conn: sqlite3.Connection,
        project_id: int,
        version: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO versions (
                id, project_id, chapter_id, section_id, kind, label, content,
                metadata_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(version["id"]),
                project_id,
                version.get("chapter_id"),
                version.get("section_id"),
                version.get("kind", "draft"),
                version.get("label", ""),
                version.get("content", ""),
                _json(version.get("metadata_json", version.get("metadata", {}))),
                validate_version_status(version.get("status", "usable")),
                version.get("created_at") or _now_sql(),
            ),
        )

    def sync_project_files(self, project_id: int) -> None:
        project = self.get_project(project_id)
        if project is None:
            return
        chapters = self.list_chapters(project_id)
        sections_by_chapter = {
            int(chapter["id"]): self.list_sections(int(chapter["id"]))
            for chapter in chapters
        }
        sync_project_core(project, self.projects_root)
        sync_library(project, self.list_world_items(project_id), self.projects_root)
        sync_chapters(project, chapters, sections_by_chapter, self.projects_root)
        sync_versions(project, self.list_versions(project_id), self.projects_root)

    def _project_id_for_chapter(self, chapter_id: int) -> int | None:
        chapter = self.get_chapter(chapter_id)
        return int(chapter["project_id"]) if chapter else None

    def _project_id_for_section(self, section_id: int) -> int | None:
        section = self.get_section(section_id)
        if section is None:
            return None
        return self._project_id_for_chapter(int(section["chapter_id"]))

    def _project_id_for_version(self, version_id: int) -> int | None:
        version = self.get_version(version_id)
        return int(version["project_id"]) if version else None

    @staticmethod
    def _renumber_project_chapters(conn: sqlite3.Connection, project_id: int) -> None:
        rows = conn.execute(
            "SELECT id FROM chapters WHERE project_id=? ORDER BY number, id",
            (project_id,),
        ).fetchall()
        for number, row in enumerate(rows, 1):
            conn.execute(
                "UPDATE chapters SET number=? WHERE id=? AND project_id=?",
                (number, int(row["id"]), project_id),
            )

    @staticmethod
    def _renumber_chapter_sections(conn: sqlite3.Connection, chapter_id: int) -> None:
        rows = conn.execute(
            "SELECT id FROM sections WHERE chapter_id=? ORDER BY number, id",
            (chapter_id,),
        ).fetchall()
        for number, row in enumerate(rows, 1):
            conn.execute(
                "UPDATE sections SET number=? WHERE id=? AND chapter_id=?",
                (number, int(row["id"]), chapter_id),
            )

    @staticmethod
    def _is_outline_split_candidate(details_json: str | None, status: str | None) -> bool:
        if status != "candidate":
            return False
        try:
            details = json.loads(details_json or "{}")
        except json.JSONDecodeError:
            return False
        return isinstance(details, dict) and details.get("source") == "outline_split"

    def get_version(self, version_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()
            return _dict(row) if row else None

    def list_versions(
        self,
        project_id: int,
        section_id: int | None = None,
        chapter_id: int | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project_id=?"]
        params: list[Any] = [project_id]
        if section_id is not None:
            clauses.append("section_id=?")
            params.append(section_id)
        if chapter_id is not None:
            clauses.append("chapter_id=?")
            params.append(chapter_id)
        if kind is not None:
            clauses.append("kind=?")
            params.append(kind)
        with self.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM versions WHERE {' AND '.join(clauses)} ORDER BY id DESC",
                params,
            ).fetchall()
            return [_dict(row) for row in rows]

    def mark_version(self, version_id: int, status: str) -> None:
        validate_version_status(status)
        project_id = self._project_id_for_version(version_id)
        with self.connection() as conn:
            conn.execute("UPDATE versions SET status=? WHERE id=?", (status, version_id))
        if project_id is not None:
            self.sync_project_files(project_id)

    def get_default_llm_config(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM llm_configs WHERE is_default=1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return _dict(row) if row else None

    def save_llm_config(self, data: dict[str, Any]) -> int:
        with self.connection() as conn:
            conn.execute("UPDATE llm_configs SET is_default=0")
            cur = conn.execute(
                """
                INSERT INTO llm_configs (
                    name, base_url, api_key_ref, chat_model, review_model, embedding_model,
                    timeout_seconds, max_tokens, temperature, top_p, top_k,
                    presence_penalty, frequency_penalty, is_default
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    data.get("name", "default"),
                    data.get("base_url", ""),
                    data.get("api_key_ref", "llm_config"),
                    data.get("chat_model", ""),
                    data.get("review_model", ""),
                    data.get("embedding_model", ""),
                    int(data.get("timeout_seconds", DEFAULT_LLM_CONFIG["timeout_seconds"]) or DEFAULT_LLM_CONFIG["timeout_seconds"]),
                    int(data.get("max_tokens", 2000) or 2000),
                    float(data.get("temperature", 0.7) or 0.0),
                    float(data.get("top_p", 0.9) or 0.0),
                    data.get("top_k"),
                    float(data.get("presence_penalty", 0.0) or 0.0),
                    float(data.get("frequency_penalty", 0.0) or 0.0),
                ),
            )
            return int(cur.lastrowid)

    def save_llm_call_log(self, data: dict[str, Any]) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO llm_call_logs (
                    project_id, agent_name, model, request_summary, response_summary,
                    success, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    data.get("project_id"),
                    data.get("agent_name", ""),
                    data.get("model", ""),
                    data.get("request_summary", ""),
                    data.get("response_summary", ""),
                    1 if data.get("success", False) else 0,
                    data.get("error"),
                ),
            )
            return int(cur.lastrowid)

    def list_llm_call_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM llm_call_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [_dict(row) for row in rows]


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.execute("PRAGMA journal_mode=OFF")
            conn.executescript(
                """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                genre TEXT NOT NULL DEFAULT '',
                style TEXT NOT NULL DEFAULT '',
                target_readers TEXT NOT NULL DEFAULT '',
                length_target TEXT NOT NULL DEFAULT '',
                estimated_total_sections TEXT NOT NULL DEFAULT '',
                default_section_target_words TEXT NOT NULL DEFAULT '',
                pov TEXT NOT NULL DEFAULT '',
                selected_genre_tags TEXT NOT NULL DEFAULT '[]',
                selected_setting_tags TEXT NOT NULL DEFAULT '[]',
                selected_character_tags TEXT NOT NULL DEFAULT '[]',
                selected_structure_tags TEXT NOT NULL DEFAULT '[]',
                selected_style_tags TEXT NOT NULL DEFAULT '[]',
                selected_forbidden_tags TEXT NOT NULL DEFAULT '[]',
                dialogue_quote_style TEXT NOT NULL DEFAULT 'cn_quotes',
                generation_profile_json TEXT NOT NULL DEFAULT '',
                world_summary TEXT NOT NULL DEFAULT '',
                character_brief TEXT NOT NULL DEFAULT '',
                writing_style_guide TEXT NOT NULL DEFAULT '',
                global_concept TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS world_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                embedding_json TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                number INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                story_time TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                characters_json TEXT NOT NULL DEFAULT '',
                goal TEXT NOT NULL DEFAULT '',
                outline TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unplanned',
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER NOT NULL,
                number INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                story_time TEXT NOT NULL DEFAULT '',
                scene TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                characters_json TEXT NOT NULL DEFAULT '',
                goal TEXT NOT NULL DEFAULT '',
                conflict TEXT NOT NULL DEFAULT '',
                emotion_shift TEXT NOT NULL DEFAULT '',
                must_happen_json TEXT NOT NULL DEFAULT '',
                forbidden_json TEXT NOT NULL DEFAULT '',
                target_words INTEGER NOT NULL DEFAULT 1200,
                status TEXT NOT NULL DEFAULT 'unplanned',
                finalized_version_id INTEGER,
                FOREIGN KEY(chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                chapter_id INTEGER,
                section_id INTEGER,
                kind TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'usable',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS llm_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT 'default',
                base_url TEXT NOT NULL DEFAULT '',
                api_key_ref TEXT NOT NULL DEFAULT 'llm_config',
                chat_model TEXT NOT NULL DEFAULT '',
                review_model TEXT NOT NULL DEFAULT '',
                embedding_model TEXT NOT NULL DEFAULT '',
                timeout_seconds INTEGER NOT NULL DEFAULT 180,
                max_tokens INTEGER NOT NULL DEFAULT 2000,
                temperature REAL NOT NULL DEFAULT 0.7,
                top_p REAL NOT NULL DEFAULT 0.9,
                top_k INTEGER,
                presence_penalty REAL NOT NULL DEFAULT 0.0,
                frequency_penalty REAL NOT NULL DEFAULT 0.0,
                is_default INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS llm_call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                agent_name TEXT NOT NULL,
                model TEXT NOT NULL,
                request_summary TEXT NOT NULL DEFAULT '',
                response_summary TEXT NOT NULL DEFAULT '',
                success INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL
            );
            """
            )
            _ensure_column(conn, "projects", "estimated_total_sections", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "projects", "default_section_target_words", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "projects", "selected_genre_tags", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_column(conn, "projects", "selected_setting_tags", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_column(conn, "projects", "selected_character_tags", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_column(conn, "projects", "selected_structure_tags", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_column(conn, "projects", "selected_style_tags", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_column(conn, "projects", "selected_forbidden_tags", "TEXT NOT NULL DEFAULT '[]'")
            _ensure_column(conn, "projects", "dialogue_quote_style", "TEXT NOT NULL DEFAULT 'cn_quotes'")
            _ensure_column(conn, "projects", "generation_profile_json", "TEXT NOT NULL DEFAULT ''")
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column in {str(row[1]) for row in rows}:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


_default_store: NovelStore | None = None


def default_store() -> NovelStore:
    global _default_store
    if _default_store is None:
        _default_store = NovelStore(DEFAULT_DB_PATH)
    return _default_store


def create_project(data: dict[str, Any]) -> int:
    return default_store().create_project(data)


def get_project(project_id: int) -> dict[str, Any] | None:
    return default_store().get_project(project_id)


def update_project(project_id: int, data: dict[str, Any]) -> None:
    default_store().update_project(project_id, data)


def list_projects() -> list[dict[str, Any]]:
    return default_store().list_projects()

