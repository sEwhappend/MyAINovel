from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .project_files import ensure_project_structure, sanitize_filename


WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NAMESPACE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"


def export_full_book_docx(store: Any, project_id: int) -> Path:
    project = store.get_project(project_id)
    if project is None:
        raise ValueError(f"project not found: {project_id}")

    projects_root = getattr(store, "projects_root", None)
    project_dir = ensure_project_structure(project, projects_root) if projects_root else ensure_project_structure(project)
    export_dir = project_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    title = str(project.get("title") or f"project-{project_id}")
    output_path = export_dir / f"{sanitize_filename(title)}-全书.docx"

    paragraphs: list[str] = [title]
    for chapter in store.list_chapters(project_id):
        finalized_sections = [
            (section, _finalized_version(store, section))
            for section in store.list_sections(int(chapter["id"]))
            if section.get("status") == "finalized" and section.get("finalized_version_id")
        ]
        finalized_sections = [
            (section, version)
            for section, version in finalized_sections
            if version is not None
        ]
        if not finalized_sections:
            continue

        chapter_title = _numbered_title("第{number}章", chapter)
        paragraphs.append(chapter_title)
        for section, version in finalized_sections:
            section_title = _numbered_title("第{number}节", section)
            if section_title:
                paragraphs.append(section_title)
            paragraphs.extend(_content_paragraphs(str(version.get("content") or "")))

    _write_docx(output_path, paragraphs)
    return output_path


def _finalized_version(store: Any, section: dict[str, Any]) -> dict[str, Any] | None:
    version_id = section.get("finalized_version_id")
    if not version_id:
        return None
    if hasattr(store, "get_version"):
        version = store.get_version(int(version_id))
        if version and int(version["id"]) == int(version_id):
            return version

    for version in store.list_versions(
        int(section.get("project_id", 0) or 0),
        section_id=int(section["id"]),
    ):
        if int(version.get("id", 0)) == int(version_id):
            return version
    return None


def _numbered_title(prefix_template: str, item: dict[str, Any]) -> str:
    number = item.get("number")
    title = str(item.get("title") or "").strip()
    if number:
        prefix = prefix_template.format(number=number)
        return f"{prefix} {title}".strip()
    return title


def _content_paragraphs(content: str) -> list[str]:
    if not content.strip():
        return []
    return [line.rstrip() for line in content.splitlines()]


def _write_docx(path: Path, paragraphs: Iterable[str]) -> None:
    document_xml = _document_xml(paragraphs)
    with ZipFile(path, "w", ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", _content_types_xml())
        docx.writestr("_rels/.rels", _package_rels_xml())
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("word/_rels/document.xml.rels", _document_rels_xml())


def _document_xml(paragraphs: Iterable[str]) -> str:
    body = "\n".join(_paragraph_xml(paragraph) for paragraph in paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{WORD_NAMESPACE}">\n'
        "<w:body>\n"
        f"{body}\n"
        "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar "
        "w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" "
        "w:header=\"720\" w:footer=\"720\" w:gutter=\"0\"/></w:sectPr>\n"
        "</w:body>\n"
        "</w:document>\n"
    )


def _paragraph_xml(text: str) -> str:
    escaped = escape(text, {'"': "&quot;", "'": "&apos;"})
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f"<w:p><w:r><w:t{space}>{escaped}</w:t></w:r></w:p>"


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>\n"
    )


def _package_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{PACKAGE_REL_NAMESPACE}">'
        f'<Relationship Id="rId1" Type="{REL_NAMESPACE}/officeDocument" Target="word/document.xml"/>'
        "</Relationships>\n"
    )


def _document_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{PACKAGE_REL_NAMESPACE}"></Relationships>\n'
    )
