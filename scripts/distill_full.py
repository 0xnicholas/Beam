"""Run the issue-20 full-scale teacher distillation (pinned invocation).

  - corpus: the frozen v1 training layers (issues #16/#17), bytes
    cross-checked against their manifests before any gateway call;
  - scale: FULL — chunk budgets are recomputed from the frozen corpus
    bytes as the exact per-class chunk totals (100% entry coverage is
    asserted locally BEFORE the first gateway call); gov_report's long
    entries, excluded from the pilot by its budget, all join here;
  - teacher/pacing/prompt: identical to the pilot (sizing decision:
    docs/baselines/2026-09-26-distill-sizing-decision.md) — same
    content-addressed ledger (distill-4fa4734ddd57fcec), so the pilot's
    299 journaled chunks replay at zero cost;
  - resume: crash journal under runs/.ledger/ keyed by the content
    address (corpus bytes + teacher + prompt + chunking) — kill and
    rerun pays only for never-recorded chunks;
  - outputs: training/distill/full-v1/{labeled.jsonl, report.json,
    report.md, manifest.json}.

Run from the repo root with the gateway up (tokencamp-pro
`scripts/dev.sh up`) and REFINE_SERVICE_KEY in the environment.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from trillic.clients.gateway import HttpGatewayClient
from trillic.distill import (
    chunk_text,
    load_corpus_rows,
    run_distillation,
    select_entries,
)
from trillic.tokens import TokenCounter

REPO = Path(__file__).resolve().parents[1]

CORPUS = [
    REPO / "training" / "corpus" / "longbench-train-v1.jsonl",
    REPO / "training" / "corpus" / "synthetic-train-v1.jsonl",
]
MANIFESTS = [
    REPO / "training" / "manifests" / "training-corpus-v1.json",
    REPO / "training" / "manifests" / "synthetic-training-v1.json",
]
OUT = REPO / "training" / "distill" / "full-v1"
LEDGER_ROOT = REPO / "runs"

TEACHER_MODEL = "deepseek/deepseek-v4-pro"
GATEWAY_URL = "http://127.0.0.1:3005"
# Pacing posture proven on the 2026-09-12 full149 runs and the #18 pilot:
# >= 3s between call starts (headroom vs the ~35/min observed trip point).
# 2026-09-26 full-scale latency profile (measured on two live launches):
# the teacher reasons ~6-12k tokens per call (55s small sysprompt chunk,
# 216s for a 510-token dialogue chunk — legitimately; reasoning_effort
# experiments documented in the sizing doc) — timeout 420s + 2 transport
# retries fit that distribution without burning slow-but-legit calls, and
# 24 workers put the ETA at ~12h for the ~6.9k fresh chunks; the crash
# journal absorbs kills (replays verified twice on real crashes today).
MIN_CALL_INTERVAL = 3.0
CONCURRENCY = 24
TIMEOUT_SECONDS = 420.0
MAX_RETRIES = 2

MAX_CHUNK_TOKENS = 512
WINDOW_SIZE = 150
VR_DROP_FRACTION = 0.05
AG_DROP_FRACTION = 0.10


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


def _check_corpus_frozen() -> None:
    """Refuse to distill drifted corpus bytes: the manifest sha256 IS the
    frozen identity of each layer."""
    for corpus_path, manifest_path in zip(CORPUS, MANIFESTS):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = manifest["corpus"]["sha256"]
        actual = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
        if actual != recorded:
            raise SystemExit(
                f"{corpus_path} does not match its manifest "
                f"({manifest_path}): {actual[:12]}… vs recorded "
                f"{recorded[:12]}… — restore the frozen corpus or "
                "regenerate the manifest deliberately"
            )
        print(f"frozen corpus ok: {corpus_path.name} ({manifest['corpus']['entries']} entries)")


def _full_chunk_budgets(counter: TokenCounter) -> dict[str, int]:
    """Full coverage, by construction: budgets = the exact per-class chunk
    totals of the frozen corpus, with a pre-spend assertion that every
    entry is selected (an oversized-entry skip would silently shrink the
    training set AFTER the money is spent)."""
    rows, _ = load_corpus_rows(CORPUS)
    chunk_counts = {
        row["id"]: len(
            chunk_text(row["prompt"], max_tokens=MAX_CHUNK_TOKENS, counter=counter)
        )
        for row in rows
    }
    budgets: dict[str, int] = {}
    for row in rows:
        budgets[row["load_type"]] = budgets.get(row["load_type"], 0) + chunk_counts[row["id"]]
    selected = select_entries(rows, chunk_counts, budgets)
    if len(selected) != len(rows):
        raise SystemExit(
            f"full-coverage assertion failed BEFORE any gateway call: "
            f"{len(selected)}/{len(rows)} entries selected — do not spend"
        )
    print(
        f"full coverage ok: {len(rows)} entries, "
        + ", ".join(f"{k}={v}" for k, v in sorted(budgets.items()))
        + f" chunks (total {sum(budgets.values())})"
    )
    return budgets


def main() -> int:
    _check_corpus_frozen()
    commit, dirty = _repo_state()
    print(f"repo state: commit {commit} dirty={dirty}")
    counter = TokenCounter("cl100k_base")
    budgets = _full_chunk_budgets(counter)
    gateway = HttpGatewayClient(
        base_url=GATEWAY_URL,
        timeout_seconds=TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
        min_call_interval=MIN_CALL_INTERVAL,
    )
    try:
        manifest = run_distillation(
            corpus_paths=CORPUS,
            chunk_budgets=budgets,
            gateway=gateway,
            teacher_model=TEACHER_MODEL,
            out_dir=OUT,
            ledger_root=LEDGER_ROOT,
            counter=counter,
            window_size=WINDOW_SIZE,
            max_chunk_tokens=MAX_CHUNK_TOKENS,
            vr_drop_fraction=VR_DROP_FRACTION,
            ag_drop_fraction=AG_DROP_FRACTION,
            concurrency=CONCURRENCY,
            repo_commit=commit,
            repo_dirty=dirty,
            record_corpus=[
                "training/corpus/longbench-train-v1.jsonl",
                "training/corpus/synthetic-train-v1.jsonl",
            ],
            record_journal="runs/.ledger/ (content-addressed, gitignored runtime ledger)",
        )
    finally:
        gateway.close()
    counts = manifest["counts"]
    if counts["selected_entries"] != counts["corpus_entries"]:
        raise SystemExit(
            f"full-coverage assertion failed: {counts['selected_entries']}/"
            f"{counts['corpus_entries']} entries selected"
        )
    gw = manifest["gateway"]
    print(
        f"{OUT}: {counts['labeled_kept']} labeled chunks kept "
        f"({counts['dropped']} dropped of {counts['chunks']} compressed; "
        f"gateway calls fresh {gw['calls_fresh']} / reused {gw['calls_reused']})"
    )
    print(f"crash journal: {gw['journal']} (ledger {gw['ledger_id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
