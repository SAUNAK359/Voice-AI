#!/usr/bin/env python3
"""Summarize REAL JSONL events; record no invented successful turns."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from rizzler.metrics import summarize_run

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('events',type=Path,help='JSONL output captured in a real running session')
parser.add_argument('--output',type=Path,help='Output JSON file')
args=parser.parse_args()
rows=[]
for lineno,line in enumerate(args.events.read_text(encoding='utf-8').splitlines(),1):
    if not line.strip():continue
    entry=json.loads(line)
    # Most Rizzler logs store their terminal metrics as a `turn_complete` event.
    if entry.get('event') not in ('turn_complete','voice_turn_complete'):
        continue
    row={'outcome':entry.get('outcome')}
    mappings={
        'asr_ms':('asr_ms',),
        'gemini_ttft_ms':('gemini_ttft_ms','llm_first_text_ms','ttft_ms'),
        'tts_first_pcm_ms':('tts_first_pcm_ms','tts_first_audio_ms'),
        'post_pause_first_audio_ms':('post_pause_first_audio_ms','first_audio_ms'),
        'e2e_ms':('e2e_ms','duration_ms'),
    }
    for dst,aliases in mappings.items():
        for k in aliases:
            if isinstance(entry.get(k),(int,float)):
                row[dst]=entry[k];break
    rows.append(row)
report={'kind':'observed-notebook-events','source':str(args.events),'statistics':summarize_run(rows),
        'caveats':['Only rows with outcome=ok contribute to stage latency summaries.',
                   'No browser-audio-played timestamp unless instrumented by frontend.',
                   'This is not a GPU performance measurement unless events came from a live GPU run.']}
if args.output:
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
