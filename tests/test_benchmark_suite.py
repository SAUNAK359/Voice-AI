"""Offline benchmark harness checks: no cloud keys or GPU required."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib import error
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    path = ROOT / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gemini=load("benchmark_gemini")
asr=load("score_asr")
artifacts=load("benchmark_artifacts")


class FakeStream:
    def __init__(self, lines): self.lines=lines
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def __iter__(self): return iter(self.lines)


class BenchmarkSuiteTests(unittest.TestCase):
    def test_target_is_not_a_measurement(self):
        result=gemini.summarize([])
        self.assertEqual(result["status"],"no_measurements")
        self.assertIsNone(result["ttft_ms"]["p50"])
        self.assertEqual(result["goal"]["target_ms"],564)
        self.assertEqual(result["goal"]["evaluation"],"insufficient_samples")

    def test_only_successful_ttft_counted(self):
        observations=[{"outcome":"ok","ttft_ms":100.0},{"outcome":"error","ttft_ms":1.0}]
        result=gemini.summarize(observations)
        self.assertEqual(result["successful"],1)
        self.assertEqual(result["failed"],1)
        self.assertEqual(result["ttft_ms"]["p50"],100.0)

    def test_mocked_sse_records_first_visible_text(self):
        lines=[b'data: {"candidates":[{"content":{"parts":[{"text":"hidden","thought":true}]}}]}\n',
               b'\n',b'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}\n',
               b'\n',b'data: {"usageMetadata":{"candidatesTokenCount":3}}\n']
        def opener(req,timeout):
            self.assertEqual(req.get_method(),"POST")
            self.assertNotIn("secret123",req.full_url)
            self.assertTrue(req.get_header("X-goog-api-key") or req.get_header("x-goog-api-key"))
            return FakeStream(lines)
        got=gemini.stream_gemini("Hello","gemini-3.5-flash-lite","secret123",opener=opener)
        self.assertEqual(got["outcome"],"ok")
        self.assertEqual(got["output_chars"],5)
        self.assertEqual(got["output_tokens"],3)
        self.assertGreaterEqual(got["ttft_ms"],got["first_event_ms"])
        self.assertNotIn("secret123",str(got))

    def test_mocked_sse_no_visible_text_fails(self):
        def opener(req,timeout):
            return FakeStream([b'data: {"usageMetadata":{"totalTokenCount":12}}\n'])
        got=gemini.stream_gemini("Hello","gemini-3.5-flash-lite","secret123",opener=opener)
        self.assertEqual(got["outcome"],"error")
        self.assertIsNone(got["ttft_ms"])

    def test_dry_run_needs_no_api_key(self):
        self.assertEqual(gemini.main(["--dry-run", "--prompts", str(ROOT/"benchmarks/fixtures/gemini_prompts.jsonl")]),0)

    def test_asr_example(self):
        data=[{"reference":"Hello World!", "hypothesis":"hello world"},
              {"reference":"open the door", "hypothesis":"open door"}]
        s=asr.score(data,"test_fixture")
        self.assertEqual(s["reference_words"],5)
        self.assertAlmostEqual(s["wer"],0.2)
        self.assertTrue(s["cer"]>0)

    def test_asr_empty_reference_rejected(self):
        with self.assertRaises(ValueError):
            asr.score([{"reference":"", "hypothesis":""}],"bad")

    def test_structural_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"report.json").write_text('{"valid":true}')
            (root/"chart.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
            (root/"table.csv").write_text('a,b\n1,2\n')
            with zipfile.ZipFile(root/"bundle.zip","w") as z: z.writestr("note.txt","hello")
            self.assertTrue(all(artifacts.validate(p)["valid"] for p in root.iterdir()))

    def test_corrupt_archive_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/"bad.docx"
            file.write_bytes(b"corrupt")
            self.assertFalse(artifacts.validate(file)["valid"])

if __name__=="__main__":unittest.main()
