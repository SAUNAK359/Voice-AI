#!/usr/bin/env python3
"""Structural artifact validity checks; no claims about accuracy or aesthetics."""
from __future__ import annotations
import argparse
import csv
import io
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

VALID_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".json",
                    ".md", ".html", ".png", ".svg", ".txt", ".zip"}


def validate(path: Path) -> dict:
    ext = path.suffix.lower()
    outcome = {"name": path.name, "format": ext, "valid": False, "check": None}
    if ext not in VALID_EXTENSIONS or not path.is_file() or path.stat().st_size == 0:
        outcome["check"] = "unsupported_missing_or_empty"; return outcome
    try:
        if ext == ".pdf":
            outcome["valid"] = path.read_bytes().startswith(b"%PDF-")
            outcome["check"] = "pdf_magic_only"
        elif ext == ".png":
            outcome["valid"] = path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            outcome["check"] = "png_magic_only"
        elif ext in {".docx", ".pptx", ".xlsx", ".zip"}:
            expected = {".docx": "word/document.xml", ".pptx": "ppt/presentation.xml",
                        ".xlsx": "xl/workbook.xml"}.get(ext)
            with zipfile.ZipFile(path) as z:
                outcome["valid"] = z.testzip() is None and (expected is None or expected in z.namelist())
            outcome["check"] = "zip_crc_and_ooxml_structure"
        elif ext == ".json":
            json.loads(path.read_text(encoding="utf-8"))
            outcome["valid"] = True;outcome["check"] = "json_parse"
        elif ext == ".csv":
            with path.open(encoding="utf-8",newline="") as stream:
                rows = list(csv.reader(stream))
            outcome["valid"] = bool(rows) and len(rows[0]) > 0 and all(len(r) == len(rows[0]) for r in rows)
            outcome["check"] = "consistent_csv_columns"
        elif ext == ".svg":
            node=ET.parse(path).getroot()
            outcome["valid"] = node.tag.endswith("}svg") or node.tag == "svg"
            outcome["check"] = "svg_xml_root"
        elif ext in {".html", ".md", ".txt"}:
            outcome["valid"] = bool(path.read_text(encoding="utf-8").strip())
            outcome["check"] = "nonblank_utf8"
    except (OSError, ValueError, UnicodeError, zipfile.BadZipFile, ET.ParseError):
        outcome["valid"] = False
        outcome["check"] = "parse_failed"
    return outcome


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args(argv)
    if not args.directory.is_dir():
        parser.error("Directory not found")
    files=[p for p in sorted(args.directory.iterdir()) if p.is_file() and p.suffix.lower() in VALID_EXTENSIONS]
    if not files:
        parser.error("No supported artifact files")
    results=[validate(p) for p in files]
    report={"kind":"offline_artifact_structural_check", "files":len(results),
            "valid":sum(x["valid"] for x in results), "invalid":sum(not x["valid"] for x in results),
            "limitations":"Structural checks only; do not establish content correctness or visual quality",
            "results":results}
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))
    return 0 if report["invalid"] == 0 else 1


if __name__=="__main__":
    raise SystemExit(main())
