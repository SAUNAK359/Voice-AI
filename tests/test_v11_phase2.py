"""V11 Phase 2 contract tests: fail-closed IR and cross-format parity."""
from __future__ import annotations

import pytest
from rizzler.work_ir import compile_ir
from rizzler.work_skills import sectioned, render_one
from rizzler.work_quality import inspect_artifact


def sample():
    return compile_ir("Regional sales report",
        "# Executive summary\nThree verified observations.\n"
        "## Evidence\nThe source data contains two observations.",
        ["https://example.org/research"], {"rows":2,"duplicates":0})


def test_ir_is_deterministic_and_carries_independent_evidence():
    a, b = sample(), sample()
    assert a == b and len(a.sha256) == 64
    assert a.schema_version == 1 and a.dataset_rows == 2
    assert a.dataset_digest
    assert a.sha256 != compile_ir(a.title,a.content,[],{"rows":2}).sha256
    assert a.sha256 != compile_ir(a.title,a.content,list(a.sources),{"rows":3}).sha256


@pytest.mark.parametrize("source",[
    "http://example.org","https://bad.test/\nX-Injected: 1",
    "file:///etc/passwd","https://example.org/" + "x" * 2050,
])
def test_ir_rejects_unsafe_source_metadata(source):
    with pytest.raises(ValueError):
        compile_ir("Report", "# Evidence\nA substantive finding that is documented.",
                   [source])


def test_ir_rejects_silent_truncation_instead_of_omitting_data():
    with pytest.raises(ValueError,match="section"):
        sectioned("# Long\n" + "x" * 8001)
    with pytest.raises(ValueError,match="section"):
        sectioned("\n".join(f"## Section {i}\nContent {i}" for i in range(25)))


def test_all_editable_renderers_share_ir_semantics(tmp_path):
    ir = sample()
    table = (["region","sales"],[["North","10"],["South","20"]])
    for kind in ("md","json","html","docx","pptx","xlsx","pdf"):
        path = tmp_path / ("report." + kind)
        render_one(kind,path,ir.title,ir.content,table,list(ir.sources))
        report = inspect_artifact(path,kind,artifact_ir=ir,
                                  dataset_rows=ir.dataset_rows)
        assert report["passed"] and "format_structure_valid" in report["checks"]
        if kind != "pdf":
            assert report["metrics"]["ir_sha256"] == ir.sha256


def test_semantic_quality_catches_missing_sections_and_source_links(tmp_path):
    ir = sample()
    path = tmp_path / "report.docx"
    render_one("docx",path,ir.title,ir.content,None,list(ir.sources))
    from docx import Document
    doc = Document(path)
    for p in doc.paragraphs:
        if p.text == "Evidence":
            p.text = "Incorrect heading"
        if p.text == "https://example.org/research":
            p.text = "redacted"
    doc.save(path)
    with pytest.raises(ValueError,match="IR"):
        inspect_artifact(path,"docx",artifact_ir=ir)


def test_powerpoint_long_sections_split_without_discarding_words(tmp_path):
    text = "# Findings\n" + " ".join(f"item{i}" for i in range(170))
    ir = compile_ir("Report",text,[])
    path = tmp_path / "long.pptx"
    render_one("pptx",path,ir.title,ir.content,None,[])
    result = inspect_artifact(path,"pptx",artifact_ir=ir)
    assert result["metrics"]["slides"] >= 3
    from pptx import Presentation
    deck = Presentation(path)
    joined = " ".join(sh.text for sl in deck.slides for sh in sl.shapes
                      if sh.has_text_frame)
    assert "item0" in joined and "item169" in joined
