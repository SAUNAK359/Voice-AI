#!/usr/bin/env python3
"""Offline validation of the canonical native V11 Kaggle launcher.

No package installation, networking, model loading or secret access occurs.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
NOTEBOOK=ROOT/"notebooks"/"Rizzler_V11_Unified_Native_Kaggle.ipynb"


def validate(path: Path = NOTEBOOK) -> dict:
    notebook=json.loads(path.read_text(encoding="utf-8"))
    if notebook.get("nbformat")!=4:
        raise ValueError("Unsupported notebook format")
    cells=notebook.get("cells")
    if not isinstance(cells,list) or not 5<=len(cells)<=16:
        raise ValueError("Native notebook must be bounded and complete")
    code=[]
    for index,cell in enumerate(cells):
        if cell.get("cell_type") not in ("code","markdown") or cell.get("outputs"):
            raise ValueError("Invalid or executable notebook outputs")
        if cell["cell_type"]=="code":
            text="".join(cell.get("source",[]))
            ast.parse(text,filename=f"native-notebook:cell[{index}]")
            code.append(text)
    combined="\n".join(code)
    needed=("UserSecretsClient","GEMINI_API_KEY","RIZZLER_ACCESS_KEY",
            "RIZZLER_WORK_SIGNING_KEY","RIZZLER_MEMORY_ENABLED",
            "RIZZLER_MEMORY_KEY","Settings.from_env","rizzler.api",
            "rizzler.work_worker","--root","/ready","/api/auth",
            "/api/runtime","/api/voice/tools","voice_prewarm",
            "git","clone","sys.executable")
    if any(term not in combined for term in needed):
        raise ValueError("Native launcher missing required single-runtime component")
    forbidden=("RIZZLER_V5_APP = FastAPI(", "from fastrtc import", "import fastrtc",
               "kaggle_secrets.UserSecretsClient().get_secret('')")
    if any(text in combined for text in forbidden):
        raise ValueError("Legacy notebook or unsafe secret wiring reintroduced")
    if combined.count("subprocess.Popen(")!=1:
        raise ValueError("Native processes must use exactly one supervised launcher")
    if "Data loss" in combined:
        raise ValueError("Unreviewed notebook warning")
    return {"cells":len(cells),"code_cells":len(code),
            "uses_native_runtime":True,"live_gpu_proven":False}


if __name__=="__main__":
    print(json.dumps(validate(),sort_keys=True))
