import io
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from my_ai_novel.style_ingest import (
    chunk,
    clean_text,
    estimate_tokens,
    metrics,
    parse_file,
    recommend_sampling,
    sample_chunks,
    text_sha1,
)


def _make_epub(path: Path) -> None:
    container = (
        '<?xml version="1.0"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles>\n'
        "</container>\n"
    )
    opf = (
        '<?xml version="1.0"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">\n'
        "  <manifest>\n"
        '    <item id="c2" href="chap2.xhtml" media-type="application/xhtml+xml"/>\n'
        '    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>\n'
        "  </manifest>\n"
        "  <spine>\n"
        '    <itemref idref="c1"/>\n'
        '    <itemref idref="c2"/>\n'
        "  </spine>\n"
        "</package>\n"
    )
    chap1 = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title>'
        "<script>var secret=1;</script></head>"
        "<body><h1>第一章</h1><p>他推开门，雨水灌进来。</p>"
        "<p>“谁在那里？”她低声问。</p></body></html>"
    )
    chap2 = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>第二段正文在这里。</p></body></html>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/chap1.xhtml", chap1)
        zf.writestr("OEBPS/chap2.xhtml", chap2)


class ParseFileTests(unittest.TestCase):
    def test_parse_file_reads_utf8_txt(self) -> None:
        path = Path(self._tmp("u.txt"))
        path.write_text("他推开门。\n雨水灌进来。", encoding="utf-8")
        self.assertIn("他推开门", parse_file(path))

    def test_parse_file_detects_gbk_txt(self) -> None:
        path = Path(self._tmp("g.txt"))
        path.write_bytes("第一章 风雪夜归人".encode("gbk"))
        text = parse_file(path)
        self.assertIn("风雪夜归人", text)

    def test_parse_file_reads_epub_in_spine_order_and_strips_tags(self) -> None:
        path = Path(self._tmp("book.epub"))
        _make_epub(path)
        text = parse_file(path)
        self.assertIn("他推开门", text)
        self.assertIn("谁在那里", text)
        self.assertIn("第二段正文", text)
        self.assertNotIn("secret", text)  # <script> content stripped
        # spine order: chap1 before chap2
        self.assertLess(text.index("他推开门"), text.index("第二段正文"))

    def _tmp(self, name: str) -> str:
        import tempfile

        return str(Path(tempfile.mkdtemp()) / name)


class CleanTextTests(unittest.TestCase):
    def test_clean_removes_chapter_headings(self) -> None:
        raw = "第1章 开端\n他推开门，雨水灌进来。\n第二十三章 终\n她转身离开。"
        cleaned = clean_text(raw)
        self.assertNotIn("第1章", cleaned)
        self.assertNotIn("第二十三章", cleaned)
        self.assertIn("他推开门", cleaned)
        self.assertIn("她转身离开", cleaned)

    def test_clean_collapses_blank_lines(self) -> None:
        cleaned = clean_text("一段。\n\n\n\n二段。")
        self.assertNotIn("\n\n\n", cleaned)


class ChunkTests(unittest.TestCase):
    def test_chunk_splits_by_target_and_records_position(self) -> None:
        paras = "\n".join(f"第{i}段。" + "字" * 50 for i in range(40))
        chunks = chunk(paras, target_chars=400)
        self.assertGreater(len(chunks), 1)
        positions = [c["position"] for c in chunks]
        self.assertEqual(positions, sorted(positions))
        self.assertGreaterEqual(positions[0], 0.0)
        self.assertLess(positions[-1], 1.0)
        for c in chunks:
            self.assertTrue(c["text"].strip())

    def test_chunk_single_when_short(self) -> None:
        chunks = chunk("很短的一段。", target_chars=3500)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["position"], 0.0)


class MetricsTests(unittest.TestCase):
    def test_metrics_basic_shape(self) -> None:
        text = "他推开门。雨水灌进来。“谁在那里？”她低声问。"
        m = metrics(text)
        self.assertGreater(m["avg_sentence_len"], 0)
        self.assertIn("short", m["sentence_len_dist"])
        self.assertGreaterEqual(m["dialogue_ratio"], 0.0)
        self.assertLessEqual(m["dialogue_ratio"], 1.0)
        self.assertIn("question", m["punct_per_1k"])

    def test_metrics_dialogue_ratio_detects_quotes(self) -> None:
        text = "旁白没有引号。" + "“" + "对" * 30 + "”"
        self.assertGreater(metrics(text)["dialogue_ratio"], 0.5)

    def test_metrics_quote_style_corner(self) -> None:
        self.assertEqual(metrics("「你好」他说。").get("quote_style"), "corner_quotes")

    def test_metrics_quote_style_curly(self) -> None:
        self.assertEqual(metrics("“你好”他说。").get("quote_style"), "cn_quotes")


