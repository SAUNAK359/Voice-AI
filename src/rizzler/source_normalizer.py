"""Bounded source normalization: evidence is data, never trusted instructions.

Call with bytes that have already passed upload or network-egress authorization.
This module does not fetch arbitrary URLs. Extracted blocks retain original
section/page coordinates so downstream researchers can independently verify them.
"""
from __future__ import annotations

import csv
import hashlib
from html.parser import HTMLParser
import io
import json
import re
import zipfile
from typing import Any

MAX_SOURCE_BYTES = 8_000_000
MAX_BLOCKS = 1200
MAX_TABLE_ROWS = 1000
MAX_BLOCK_CHARS = 6000


def _clean(value: Any, limit: int = MAX_BLOCK_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.current = None
        self.buffer: list[str] = []
        self.blocks: list[dict] = []
        self.tables: list[list[list[str]]] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "noscript", "svg", "template"):
            self.hidden += 1
            return
        if self.hidden:
            return
        if tag == "table":
            self._flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag in ("h1", "h2", "h3", "h4", "p", "li", "blockquote", "pre"):
            self._flush()
            self.current = tag
        elif tag == "br" and self.current:
            self.buffer.append(" ")

    def handle_data(self, data):
        if self.hidden:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif self.current is not None:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "noscript", "svg", "template"):
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(_clean(" ".join(self.cell), 1000))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            if len(self.table) < MAX_TABLE_ROWS:
                self.table.append(self.row[:50])
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.table and len(self.tables) < 30:
                self.tables.append(self.table)
            self.table = None
        elif tag == self.current:
            self._flush()

    def _flush(self):
        if self.current:
            text = _clean(" ".join(self.buffer))
            if text and len(self.blocks) < MAX_BLOCKS:
                self.blocks.append({"type": "heading" if self.current.startswith("h") else "text",
                                    "text": text, "location": {"block": len(self.blocks)}})
        self.current, self.buffer = None, []


def _markdown(value: str) -> tuple[list[dict], list[dict]]:
    blocks: list[dict] = []
    tables: list[dict] = []
    lines = value.splitlines()
    paragraph: list[str] = []
    in_code = False

    def flush():
        if paragraph and len(blocks) < MAX_BLOCKS:
            text = _clean(" ".join(paragraph))
            if text:
                blocks.append({"type": "text", "text": text,
                               "location": {"block": len(blocks)}})
            paragraph.clear()

    idx = 0
    while idx < len(lines) and len(blocks) < MAX_BLOCKS:
        line = lines[idx].strip()
        if line.startswith(("~~~", "```")):
            flush()
            in_code = not in_code
            idx += 1
            continue
        if in_code:
            paragraph.append(line)
        elif re.match(r"^#{1,6} ", line):
            flush()
            blocks.append({"type": "heading", "text": _clean(line.lstrip("# ")),
                           "location": {"line": idx + 1}})
        elif "|" in line and idx + 1 < len(lines) and re.match(
                r"^\s*\|?\s*:?-{3,}:?\s*\|", lines[idx + 1]):
            flush()
            header = [x.strip() for x in line.strip("|").split("|")]
            idx += 2
            rows = [header]
            while idx < len(lines) and "|" in lines[idx] and len(rows) < MAX_TABLE_ROWS:
                rows.append([_clean(x, 1000) for x in lines[idx].strip().strip("|").split("|")])
                idx += 1
            tables.append({"rows": rows, "location": {"line": idx + 1 - len(rows)}})
            continue
        elif not line:
            flush()
        else:
            paragraph.append(line)
        idx += 1
    flush()
    return blocks, tables


