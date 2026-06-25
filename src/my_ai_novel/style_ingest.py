"""从参考文本（txt/epub）提炼文风的纯逻辑层。

只做解析、清洗、切块、本地统计和抽样，不调用 LLM、不依赖 UI。
仅用 Python 标准库（zipfile、html.parser、xml、re），不引入第三方依赖。
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# txt 编码探测顺序：先无 BOM 的 utf-8，再常见中文编码。
_TXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5")

# 句子结束标点（中英文）。
_SENTENCE_ENDERS = "。！？!?…"
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?]+|……|…")

# 章节/卷标题行（整行就是标题时丢弃）。
_HEADING_RE = re.compile(
    r"^\s*(?:第\s*[0-9一二三四五六七八九十百千零两]+\s*[章卷节回部篇集话]"
    r"|序章|序言|楔子|尾声|后记|目录|番外|第[0-9]+话)\b.*$"
)

_BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}
_SKIP_TAGS = {"script", "style"}

# 引号：弯引号 “” / 直角引号 「」『』
_QUOTE_SPANS_RE = re.compile(r"“[^”]*”|「[^」]*」|『[^』]*』")


def parse_file(path: str | Path) -> str:
    """读取 txt 或 epub，返回纯文本（保留段落换行）。"""
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix == ".epub":
        return _parse_epub(target)
    return _parse_txt(target)


def _parse_txt(path: Path) -> str:
    data = path.read_bytes()
    for encoding in _TXT_ENCODINGS:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        return _normalize_newlines(text)
    # 全部失败时用 utf-8 容错解码，避免抛错中断分析。
    return _normalize_newlines(data.decode("utf-8", errors="replace"))


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_epub(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        hrefs = _epub_spine_hrefs(zf, names)
        if not hrefs:
            hrefs = sorted(
                name for name in names if name.lower().endswith((".xhtml", ".html", ".htm"))
            )
        parts: list[str] = []
        for href in hrefs:
            try:
                raw = zf.read(href)
            except KeyError:
                continue
            parts.append(_html_to_text(raw.decode("utf-8", errors="replace")))
    return _normalize_newlines("\n".join(parts))


def _epub_spine_hrefs(zf: zipfile.ZipFile, names: list[str]) -> list[str]:
    """按 OPF spine 顺序返回正文 href；解析失败返回空列表（交由调用方兜底）。"""
    opf_name = _epub_opf_name(zf, names)
    if not opf_name:
        return []
    try:
        root = ET.fromstring(zf.read(opf_name))
    except (ET.ParseError, KeyError):
        return []
    base = opf_name.rsplit("/", 1)[0] if "/" in opf_name else ""
    manifest: dict[str, str] = {}
    spine: list[str] = []
    for element in root.iter():
        local = _local_name(element.tag)
        if local == "item":
            item_id = element.get("id")
            href = element.get("href")
            if item_id and href:
                manifest[item_id] = href
        elif local == "itemref":
            idref = element.get("idref")
            if idref:
                spine.append(idref)
    hrefs: list[str] = []
    for idref in spine:
        href = manifest.get(idref)
        if not href:
            continue
        full = f"{base}/{href}" if base else href
        hrefs.append(_normalize_zip_path(full))
    return hrefs


def _epub_opf_name(zf: zipfile.ZipFile, names: list[str]) -> str:
    try:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
    except (ET.ParseError, KeyError):
        return next((name for name in names if name.lower().endswith(".opf")), "")
    for element in container.iter():
        if _local_name(element.tag) == "rootfile":
            full_path = element.get("full-path")
            if full_path:
                return _normalize_zip_path(full_path)
    return next((name for name in names if name.lower().endswith(".opf")), "")


def _normalize_zip_path(path: str) -> str:
    parts: list[str] = []
    for segment in path.replace("\\", "/").split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/".join(parts)


def clean_text(text: str) -> str:
    """去掉整行的章节标题、目录页，并合并多余空行；保留叙述与对白。"""
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        if _HEADING_RE.match(line):
            continue
        lines.append(line)
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return collapsed.strip()


def _paragraphs(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def chunk(text: str, target_chars: int = 3500) -> list[dict[str, Any]]:
    """按段落累积成 ~target_chars 的块，记录每块在全文的相对起点 position(0~1)。"""
    paragraphs = _paragraphs(text)
    total = sum(len(p) for p in paragraphs)
    chunks: list[dict[str, Any]] = []
    if total <= 0:
        return chunks
    buffer: list[str] = []
    buffer_len = 0
    consumed_before = 0
    index = 0

    def flush(start_offset: int) -> None:
        nonlocal index
        if not buffer:
            return
        chunks.append(
            {
                "index": index,
                "position": start_offset / total,
                "text": "\n".join(buffer),
            }
        )
        index += 1

    chunk_start_offset = 0
    for paragraph in paragraphs:
        if not buffer:
            chunk_start_offset = consumed_before
        buffer.append(paragraph)
        buffer_len += len(paragraph)
        consumed_before += len(paragraph)
        if buffer_len >= target_chars:
            flush(chunk_start_offset)
            buffer = []
            buffer_len = 0
    flush(chunk_start_offset)
    return chunks


def sample_chunks(chunks: list[dict[str, Any]], count: int = 12) -> list[dict[str, Any]]:
    """从所有块里均匀抽 count 块，含开头块，按位置升序、结果确定。"""
    if count <= 0:
        return []
    if len(chunks) <= count:
        return list(chunks)
    last = len(chunks) - 1
    picked_indices = sorted({round(i * last / (count - 1)) for i in range(count)})
    # 取整去重后可能少于 count，用未选中的块补足。
    if len(picked_indices) < count:
        for position in range(len(chunks)):
            if len(picked_indices) >= count:
                break
            if position not in picked_indices:
                picked_indices.append(position)
        picked_indices = sorted(set(picked_indices))
    return [chunks[i] for i in picked_indices[:count]]


_BODY_MOTIF_WATCH = (
    "攥紧", "攥", "硌进掌心", "硌", "掌心", "喉咙发紧", "喉结", "喉咙",
    "月光", "石板", "脊背", "指节", "冷汗", "屏住呼吸", "心跳",
)


def overused_motifs(text: str, threshold: int = 2) -> list[str]:
    """从文本里挑出高频（≥threshold 次）的体感意象/身体反应词，供续写时回避重复。"""
    content = text or ""
    return [word for word in _BODY_MOTIF_WATCH if content.count(word) >= threshold]


def text_sha1(text: str) -> str:
    """文本内容的 sha1，用作文风分析缓存键。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文约 0.6 token/字），用于分析前的成本预估。"""
    compact = re.sub(r"\s+", "", text)
    return round(len(compact) * 0.6)


def _split_sentences(text: str) -> list[str]:
    pieces = _SENTENCE_SPLIT_RE.split(text)
    return [piece.strip() for piece in pieces if piece.strip()]


def metrics(text: str) -> dict[str, Any]:
    """本地确定性统计：句长、对白占比、段落句数、标点频率、引号风格。"""
    compact = re.sub(r"\s+", "", text)
    total_chars = len(compact)
    sentences = _split_sentences(text)
    sentence_lengths = [len(s) for s in sentences]
    sentence_count = len(sentence_lengths)
    avg_sentence_len = round(sum(sentence_lengths) / sentence_count, 2) if sentence_count else 0.0

    short = sum(1 for length in sentence_lengths if length < 15)
    long_count = sum(1 for length in sentence_lengths if length > 40)
    mid = sentence_count - short - long_count
    if sentence_count:
        dist = {
            "short": round(short / sentence_count, 3),
            "mid": round(mid / sentence_count, 3),
            "long": round(long_count / sentence_count, 3),
        }
    else:
        dist = {"short": 0.0, "mid": 0.0, "long": 0.0}

    dialogue_chars = sum(max(len(span) - 2, 0) for span in _QUOTE_SPANS_RE.findall(text))
    dialogue_ratio = round(dialogue_chars / total_chars, 3) if total_chars else 0.0

    paragraphs = _paragraphs(text)
    paragraph_sentences = [len(_split_sentences(p)) or 1 for p in paragraphs]
    paragraph_avg_sentences = (
        round(sum(paragraph_sentences) / len(paragraph_sentences), 2) if paragraph_sentences else 0.0
    )

    per_1k = (total_chars / 1000) if total_chars else 1.0
    punct_per_1k = {
        "dash": round(text.count("——") / per_1k, 2),
        "ellipsis": round((text.count("……") + text.count("…")) / per_1k, 2),
        "question": round((text.count("？") + text.count("?")) / per_1k, 2),
        "exclaim": round((text.count("！") + text.count("!")) / per_1k, 2),
    }

    corner = len(re.findall(r"「[^」]*」", text)) + len(re.findall(r"『[^』]*』", text))
    curly = len(re.findall(r"“[^”]*”", text))
    quote_style = "corner_quotes" if corner > curly else "cn_quotes"

    bigrams = [compact[i : i + 2] for i in range(len(compact) - 1)]
    lexical_diversity = round(len(set(bigrams)) / len(bigrams), 3) if bigrams else 0.0

    return {
        "total_chars": total_chars,
        "sentence_count": sentence_count,
        "avg_sentence_len": avg_sentence_len,
        "sentence_len_dist": dist,
        "dialogue_ratio": dialogue_ratio,
        "paragraph_avg_sentences": paragraph_avg_sentences,
        "punct_per_1k": punct_per_1k,
        "quote_style": quote_style,
        "lexical_diversity": lexical_diversity,
    }


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def recommend_sampling(metrics_data: dict[str, Any] | None) -> dict[str, Any]:
    """从本地统计启发式地推荐采样参数（推荐起点，可手调）。

    注意：采样参数是解码控制，无法从成品文本严格反推，这里只做基于
    词汇多样性/句长变化/对白占比的启发式映射；DeepSeek 思考模式下这些参数无效。
    """
    data = metrics_data or {}
    diversity = _to_float(data.get("lexical_diversity"), 0.5)
    dist = data.get("sentence_len_dist") or {}
    concentration = max(
        _to_float(dist.get("short"), 0.0),
        _to_float(dist.get("mid"), 0.0),
        _to_float(dist.get("long"), 0.0),
    )
    variety = 1.0 - concentration  # 句长越分散越大
    dialogue = _to_float(data.get("dialogue_ratio"), 0.2)

    temperature = _clamp(0.85 + 0.4 * (diversity - 0.5) + 0.3 * (variety - 0.4) + 0.15 * (dialogue - 0.2), 0.7, 1.1)
    top_p = _clamp(0.90 + 0.12 * (diversity - 0.5), 0.85, 0.95)
    presence = _clamp(0.2 + 0.5 * (diversity - 0.5), 0.0, 0.5)
    frequency = _clamp(0.3 + 0.5 * (diversity - 0.5), 0.0, 0.6)
    return {
        "temperature": round(temperature, 2),
        "top_p": round(top_p, 2),
        "top_k": 0,
        "presence_penalty": round(presence, 2),
        "frequency_penalty": round(frequency, 2),
        "note": "基于样本词汇多样性/句长变化/对白占比的启发式推荐起点，可手调；DeepSeek 思考模式下这些参数无效。",
    }
