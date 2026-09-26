"""Freeze the full-scale training set (issue #20): the stage-3 data anchor.

Writes training/manifests/training-set-v1.json pinning:
- the distill output (dir identity + manifest sha256 + labeled sha256/rows),
- the upstream freeze chain (corpus file shas from the distill manifest +
  the live bytes of both corpus manifests),
- teacher / quality-control / counts, and the mix in both calibers
  (entry-level anchor vs row-level outcome — see
  docs/baselines/2026-09-26-distill-sizing-decision.md),
- the repo commit whose code generated the freeze.

The distill output is validated BEFORE the record is written (a broken or
drifted artifact refuses to freeze), and re-validated against the written
record afterwards (`trillic distill validate ... --freeze ...` is the
standing checker — stage 3 asserts against this record before every
acceptance attempt's training run).

Run from the repo root AFTER scripts/distill_full.py completes.
"""

import json
import subprocess
import sys
from pathlib import Path

from trillic.distill import (
    DistillError,
    build_freeze_record,
    collect_distill_errors,
)

REPO = Path(__file__).resolve().parents[1]

DISTILL_DIR = REPO / "training" / "distill" / "full-v1"
RECORD_DIR = "training/distill/full-v1"
CORPUS_MANIFESTS = [
    (
        REPO / "training" / "manifests" / "training-corpus-v1.json",
        "training/manifests/training-corpus-v1.json",
    ),
    (
        REPO / "training" / "manifests" / "synthetic-training-v1.json",
        "training/manifests/synthetic-training-v1.json",
    ),
]
OUT = REPO / "training" / "manifests" / "training-set-v1.json"


def _repo_state() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout.strip())
        return commit, dirty
    except subprocess.SubprocessError:
        return None, None


def main() -> int:
    commit, dirty = _repo_state()
    print(f"repo state: commit {commit} dirty={dirty}")
    try:
        record = build_freeze_record(
            DISTILL_DIR,
            record_dir=RECORD_DIR,
            corpus_manifests=CORPUS_MANIFESTS,
            repo_commit=commit,
            repo_dirty=dirty,
        )
    except DistillError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    OUT.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    errors = collect_distill_errors(DISTILL_DIR, freeze_path=OUT, base_dir=REPO)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    labeled = record["distill"]["labeled"]
    print(f"written: {OUT}")
    print(
        f"frozen training set: {labeled['rows']} rows, "
        f"sha256 {labeled['sha256'][:12]}…; entry mix "
        + json.dumps(record["mix"]["entry_level_pct"])
        + ", row mix "
        + json.dumps(record["mix"]["row_level_pct"])
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