def normalize_source(data: bytes, mime_type: str, *, source_id: str,
                     source_url: str | None = None) -> dict:
    """Turn an authorized source into typed blocks, tables and extraction warnings.

    No OCR, network access, instruction execution or unsourced fact verification.
    Parsed content is always untrusted; use a separate evidence/verifier stage.
    """
    from .research_evidence import safe_source_url

    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds authorized byte budget")
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", source_id):
        raise ValueError("Invalid source identifier")
    if source_url is not None and safe_source_url(source_url) != source_url:
        raise ValueError("Unsafe or noncanonical source reference")
    media = mime_type.split(";", 1)[0].strip().lower()
    blocks: list[dict] = []
    tables: list[dict] = []
    warnings: list[str] = []
    if media == "application/pdf":
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF extraction requires PyMuPDF") from exc
        with fitz.open(stream=data, filetype="pdf") as doc:
            if not 1 <= len(doc) <= 250:
                raise ValueError("PDF page count outside extraction bounds")
            for page_num, page in enumerate(doc):
                body = page.get_text("text", sort=True)
                if body.strip():
                    blocks.append({"type": "text", "text": body[:MAX_BLOCK_CHARS],
                                   "location": {"page": page_num + 1}})
                    if len(body) > MAX_BLOCK_CHARS:
                        warnings.append("page_text_truncated:" + str(page_num + 1))
                else:
                    warnings.append("page_without_extractable_text:" + str(page_num + 1))
                # Table extraction is bounded and isolated per page; malformed
                # ruled tables must not discard otherwise readable page text.
                try:
                    discovered = page.find_tables()
                    for table in list(discovered.tables)[:15]:
                        rows = table.extract()[:MAX_TABLE_ROWS]
                        rows = [[_clean(v or "", 1000) for v in row[:50]]
                                for row in rows]
                        if rows:
                            tables.append({"rows": rows,
                                           "location": {"page": page_num + 1,
                                                        "table": len(tables) + 1}})
                except (AttributeError, RuntimeError, ValueError):
                    warnings.append("pdf_table_detection_unavailable:" + str(page_num + 1))
        if not blocks:
            warnings.append("ocr_or_vlm_required")
    elif media in ("text/html", "application/xhtml+xml"):
        text = data.decode("utf-8-sig", errors="replace")
        parser = _HTML()
        parser.feed(text)
        parser.close()
        parser._flush()
        blocks = parser.blocks
        tables = [{"rows": rows, "location": {"table": i + 1}}
                  for i, rows in enumerate(parser.tables)]
        # Fallback to article/main-content extraction for sites that wrap
        # meaningful text in nonsemantic divs instead of p/article headings.
        # Extractors are never allowed to execute page scripts or remote links.
        if sum(len(item["text"]) for item in blocks) < 200:
            try:
                import trafilatura
                article = trafilatura.extract(text, include_tables=True,
                                              include_comments=False)
                if article and len(article) > sum(len(item["text"]) for item in blocks):
                    more, extra_tables = _markdown(article[:MAX_SOURCE_BYTES])
                    if more:
                        blocks = more
                        tables.extend(extra_tables)
                        warnings.append("article_extractor_fallback")
            except ImportError:
                warnings.append("article_extractor_not_installed")
            except Exception:
                warnings.append("article_extractor_failed")
        if not blocks:
            warnings.append("html_without_readable_main_text")
    elif media in ("text/markdown", "text/x-markdown", "text/plain"):
        blocks, tables = _markdown(data.decode("utf-8-sig", errors="replace"))
    elif media in ("text/csv", "application/csv"):
        content = data.decode("utf-8-sig", errors="strict")
        rows = list(csv.reader(io.StringIO(content)))
        if not rows or len(rows) > MAX_TABLE_ROWS or max(map(len, rows)) > 50:
            raise ValueError("CSV table outside extraction bounds")
        tables = [{"rows": rows, "location": {"table": 1}}]
    elif media == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        from openpyxl import load_workbook
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 500 or sum(v.file_size for v in entries) > 30_000_000:
                    raise ValueError("Spreadsheet expansion exceeds source budget")
                if any(v.filename.startswith("/") or ".." in v.filename.split("/")
                       or v.filename.lower().endswith(("vbaproject.bin", ".exe", ".dll"))
                       or v.filename.startswith("xl/externalLinks/")
                       for v in entries):
                    raise ValueError("Unsafe spreadsheet package")
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid spreadsheet archive") from exc
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True,
                                 keep_links=False)
        try:
            if len(workbook.sheetnames) > 30:
                raise ValueError("Workbook has too many sheets")
            for sheet in workbook:
                row_limit = sheet.max_row or MAX_TABLE_ROWS
                col_limit = sheet.max_column or 50
                if row_limit > MAX_TABLE_ROWS or col_limit > 50:
                    warnings.append("sheet_truncated:" + sheet.title[:80])
                rows = []
                for row in sheet.iter_rows(min_row=1, max_row=min(row_limit, MAX_TABLE_ROWS),
                                           max_col=min(col_limit, 50), values_only=True):
                    rows.append([_clean(v if v is not None else "", 1000) for v in row])
                if rows:
                    tables.append({"rows": rows, "location": {"sheet": sheet.title[:80]}})
        finally:
            workbook.close()
    elif media in ("application/json", "application/ld+json"):
        obj = json.loads(data.decode("utf-8-sig"))
        if isinstance(obj, dict):
            for key, value in list(obj.items())[:MAX_BLOCKS]:
                blocks.append({"type": "text", "text": _clean(
                    key + ": " + json.dumps(value, ensure_ascii=False)),
                    "location": {"json_key": key[:120]}})
        elif isinstance(obj, list):
            for i, value in enumerate(obj[:MAX_BLOCKS]):
                blocks.append({"type": "text", "text": _clean(
                    json.dumps(value, ensure_ascii=False)), "location": {"item": i}})
        else:
            blocks.append({"type": "text", "text": _clean(obj), "location": {"item": 0}})
    else:
        raise ValueError("Unsupported source content type")
    if len(blocks) > MAX_BLOCKS:
        blocks = blocks[:MAX_BLOCKS]
        warnings.append("blocks_truncated")
    return {"schema_version": 1, "source_id": source_id,
            "source_url": source_url,
            "content_type": media, "sha256": hashlib.sha256(data).hexdigest(),
            "blocks": blocks, "tables": tables, "warnings": warnings,
            "provenance": "authorized_source_bytes_unverified"}