class SampleChunksTests(unittest.TestCase):
    def test_sample_chunks_even_and_capped(self) -> None:
        chunks = chunk("\n".join(f"第{i}段。" + "字" * 50 for i in range(60)), target_chars=120)
        picked = sample_chunks(chunks, count=5)
        self.assertEqual(len(picked), 5)
        # deterministic and ascending by position
        positions = [c["position"] for c in picked]
        self.assertEqual(positions, sorted(positions))
        # includes the opening chunk
        self.assertEqual(picked[0]["index"], chunks[0]["index"])

    def test_sample_chunks_returns_all_when_fewer(self) -> None:
        chunks = chunk("\n".join(f"第{i}段。" + "字" * 50 for i in range(3)), target_chars=120)
        picked = sample_chunks(chunks, count=12)
        self.assertEqual(len(picked), len(chunks))


class SamplingTests(unittest.TestCase):
    def test_metrics_includes_lexical_diversity(self) -> None:
        repetitive = metrics("啊" * 200)
        varied = metrics("他推开门，雨水灌进来，她转身离开，灯光摇晃，远处传来钟声。" * 8)
        self.assertGreaterEqual(repetitive["lexical_diversity"], 0.0)
        self.assertLessEqual(varied["lexical_diversity"], 1.0)
        self.assertLess(repetitive["lexical_diversity"], varied["lexical_diversity"])

    def test_recommend_sampling_keys_and_ranges(self) -> None:
        rec = recommend_sampling({"lexical_diversity": 0.6, "dialogue_ratio": 0.25,
                                  "sentence_len_dist": {"short": 0.4, "mid": 0.4, "long": 0.2}})
        for key in ("temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty"):
            self.assertIn(key, rec)
        self.assertGreaterEqual(rec["temperature"], 0.7)
        self.assertLessEqual(rec["temperature"], 1.1)
        self.assertGreaterEqual(rec["top_p"], 0.85)
        self.assertLessEqual(rec["top_p"], 0.95)
        self.assertGreaterEqual(rec["presence_penalty"], 0.0)
        self.assertLessEqual(rec["frequency_penalty"], 0.6)

    def test_recommend_sampling_higher_diversity_raises_temperature(self) -> None:
        low = recommend_sampling({"lexical_diversity": 0.2})
        high = recommend_sampling({"lexical_diversity": 0.95})
        self.assertLess(low["temperature"], high["temperature"])

    def test_recommend_sampling_handles_empty_metrics(self) -> None:
        rec = recommend_sampling({})
        self.assertGreaterEqual(rec["temperature"], 0.7)
        self.assertLessEqual(rec["temperature"], 1.1)


class HelperTests(unittest.TestCase):
    def test_overused_motifs_flags_repeated(self) -> None:
        from my_ai_novel.style_ingest import overused_motifs
        flags = overused_motifs("月光" * 3 + "她攥紧手，又攥紧。剩下是普通叙述句子。")
        self.assertIn("月光", flags)
        self.assertIn("攥", flags)
        self.assertEqual(overused_motifs("一段没有重复体感意象的普通叙述。"), [])

    def test_text_sha1_is_stable_and_content_sensitive(self) -> None:
        self.assertEqual(text_sha1("他推开门。"), text_sha1("他推开门。"))
        self.assertNotEqual(text_sha1("他推开门。"), text_sha1("她推开门。"))

    def test_estimate_tokens_positive_and_ignores_whitespace(self) -> None:
        self.assertGreater(estimate_tokens("字" * 100), 0)
        self.assertEqual(estimate_tokens("字\n字\n字"), estimate_tokens("字字字"))


REAL_SAMPLE_DIR = ROOT / "风格化参考文本"


class RealSampleBooksTests(unittest.TestCase):
    @unittest.skipUnless(REAL_SAMPLE_DIR.is_dir(), "no 风格化参考文本/ dir")
    def test_real_books_parse_clean_chunk_metrics(self) -> None:
        books = sorted(REAL_SAMPLE_DIR.glob("*.txt"))
        if not books:
            self.skipTest("no .txt sample books present")
        for book in books:
            text = clean_text(parse_file(book))
            self.assertGreater(len(text), 100_000)
            chunks = chunk(text)
            self.assertGreater(len(chunks), 10)
            picked = sample_chunks(chunks, count=12)
            self.assertLessEqual(len(picked), 12)
            m = metrics(text)
            self.assertGreater(m["avg_sentence_len"], 0)
            self.assertGreaterEqual(m["dialogue_ratio"], 0.0)
            self.assertLessEqual(m["dialogue_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
