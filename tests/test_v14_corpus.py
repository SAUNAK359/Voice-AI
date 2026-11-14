"""Model-directed Work source coverage and checkpoint replay integration."""
import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rizzler.source_index import SourceIndex
from rizzler.work_store import WorkStore,Missing

class CorpusWorkTests(unittest.TestCase):
    def test_work_job_persists_scope_and_blocks_cross_owner_source(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{"RIZZLER_AGENTIC_ENABLED":"1"}):
            store=WorkStore(root)
            source=SourceIndex(root).register("owner","research.md",
                      ("## Operations\nEvidence is traceable.\n"*100).encode())
            job=store.submit("owner","Analyze all operational findings",
                             ["md"],"corpus_job_001",[],[source["id"]],"complete")
            scope=store.specification("owner",job["id"])
            self.assertEqual(scope["source_ids"],[source["id"]])
            self.assertEqual(scope["source_coverage"],"complete")
            with self.assertRaises(Missing):
                store.submit("other","Analyze those records",
                    ["md"],"corpus_job_002",[],[source["id"]],"complete")

    def test_full_corpus_is_mapped_and_cached_without_provider_on_replay(self):
        from rizzler.work_corpus import analyze
        from rizzler.work_dynamic import WorkModelConfig
        from google import genai
        count=[0]
        class FakeClient:
            def __init__(self):
                class Models:
                    async def generate_content(self,model,contents,config):
                        count[0]+=1
                        return SimpleNamespace(text="Evidence: The source was reviewed and material is traceable. "
                             "Findings: All cited portions are represented. Contradictions: none stated.")
                async def close():pass
                self.aio=SimpleNamespace(models=Models(),aclose=close)
        with tempfile.TemporaryDirectory() as root:
            store=WorkStore(root)
            source=SourceIndex(root).register("owner","body.txt",
                ("A warehouse finding with inventory measurements and stable attribution.\n"*1300).encode())
            cfg=WorkModelConfig("mock-key","gemini-test-model",45)
            with patch.object(WorkModelConfig,"from_env",return_value=cfg),\
                 patch.object(genai,"Client",return_value=FakeClient()),\
                 patch("rizzler.production_guard.reserve_provider_call"):
                first=asyncio.run(analyze(store,"owner","Explain all findings",
                                           [source["id"]],"complete"))
                calls=count[0]
                second=asyncio.run(analyze(store,"owner","Explain all findings",
                                            [source["id"]],"complete"))
            self.assertEqual(first["coverage"],"all_indexed_text_passages")
            self.assertEqual(first["passages_total"],first["passages_examined"])
            self.assertGreater(calls,1)
            self.assertEqual(count[0],calls)
            self.assertEqual(second["passages_examined"],first["passages_examined"])

    def test_cross_worker_source_hydration_from_private_object_store(self):
        from rizzler.work_corpus import analyze
        import hashlib
        from pathlib import Path
        class PrivateObjects:
            def __init__(self):self.data={}
            def put(self,key,path,digest,size):
                data=Path(path).read_bytes()
                assert hashlib.sha256(data).hexdigest()==digest and len(data)==size
                self.data[key]=data
            def get(self,key,path,digest,size):
                data=self.data[key]
                assert hashlib.sha256(data).hexdigest()==digest and len(data)==size
                Path(path).parent.mkdir(parents=True,exist_ok=True)
                Path(path).write_bytes(data)
        with tempfile.TemporaryDirectory() as one,tempfile.TemporaryDirectory() as two:
            remote=PrivateObjects()
            source=SourceIndex(one).register("owner","remote.txt",
                ("Independent worker should retrieve the source accurately.\n"*60).encode(),
                objects=remote)
            api=WorkStore(one,object_store=remote)
            job=api.submit("owner","Read my independent worker source",
                ["md"],"cross_worker_001",[],[source["id"]],"targeted")
            receipts=api.specification("owner",job["id"])["source_refs"]
            worker=WorkStore(two,object_store=remote)
            report=asyncio.run(analyze(worker,"owner","independent worker",
                                [source["id"]],"targeted",receipts))
            self.assertEqual(report["coverage"],"retrieved_excerpts_only")
            self.assertIn("source",report["text"])
            self.assertEqual(SourceIndex(two).list("owner")[0]["sha256"],source["metadata"].get("sha256",
                hashlib.sha256(("Independent worker should retrieve the source accurately.\n"*60).encode()).hexdigest()))

    def test_targeted_scope_never_claims_complete_coverage(self):
        from rizzler.work_corpus import analyze
        with tempfile.TemporaryDirectory() as root:
            store=WorkStore(root)
            source=SourceIndex(root).register("owner","body.md",
                      ("Inventories are evaluated on real input rows.\n"*2000).encode())
            result=asyncio.run(analyze(store,"owner","inventory",[source["id"]],"targeted"))
            self.assertEqual(result["coverage"],"retrieved_excerpts_only")
            self.assertLess(result["passages_examined"],result["passages_total"])
if __name__=="__main__":unittest.main()
