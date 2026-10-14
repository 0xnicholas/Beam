#!/usr/bin/env python
"""Measure per-token keep probabilities with a compression checkpoint.

Mirrors tokencamp-pro/sidecars/refine/compressor.py `_compress_one`
exactly (special tokens -> 1.0, fact/code spans -> 1.0, keep <=> p >= level)
and prints one JSON blob holding, per input text:

  - every token with its surface form, keep probability and force-keep flag
  - the retained count, retention and decoded text at each swept level
  - which numeric facts survive the harness's verbatim check

Run it from the training venv (torch + transformers), offline:

  HF_HUB_OFFLINE=1 .venv-train/bin/python assets/repro/keep-probability-trace.py \
    --model ../tokencamp-pro/sidecars/refine/models/models--microsoft--\
llmlingua-2-bert-base-multilingual-cased-meetingbank/snapshots/<rev> \
    --text "..." --levels 0.1 0.2 0.3 0.4 0.5

Used by lessons/0001 to produce assets/data/trace-zh.js and trace-en.js.
"""
from __future__ import annotations

import argparse
import json
import re

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

# Verbatim copy of refiner._FACT_PATTERN (the runtime's force-keep rule).
FACT_PATTERN = re.compile(r"#[\w-]+|\d+(?:[.,:/-]\d+)*%?")


def trace(model_dir: str, texts: dict[str, str], levels: list[float]) -> dict:
    tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForTokenClassification.from_pretrained(model_dir, local_files_only=True)
    model.eval()

    out: dict[str, dict] = {}
    for name, text in texts.items():
        enc = tok(text, return_tensors="pt", return_offsets_mapping=True)
        offsets = enc.pop("offset_mapping")[0]
        with torch.no_grad():
            logits = model(**enc).logits
        probs = torch.softmax(logits, dim=-1)[0, :, 1]

        ids = enc["input_ids"][0]
        special_ids = {tok.cls_token_id, tok.sep_token_id}
        special_mask = torch.tensor([int(t) in special_ids for t in ids])
        probs[special_mask] = 1.0

        fact_spans = [m.span() for m in FACT_PATTERN.finditer(text)]
        fact_mask = torch.tensor(
            [any(ts < fe and fs < te for fs, fe in fact_spans) for ts, te in offsets.tolist()]
        )
        probs[fact_mask] = 1.0

        rows = [
            {
                "token": tok.convert_ids_to_tokens(int(tid)),
                "surface": text[ts:te],
                "start": ts,
                "end": te,
                "p": round(float(probs[i]), 4),
                "special": bool(special_mask[i]),
                "fact": bool(fact_mask[i]),
            }
            for i, (tid, (ts, te)) in enumerate(zip(ids.tolist(), offsets.tolist()))
        ]

        facts = FACT_PATTERN.findall(text)
        measured: dict[str, dict] = {}
        for level in levels:
            keep = probs >= level
            decoded = tok.decode(ids[keep], skip_special_tokens=True).strip()
            measured[str(level)] = {
                "kept": int(keep.sum()),
                "total": int(len(ids)),
                "retention": round(float(keep.sum()) / len(ids), 4),
                "compression_ratio": round(1 - float(keep.sum()) / len(ids), 4),
                "text": decoded,
                "facts": facts,
                "facts_surviving_verbatim": [f for f in facts if f in decoded],
            }

        out[name] = {"text": text, "tokens": rows, "levels": measured}

    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="checkpoint directory (local snapshot)")
    ap.add_argument("--text", action="append", required=True, help="text to trace (repeatable)")
    ap.add_argument("--levels", nargs="+", type=float, default=[0.1, 0.2, 0.3, 0.4, 0.5])
    args = ap.parse_args()

    texts = {f"text{i}": t for i, t in enumerate(args.text)}
    print(json.dumps(trace(args.model, texts, args.levels), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
