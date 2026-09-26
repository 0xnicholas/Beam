"""Teacher distillation pipeline (issue #18): corpus in, labeled data out.

Implements the LLMLingua-2 data-construction method (arXiv:2403.12968)
against this repo's frozen training corpora (issues #16/#17):

1. chunk every corpus entry to <= max tokens (default 512), on sentence
   boundaries where the text allows it;
2. compress each chunk through the gateway teacher (prompt template
   versioned below — the paper's Fig. 2 prompt, verbatim);
3. derive word-level keep/delete labels on the ORIGINAL chunk text with
   the paper's sliding-window fuzzy matching (label_word.py port);
4. quality-control the labeled chunks: drop the top VR fraction (most
   hallucination-prone), then the top AG fraction of survivors (worst
   label alignment). Fractions and thresholds are versioned in the
   distillation manifest.

Deviations from the reference implementation, recorded in every manifest:

- tokenization: spacy lemmas -> deterministic regex word tokens (words
  with internal ' / - kept whole), compared case-insensitively; commas
  are dropped exactly as the reference does. No model downloads, no
  network, byte-stable across machines.
- chunk boundaries additionally break on newline runs (dialogue turns and
  prompt blocks have no sentence punctuation; the paper's own rule --
  "ends with a period" -- only fits its Wikipedia/MeetingBank corpus).

Billing/resume posture (mirrors trillic.resume, issue #8): the gateway
teacher is the billing surface. One journal line is appended per FRESH
compressed chunk (reusing trillic.resume.CallJournal), keyed by the
content-addressed ledger id (corpus bytes + teacher model + prompt sha +
chunking params). A killed run's rerun replays journaled chunks and pays
only for the ones it never recorded — zero duplicate gateway calls for
completed work.
"""

import bisect
import hashlib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from trillic.clients.gateway import GatewayClient
from trillic.quality import percentile, rounded_mean
from trillic.resume import CallJournal
from trillic.tokens import TokenCounter

__all__ = [
    "DistillError",
    "FREEZE_RECORD_SCHEMA_VERSION",
    "PROMPT_TEMPLATE",
    "PROMPT_VERSION",
    "TextChunk",
    "WordTok",
    "build_freeze_record",
    "chunk_text",
    "collect_distill_errors",
    "word_tokens",
    "match_labels",
    "distill_metrics",
    "label_chunk",
    "quality_control",
    "distill_ledger_id",
    "load_corpus_rows",
    "run_distillation",
]

# The paper's teacher prompt (Fig. 2 / Fig. 9), verbatim; the (GPT-4)
# self-reference is part of the reference method and stays as-is. Version
# v1 = paper-faithful; ANY change bumps the version and the sha256 that
# the manifest pins (teacher outputs are not comparable across versions).
PROMPT_TEMPLATE = (
    "Compress the given text to short expressions, and such that you "
    "(GPT-4) can reconstruct it as close as possible to the original. "
    "Unlike the usual text compression, I need you to comply with the 5 "
    "conditions below:\n"
    "1. You can ONLY remove unimportant words.\n"
    "2. Do not reorder the original words.\n"
    "3. Do not change the original words.\n"
    "4. Do not use abbreviations or emojis.\n"
    "5. Do not add new words or symbols.\n"
    "Compress the origin aggressively by removing words only. Compress "
    "the origin as short as you can, while retaining as much information "
    "as possible. If you understand, please compress the following text:\n"
    "{text}\n"
    "The compressed text is:"
)
PROMPT_VERSION = "llmlingua2-paper-v1"

# Reference defaults: window 150 tokens (label_word.py --window_size),
# <= 512 tokens per chunk (paper Sec. 3.1), VR top 5% / AG top 10%
# (paper Sec. 3.3). All overridable; every value lands in the manifest.
DEFAULT_WINDOW_SIZE = 150
DEFAULT_MAX_CHUNK_TOKENS = 512
DEFAULT_VR_DROP_FRACTION = 0.05
DEFAULT_AG_DROP_FRACTION = 0.10

_ROUND = 4

# Word tokens: alphanumeric runs (internal ' ' - kept whole) or single
# punctuation marks. Matches the reference's treatment of "," as a
# non-token; everything else — including "." — is a token.
_WORD_RE = re.compile(r"[0-9A-Za-z]+(?:['’\-][0-9A-Za-z]+)*|[^\w\s]")

# Sentence-boundary candidates: sentence-final punctuation (+ closing
# quotes/brackets) followed by whitespace or end-of-text, or a newline
# run (dialogue turns / prompt blocks). Decimal points ("3.14") do not
# match — the digit after the period is not whitespace.
_BOUNDARY_RE = re.compile(r"[.!?…][\"')\]]*(?:\s+|$)|(?:\n[ \t]*)+")


class DistillError(ValueError):
    """Distillation input, pipeline, or artifact error."""


@dataclass(frozen=True)
class TextChunk:
    """A lossless [start, end) slice of an entry's prompt."""

    index: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class WordTok:
    """One word-level token with its exact char span and keep label."""

    text: str
    start: int
    end: int
    keep: bool


def chunk_text(text: str, *, max_tokens: int, counter: TokenCounter) -> list[TextChunk]:
    """Pack `text` into chunks of at most `max_tokens` tokens.

    Chunks are contiguous character slices: concatenating every chunk
    reproduces the prompt byte-for-byte (asserted by the caller-facing
    invariant below). Boundaries prefer sentence ends / newline runs; a
    single span larger than the cap is hard-split at word boundaries
    (last resort: mid-word) so the cap always holds.
    """
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
        raise DistillError(f"max_tokens must be an integer >= 1, got {max_tokens!r}")
    if not text:
        return []

    chunks: list[TextChunk] = []

    def emit(start: int, end: int) -> None:
        if end > start:
            chunks.append(
                TextChunk(index=len(chunks), start=start, end=end, text=text[start:end])
            )

    def hard_split(start: int, end: int) -> tuple[int, int]:
        """Split an oversized span at word boundaries into pieces of at
        most max_tokens, emitting every closed piece; returns the open
        last piece (guaranteed to fit unless a single unsplittable
        character run exceeds the cap, in which case the cap holds for
        every emitted piece and the open tail is char-split too)."""
        marks = sorted({m.start() for m in _WORD_RE.finditer(text, start, end)} | {end})

        def _fit_chars(lo: int, hi: int) -> int:
            """Largest mid in (lo, hi) with count(text[lo:mid]) <= cap.
            Returns >= lo + 1 (progress guarantee: pathological runs of
            unsplittable characters must never loop forever)."""
            good = lo + 1
            lo_b, hi_b = lo + 1, hi - 1
            while lo_b <= hi_b:
                mid = (lo_b + hi_b) // 2
                if counter.count(text[lo:mid]) <= max_tokens:
                    good = mid
                    lo_b = mid + 1
                else:
                    hi_b = mid - 1
            return good

        piece_start = start
        for mark in marks:
            if mark <= piece_start:
                continue
            while counter.count(text[piece_start:mark]) > max_tokens:
                # next interior word boundary, if any, closes the piece
                idx = bisect.bisect_right(marks, piece_start)
                nxt = marks[idx] if idx < len(marks) else mark
                if nxt < mark:
                    emit(piece_start, nxt)
                    piece_start = nxt
                else:
                    # no word boundary inside: char-split the segment
                    mid = _fit_chars(piece_start, mark)
                    emit(piece_start, mid)
                    piece_start = mid
        return piece_start, end

    cur_start = 0
    cur_end: int | None = None
    for _, span_end in _sentence_spans(text):
        if counter.count(text[cur_start:span_end]) <= max_tokens:
            cur_end = span_end
            continue
        # overflow: close what we have (if anything), then absorb the span
        if cur_end is not None:
            emit(cur_start, cur_end)
            cur_start = cur_end
        if counter.count(text[cur_start:span_end]) <= max_tokens:
            cur_end = span_end
        else:
            # the span alone exceeds the cap: hard-split it at word
            # boundaries, keep only the open tail as the current chunk
            piece_start, _ = hard_split(cur_start, span_end)
            cur_start, cur_end = piece_start, span_end
    if cur_end is not None:
        emit(cur_start, cur_end)

    # losslessness is a hard invariant, not a hope
    assert "".join(c.text for c in chunks) == text, "chunking lost text"
    assert all(counter.count(c.text) <= max_tokens for c in chunks), "chunk over cap"
    return chunks


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Contiguous [start, end) spans cut at boundary candidates."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _BOUNDARY_RE.finditer(text):
        end = match.end()
        spans.append((start, end))
        start = end
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def word_tokens(text: str) -> list[WordTok]:
    """Deterministic word tokens with char spans; commas are dropped
    (reference behavior), everything else kept, keep=False."""
    return [
        WordTok(text=m.group(), start=m.start(), end=m.end(), keep=False)
        for m in _WORD_RE.finditer(text)
        if m.group() != ","
    ]


def match_labels(
    origin_tokens: list[str], comp_tokens: list[str], *, window_size: int
) -> tuple[list[bool], int]:
    """LLMLingua-2 sliding-window fuzzy matching (label_word.py port).

    Walks the compressed tokens in order; each tries to label the first
    equal (case-insensitive) unlabeled origin token within `window_size`
    positions of the previous match — forward scan first, window sliding
    at most window//2 per match, then backward. Returns (labels,
    num_find) where num_find counts compressed tokens whose word occurs
    ANYWHERE in the origin (the Variation Rate numerator's complement).
    """
    if not isinstance(window_size, int) or isinstance(window_size, bool) or window_size < 1:
        raise DistillError(f"window_size must be an integer >= 1, got {window_size!r}")
    num_origin = len(origin_tokens)
    labels = [False] * num_origin
    if num_origin == 0:
        return labels, 0
    origin_set = {t.lower() for t in origin_tokens}
    num_find = 0
    prev_idx = 0
    for token in comp_tokens:
        if token in origin_set or token.lower() in origin_set:
            num_find += 1
        for i in range(window_size):
            # look forward
            token_idx = min(prev_idx + i, num_origin - 1)
            if _equal(origin_tokens[token_idx], token) and not labels[token_idx]:
                labels[token_idx] = True
                # window does not go too fast
                if token_idx - prev_idx > window_size // 2:
                    prev_idx += window_size // 2
                else:
                    prev_idx = token_idx
                break
            # look backward
            token_idx = max(prev_idx - i, 0)
            if _equal(origin_tokens[token_idx], token) and not labels[token_idx]:
                labels[token_idx] = True
                prev_idx = token_idx
                break
    return labels, num_find


def _equal(a: str, b: str) -> bool:
    return a.lower() == b.lower()


def distill_metrics(
    *, n_origin: int, n_comp: int, n_kept: int, num_find: int
) -> dict:
    """Paper-caliber per-chunk metrics (label_word.py formulas):

    - variation_rate  = 1 - find_rate   (find_rate = findable comp words
      / comp words; hallucination proxy)
    - hitting_rate    = num_find / origin words
    - matching_rate   = labeled origin words / origin words
    - alignment_gap   = hitting_rate - matching_rate (0 = perfect labels)
    """
    if n_origin < 1:
        raise DistillError(f"n_origin must be >= 1, got {n_origin!r}")
    if n_comp < 0 or n_kept < 0 or num_find < 0 or n_kept > n_origin or num_find > n_comp:
        raise DistillError(
            f"inconsistent counts: origin={n_origin} comp={n_comp} "
            f"kept={n_kept} find={num_find}"
        )
    find_rate = num_find / n_comp if n_comp else 0.0
    hitting_rate = num_find / n_origin
    matching_rate = n_kept / n_origin
    return {
        "word_compressed_rate": round(n_comp / n_origin, _ROUND),
        "find_rate": round(find_rate, _ROUND),
        "variation_rate": round(1.0 - find_rate, _ROUND),
        "hitting_rate": round(hitting_rate, _ROUND),
        "matching_rate": round(matching_rate, _ROUND),
        "alignment_gap": round(hitting_rate - matching_rate, _ROUND),
    }


@dataclass(frozen=True)
class LabeledChunk:
    """Word-labeled chunk: tokens with keep flags + paper metrics."""

    tokens: list[WordTok]
    metrics: dict


def label_chunk(
    origin_text: str, compressed_text: str, *, window_size: int
) -> LabeledChunk:
    """Tokenize + match one (chunk, teacher output) pair."""
    origin = word_tokens(origin_text)
    comp = word_tokens(compressed_text)
    labels, num_find = match_labels(
        [t.text for t in origin], [t.text for t in comp], window_size=window_size
    )
    metrics = distill_metrics(
        n_origin=len(origin),
        n_comp=len(comp),
        n_kept=sum(labels),
        num_find=num_find,
    )
    tokens = [replace(t, keep=lab) for t, lab in zip(origin, labels)]
    return LabeledChunk(tokens=tokens, metrics=metrics)


def quality_control(
    rows: list[dict], *, vr_drop_fraction: float, ag_drop_fraction: float
) -> tuple[list[dict], dict]:
    """Sequential paper filters over labeled-chunk rows.

    Order (versioned in the manifest): drop the top `vr_drop_fraction`
    by Variation Rate (hallucination-prone teacher output), then the top
    `ag_drop_fraction` of the SURVIVORS by Alignment Gap (labels that the
    matcher could not reproduce). Drop counts are ceil(fraction * n);
    ties break by id so the result is order-independent; kept rows keep
    their input order.
    """
    _check_fraction("vr_drop_fraction", vr_drop_fraction)
    _check_fraction("ag_drop_fraction", ag_drop_fraction)

    def rank_and_drop(pool: list[dict], fraction: float, metric: str):
        ordered = sorted(pool, key=lambda r: (r["metrics"][metric], r["id"]))
        k = math.ceil(fraction * len(ordered)) if ordered else 0
        dropped = ordered[len(ordered) - k :] if k else []
        survivors = ordered[: len(ordered) - k] if k else ordered
        threshold = survivors[-1]["metrics"][metric] if survivors else None
        return dropped, threshold

    vr_dropped, vr_threshold = rank_and_drop(rows, vr_drop_fraction, "variation_rate")
    vr_ids = {r["id"] for r in vr_dropped}
    after_vr = [r for r in rows if r["id"] not in vr_ids]
    ag_dropped, ag_threshold = rank_and_drop(after_vr, ag_drop_fraction, "alignment_gap")
    ag_ids = {r["id"] for r in ag_dropped}
    kept = [r for r in after_vr if r["id"] not in ag_ids]

    dropped = sorted(
        [
            *[
                {"id": r["id"], "dropped_by": "variation_rate", "metrics": r["metrics"]}
                for r in vr_dropped
            ],
            *[
                {"id": r["id"], "dropped_by": "alignment_gap", "metrics": r["metrics"]}
                for r in ag_dropped
            ],
        ],
        key=lambda r: r["id"],
    )
    report = {
        "order": "variation_rate_then_alignment_gap",
        "vr_drop_fraction": vr_drop_fraction,
        "ag_drop_fraction": ag_drop_fraction,
        "input": len(rows),
        "vr_dropped": len(vr_dropped),
        "ag_dropped": len(ag_dropped),
        "kept": len(kept),
        "vr_threshold": vr_threshold,
        "ag_threshold": ag_threshold,
        "dropped": dropped,
    }
    return kept, report


def _check_fraction(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DistillError(f"{name} must be a number in [0, 1), got {value!r}")
    if not 0.0 <= value < 1.0:
        raise DistillError(f"{name} must be within [0, 1), got {value!r}")


# ---------------------------------------------------------------------------
# Orchestration: corpus loading, budgeted selection, teacher loop, artifacts
# ---------------------------------------------------------------------------

_LOAD_TYPES = ("rag", "system_prompt", "dialogue")
_JOURNAL_KIND = "distill-chunk"


def prompt_sha256() -> str:
    """sha256 of the versioned prompt template (manifest pin)."""
    return hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest()


def load_corpus_rows(paths: list[Path]) -> tuple[list[dict], list[dict]]:
    """Load training-corpus jsonl files (schema v1, issues #16/#17).

    Returns (rows, files) where files carry the per-file identity the
    ledger and manifest pin (path as given + sha256 + entry count).
    """
    rows: list[dict] = []
    files: list[dict] = []
    seen_ids: set[str] = set()
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise DistillError(f"{path}: no such corpus file") from None
        count = 0
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise DistillError(f"{path}: line {number}: cannot parse JSON: {e}") from None
            if not isinstance(row, dict):
                raise DistillError(f"{path}: line {number}: each row must be a JSON object")
            entry_id = row.get("id")
            if not isinstance(entry_id, str) or not entry_id.strip():
                raise DistillError(f"{path}: line {number}: id must be a non-empty string")
            if entry_id in seen_ids:
                raise DistillError(
                    f"{path}: line {number}: duplicate id {entry_id!r} "
                    "(ids must be unique across all corpus files)"
                )
            seen_ids.add(entry_id)
            if row.get("load_type") not in _LOAD_TYPES:
                raise DistillError(
                    f"{path}: line {number} (id={entry_id!r}): load_type must be "
                    f"one of {list(_LOAD_TYPES)}, got {row.get('load_type')!r}"
                )
            prompt = row.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise DistillError(
                    f"{path}: line {number} (id={entry_id!r}): prompt must be a "
                    "non-empty string"
                )
            if not isinstance(row.get("source"), dict):
                raise DistillError(
                    f"{path}: line {number} (id={entry_id!r}): source must be an object"
                )
            rows.append(row)
            count += 1
        files.append(
            {
                "file": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "entries": count,
            }
        )
    return rows, files


def select_entries(
    rows: list[dict],
    chunk_counts: dict[str, int],
    budgets: dict[str, int],
) -> list[dict]:
    """Deterministic per-class selection under CHUNK budgets.

    The budget bounds gateway spend directly (one call per chunk), so the
    pilot scale is pinned by construction. Entries scan in corpus order;
    an entry joins its class iff its chunks fit the remaining budget
    (oversized entries are skipped, not truncated — a chunked entry with
    a hole is not a valid training sample). Budgets naming classes that
    are not in the corpus are rejected loudly.
    """
    present = {row["load_type"] for row in rows}
    unknown = set(budgets) - present
    if unknown:
        raise DistillError(
            f"chunk budget names classes not present in the corpus: "
            f"{sorted(unknown)} (present: {sorted(present)})"
        )
    remaining = dict(budgets)
    selected: list[dict] = []
    for row in rows:
        load_type = row["load_type"]
        if load_type not in remaining:
            continue
        need = chunk_counts[row["id"]]
        if need <= remaining[load_type]:
            remaining[load_type] -= need
            selected.append(row)
    return selected


def distill_ledger_id(
    *,
    corpus_shas: list[str],
    teacher_model: str,
    prompt_sha256: str,
    max_chunk_tokens: int,
    encoding: str,
) -> str:
    """Identity of the distillation billing surface: same corpus bytes +
    same teacher + same prompt + same chunking = same ledger. Labeling/QC
    parameters are deliberately absent (local recompute, zero cost)."""
    digest = hashlib.sha256()
    for part in (
        *corpus_shas,
        teacher_model,
        prompt_sha256,
        str(max_chunk_tokens),
        encoding,
    ):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


def load_chunk_results(path: Path) -> dict[str, dict]:
    """Parse a distillation journal into {chunk key: result}.

    Mirrors CallJournal.load_replay's torn-tail tolerance: a line that
    fails to parse is a kill during the write — dropped, honestly
    re-billed on the next run.
    """
    path = Path(path)
    if not path.is_file():
        return {}
    results: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("kind") != _JOURNAL_KIND:
                continue
            results[record["item"]] = {
                "compressed_text": record["answer"],
                "served_model": record.get("payload"),
            }
    return results


def _compress_chunks(
    gateway: GatewayClient,
    *,
    teacher_model: str,
    jobs: list[tuple[str, str]],
    journal: CallJournal,
    replay: dict[str, dict],
    concurrency: int,
) -> tuple[dict[str, dict], dict[str, int]]:
    """Compress every chunk exactly once, journal-first billing.

    Journaled chunks replay for free (kill-and-rerun); fresh calls append
    to the crash journal immediately after returning, so a kill loses at
    most the in-flight chunk.
    """
    results: dict[str, dict] = {}
    stats = {"fresh": 0, "reused": 0}

    def work(job: tuple[str, str]) -> tuple[str, dict]:
        key, text = job
        if key in replay:
            stats["reused"] += 1
            entry = dict(replay[key])
            entry["fresh"] = False
            return key, entry
        result = gateway.chat(teacher_model, PROMPT_TEMPLATE.format(text=text))
        journal.record(
            kind=_JOURNAL_KIND,
            item_id=key,
            level=None,
            payload=result.model,  # served model: the version of record
            answer=result.content,
            scores=[],
        )
        stats["fresh"] += 1
        return key, {
            "compressed_text": result.content,
            "served_model": result.model,
            "fresh": True,
        }

    if concurrency <= 1:
        for key, entry in (work(job) for job in jobs):
            results[key] = entry
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for key, entry in pool.map(work, jobs):
                results[key] = entry
    return results, stats


def _check_overwrite_identity(
    out_dir: Path,
    *,
    corpus_shas: list[str],
    teacher_model: str,
    max_chunk_tokens: int,
    window_size: int,
    vr_drop_fraction: float,
    ag_drop_fraction: float,
) -> None:
    """Versioned-artifact guard with a re-pin escape hatch.

    A manifest in the out dir refuses the run UNLESS every
    content-determining pin matches (corpus bytes, teacher, chunking,
    matching, QC fractions): same identity means the regeneration is
    journal-backed and byte-deterministic, so overwriting in place is
    exactly the zero-cost re-pin flow (record paths / repo commit may
    legitimately differ — that is the point of re-pinning). Any drift
    picks a new output directory instead of silently rewriting history.
    """
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        return
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise DistillError(
            f"{manifest_path} exists but cannot be read ({e}) — move it aside "
            "and regenerate deliberately"
        ) from e
    mismatches: list[str] = []
    files = existing.get("corpus", {}).get("files", [])
    if [f.get("sha256") for f in files] != corpus_shas:
        mismatches.append("corpus files/sha256s")
    teacher = existing.get("teacher", {})
    if teacher.get("model") != teacher_model or teacher.get("prompt_version") != PROMPT_VERSION:
        mismatches.append("teacher model / prompt version")
    if existing.get("chunking", {}).get("max_tokens") != max_chunk_tokens:
        mismatches.append("chunking.max_tokens")
    if existing.get("labeling", {}).get("window_size") != window_size:
        mismatches.append("labeling.window_size")
    qc = existing.get("quality_control", {})
    if qc.get("vr_drop_fraction") != vr_drop_fraction or qc.get("ag_drop_fraction") != ag_drop_fraction:
        mismatches.append("quality_control drop fractions")
    if mismatches:
        raise DistillError(
            f"{manifest_path} already exists with a different identity "
            f"({'; '.join(mismatches)}) — distillation outputs are versioned "
            "artifacts; pick a new output directory instead of overwriting"
        )


def run_distillation(
    *,
    corpus_paths: list[Path],
    chunk_budgets: dict[str, int],
    gateway: GatewayClient,
    teacher_model: str,
    out_dir: Path,
    ledger_root: Path,
    counter: TokenCounter,
    window_size: int = DEFAULT_WINDOW_SIZE,
    max_chunk_tokens: int = DEFAULT_MAX_CHUNK_TOKENS,
    vr_drop_fraction: float = DEFAULT_VR_DROP_FRACTION,
    ag_drop_fraction: float = DEFAULT_AG_DROP_FRACTION,
    concurrency: int = 1,
    repo_commit: str | None = None,
    repo_dirty: bool | None = None,
    record_corpus: list[str] | None = None,
    record_journal: str | None = None,
) -> dict:
    """Full pipeline: corpus in, labeled dataset + QC report + manifest out.

    The gateway teacher is the only billed surface; every completed
    compression lands in the crash journal keyed by the content-addressed
    ledger id, so an interrupted rerun pays only for chunks it never
    recorded. Artifacts are written at the END (a killed run leaves no
    half-written output dir; the journal is the ledger of record).
    """
    _check_fraction("vr_drop_fraction", vr_drop_fraction)
    _check_fraction("ag_drop_fraction", ag_drop_fraction)
    if not isinstance(window_size, int) or isinstance(window_size, bool) or window_size < 1:
        raise DistillError(f"window_size must be an integer >= 1, got {window_size!r}")
    if (
        not isinstance(max_chunk_tokens, int)
        or isinstance(max_chunk_tokens, bool)
        or max_chunk_tokens < 1
    ):
        raise DistillError(f"max_chunk_tokens must be an integer >= 1, got {max_chunk_tokens!r}")
    if not isinstance(concurrency, int) or isinstance(concurrency, bool) or concurrency < 1:
        raise DistillError(f"concurrency must be an integer >= 1, got {concurrency!r}")
    out_dir = Path(out_dir)
    rows, files = load_corpus_rows(list(corpus_paths))
    _check_overwrite_identity(
        out_dir,
        corpus_shas=[f["sha256"] for f in files],
        teacher_model=teacher_model,
        max_chunk_tokens=max_chunk_tokens,
        window_size=window_size,
        vr_drop_fraction=vr_drop_fraction,
        ag_drop_fraction=ag_drop_fraction,
    )
    if record_corpus is not None and len(record_corpus) != len(files):
        raise DistillError(
            f"record_corpus needs one identity per corpus file ({len(files)}), "
            f"got {len(record_corpus)}"
        )
    # one chunking pass feeds both the budgeted selection (needs counts)
    # and the job list (needs the chunks) — no second traversal
    chunks_by_id: dict[str, list[TextChunk]] = {
        row["id"]: chunk_text(
            row["prompt"], max_tokens=max_chunk_tokens, counter=counter
        )
        for row in rows
    }
    chunk_counts = {row_id: len(chunks) for row_id, chunks in chunks_by_id.items()}
    selected = select_entries(rows, chunk_counts, chunk_budgets)
    if not selected:
        raise DistillError("chunk budgets selected zero entries — nothing to distill")

    @dataclass(frozen=True)
    class Job:
        key: str
        row: dict
        chunk: TextChunk

    jobs: list[Job] = []
    token_empty = 0
    for row in selected:
        for chunk in chunks_by_id[row["id"]]:
            # Punctuation/whitespace-only chunks (a boundary-packing
            # remnant: a lone ", " etc.) carry no labelable words — their
            # metrics are 0/0-undefined and compressing them is pointless
            # spend. Skip and count them. Every OTHER chunk keeps its
            # index, so journal keys stay byte-stable across the fix.
            if not word_tokens(chunk.text):
                token_empty += 1
                continue
            jobs.append(Job(key=f"{row['id']}#c{chunk.index}", row=row, chunk=chunk))
    if not jobs:
        raise DistillError(
            "the selection produced zero compressible chunks (every chunk "
            "is token-empty) — nothing to distill"
        )
    lid = distill_ledger_id(
        corpus_shas=[f["sha256"] for f in files],
        teacher_model=teacher_model,
        prompt_sha256=prompt_sha256(),
        max_chunk_tokens=max_chunk_tokens,
        encoding=counter.encoding_name,
    )
    journal_path = Path(ledger_root) / ".ledger" / f"distill-{lid}.jsonl"
    journal = CallJournal(journal_path)
    replay = load_chunk_results(journal_path)
    try:
        compressed, comp_stats = _compress_chunks(
            gateway,
            teacher_model=teacher_model,
            jobs=[(job.key, job.chunk.text) for job in jobs],
            journal=journal,
            replay=replay,
            concurrency=concurrency,
        )
    finally:
        journal.close()

    labeled_rows = []
    for job in jobs:
        entry = compressed[job.key]
        labeled = label_chunk(
            job.chunk.text, entry["compressed_text"], window_size=window_size
        )
        labeled_rows.append(
            {
                "id": job.key,
                "entry_id": job.row["id"],
                "load_type": job.row["load_type"],
                "prompt": job.chunk.text,
                "question": job.row.get("question", ""),
                "task": job.row.get("task", ""),
                "chunk": {
                    "index": job.chunk.index,
                    "start": job.chunk.start,
                    "end": job.chunk.end,
                    "entry_chars": len(job.row["prompt"]),
                },
                "compressed_text": entry["compressed_text"],
                "teacher_model_served": entry["served_model"],
                "tokens": [
                    [tok.text, tok.start, tok.end, int(tok.keep)] for tok in labeled.tokens
                ],
                "metrics": labeled.metrics,
                "source": dict(job.row["source"]),
            }
        )

    kept, qc_report = quality_control(
        labeled_rows, vr_drop_fraction=vr_drop_fraction, ag_drop_fraction=ag_drop_fraction
    )

    by_load_type: dict[str, dict] = {}
    for row in labeled_rows:
        block = by_load_type.setdefault(
            row["load_type"], {"entries": 0, "chunks": 0, "kept": 0, "dropped": 0}
        )
        block["chunks"] += 1
    kept_ids = {r["id"] for r in kept}
    for row in labeled_rows:
        by_load_type[row["load_type"]]["kept" if row["id"] in kept_ids else "dropped"] += 1
    selected_ids = {r["id"] for r in selected}
    for row in rows:
        if row["id"] in selected_ids:
            by_load_type[row["load_type"]]["entries"] += 1

    served_models = sorted(
        {e["served_model"] for e in compressed.values() if e.get("served_model")}
    )
    counts = {
        "corpus_entries": len(rows),
        "selected_entries": len(selected),
        "chunks": len(jobs),
        "token_empty_chunks_skipped": token_empty,
        "labeled_kept": len(kept),
        "dropped": len(labeled_rows) - len(kept),
        "by_load_type": by_load_type,
    }
    gateway_block = {
        "calls_fresh": comp_stats["fresh"],
        "calls_reused": comp_stats["reused"],
        "ledger_id": lid,
        "journal": record_journal if record_journal is not None else str(journal_path),
        # Distinct chunks the journal has EVER recorded for this ledger:
        # the billing surface stays auditable even when THIS run replayed
        # everything (artifact assembled at zero cost after the billed run).
        "journal_records": len(load_chunk_results(journal_path)),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    labeled_path = out_dir / "labeled.jsonl"
    labeled_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8"
    )
    report = _build_report(
        labeled_rows=labeled_rows,
        kept=kept,
        qc_report=qc_report,
        counts=counts,
        gateway=gateway_block,
        by_load_type=by_load_type,
        teacher_model=teacher_model,
        served_models=served_models,
        vr_drop_fraction=vr_drop_fraction,
        ag_drop_fraction=ag_drop_fraction,
    )
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "report.md").write_text(_render_report_md(report), encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "method": (
            "LLMLingua-2 distillation pipeline (arXiv:2403.12968): teacher "
            "compression of <=512-token chunks -> deterministic word-level "
            "labels via sliding-window fuzzy matching -> VR/AG quality control"
        ),
        "generated_by": {
            "tool": "trillic.distill",
            "repo_commit": repo_commit,
            "repo_dirty": repo_dirty,
        },
        "corpus": {
            "files": (
                [dict(f, file=recorded) for f, recorded in zip(files, record_corpus)]
                if record_corpus is not None
                else files
            ),
            "selection_rule": (
                "per load_type, entries scan in corpus file order and join "
                "iff their whole chunk count fits the remaining class budget "
                "(oversized entries are skipped, never truncated); budgets "
                "bound the gateway spend by construction"
            ),
            "chunk_budgets": dict(chunk_budgets),
        },
        "teacher": {
            "model": teacher_model,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": prompt_sha256(),
            "prompt_template": PROMPT_TEMPLATE,
            "served_models": served_models,
        },
        "chunking": {
            "max_tokens": max_chunk_tokens,
            "encoding": counter.encoding_name,
            "boundary_rule": (
                "sentence-final punctuation + trailing whitespace, or "
                "newline runs; oversized spans hard-split at word boundaries; "
                "chunks are lossless char slices of the prompt"
            ),
        },
        "labeling": {
            "algorithm": "llmlingua2 label_word.py port (sliding-window fuzzy matching)",
            "tokenizer": (
                "regex word tokens (internal ' and - kept whole), commas "
                "dropped, case-insensitive comparison — deviation from the "
                "reference's spacy lemmas: deterministic, zero-dependency"
            ),
            "window_size": window_size,
        },
        "quality_control": {
            "order": "variation_rate_then_alignment_gap",
            "vr_drop_fraction": vr_drop_fraction,
            "ag_drop_fraction": ag_drop_fraction,
            "vr_threshold": qc_report["vr_threshold"],
            "ag_threshold": qc_report["ag_threshold"],
            "drop_counts": {
                "variation_rate": qc_report["vr_dropped"],
                "alignment_gap": qc_report["ag_dropped"],
            },
        },
        "gateway": gateway_block,
        "outputs": {
            "labeled": {
                "file": labeled_path.name,
                "sha256": hashlib.sha256(labeled_path.read_bytes()).hexdigest(),
                "rows": len(kept),
            },
            "report": "report.json",
        },
        "counts": counts,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def _distribution(rows: list[dict], field: str) -> dict:
    values = [r["metrics"][field] for r in rows]
    return {
        "p50": _nullable_round(percentile(values, 50)),
        "p90": _nullable_round(percentile(values, 90)),
        "p95": _nullable_round(percentile(values, 95)),
        "mean": rounded_mean(values),
    }


def _nullable_round(value: float | None) -> float | None:
    return None if value is None else round(value, _ROUND)


def _build_report(
    *,
    labeled_rows: list[dict],
    kept: list[dict],
    qc_report: dict,
    counts: dict,
    gateway: dict,
    by_load_type: dict,
    teacher_model: str,
    served_models: list[str],
    vr_drop_fraction: float,
    ag_drop_fraction: float,
) -> dict:
    return {
        "teacher": {
            "model": teacher_model,
            "served_models": served_models,
            "prompt_version": PROMPT_VERSION,
        },
        "counts": counts,
        "gateway": gateway,
        "quality_control": qc_report,
        "distributions": {
            "population": {
                field: _distribution(labeled_rows, field)
                for field in (
                    "word_compressed_rate",
                    "variation_rate",
                    "matching_rate",
                    "hitting_rate",
                    "alignment_gap",
                )
            },
            "kept": {
                field: _distribution(kept, field)
                for field in (
                    "word_compressed_rate",
                    "variation_rate",
                    "matching_rate",
                    "alignment_gap",
                )
            },
        },
        "by_load_type": by_load_type,
    }


def _render_report_md(report: dict) -> str:
    """Human summary (markdown): scale, drop rates, distributions, pins."""
    counts = report["counts"]
    qc = report["quality_control"]
    gw = report["gateway"]
    lines = [
        "# Teacher distillation run",
        "",
        "## Scale",
        "",
        f"- corpus entries: {counts['corpus_entries']} (selected {counts['selected_entries']})",
        f"- chunks compressed: {counts['chunks']}",
        f"- labeled kept: {counts['labeled_kept']} "
        f"(dropped {counts['dropped']})",
        "",
        "## Quality control",
        "",
        f"- Variation Rate filter: top {qc['vr_drop_fraction']:.0%} dropped "
        f"(threshold {qc['vr_threshold'] if qc['vr_threshold'] is not None else 'n/a'})",
        f"- Alignment Gap filter: top {qc['ag_drop_fraction']:.0%} of survivors "
        f"dropped (threshold {qc['ag_threshold'] if qc['ag_threshold'] is not None else 'n/a'})",
        "",
        "## Alignment distribution (population -> kept)",
        "",
        "| metric | p50 | p90 | p95 | mean |",
        "|---|---|---|---|---|",
    ]
    for field in ("matching_rate", "alignment_gap", "variation_rate", "word_compressed_rate"):
        pop = report["distributions"]["population"].get(field, {})
        kept = report["distributions"]["kept"].get(field, {})
        lines.append(
            f"| {field} | {pop.get('p50')} -> {kept.get('p50')} "
            f"| {pop.get('p90')} -> {kept.get('p90')} "
            f"| {pop.get('p95')} -> {kept.get('p95')} "
            f"| {pop.get('mean')} -> {kept.get('mean')} |"
        )
    lines += [
        "",
        "## Teacher",
        "",
        f"- model pin: `{report['teacher']['model']}` "
        f"(served: {', '.join(report['teacher']['served_models']) or 'n/a'})",
        f"- prompt: {report['teacher']['prompt_version']}",
        "",
        "## Gateway billing",
        "",
        f"- fresh calls: {gw['calls_fresh']}, replayed: {gw['calls_reused']}",
        f"- crash journal: `{gw['journal']}` (ledger `{gw['ledger_id']}`)",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Freeze + validation (issue #20): the stage-3 data version anchor
# ---------------------------------------------------------------------------

FREEZE_RECORD_SCHEMA_VERSION = 1

FREEZE_ROLE = (
    "stage-3 data version anchor: every acceptance attempt (at most 3, "
    "roadmap 阶段 3 止损) trains on bytes pinned here; a per-attempt "
    "row-level resample derives from THIS pool and pins its own file "
    "sha256 + sampling rule in that attempt's run record"
)

_FREEZE_EXCLUSIONS = {
    "meetingbank": (
        "hard-excluded from training and eval (docs/data-strategy.md "
        "硬约束 1: it is the base checkpoint's training set) — enforced "
        "upstream by the corpus validators, re-pinned here by the corpus "
        "file shas"
    ),
    "customer_prompts": (
        "never used for training or eval (硬约束 2: privacy boundary, "
        "no exceptions)"
    ),
}

_MIX_ROW_POLICY = (
    "the frozen set keeps EVERY QC-passed row (no row-level downsampling — "
    "docs/baselines/2026-09-26-distill-sizing-decision.md); row-level "
    "rebalancing is a stage-3 per-attempt variable whose derived file "
    "sha256 + sampling rule land in that attempt's run record"
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_labeled_row(
    row: object, path: Path, line_no: int, seen_ids: set[str], errors: list[str]
) -> None:
    """One labeled.jsonl row against the issue-18 output schema (the same
    shape train.load_labeled_dataset enforces, collecting every problem)."""
    where = f"{path}: line {line_no}"
    if not isinstance(row, dict):
        errors.append(f"{where}: each row must be a JSON object")
        return
    row_id = row.get("id")
    if not isinstance(row_id, str) or not row_id.strip():
        errors.append(f"{where}: id must be a non-empty string")
    elif row_id in seen_ids:
        errors.append(f"{where}: duplicate id {row_id!r}")
    else:
        seen_ids.add(row_id)
    if row.get("load_type") not in _LOAD_TYPES:
        errors.append(
            f"{where}: load_type must be one of {list(_LOAD_TYPES)}, "
            f"got {row.get('load_type')!r}"
        )
    prompt = row.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append(f"{where}: prompt must be a non-empty string")
        return  # span bounds are meaningless without the prompt
    tokens = row.get("tokens")
    if not isinstance(tokens, list) or not tokens:
        errors.append(f"{where}: tokens must be a non-empty list")
        return
    last_end = 0
    for tok in tokens:
        if not (isinstance(tok, list) and len(tok) == 4):
            errors.append(f"{where}: token rows are [text, start, end, keep]")
            return
        _, start, end, keep = tok
        if not (isinstance(start, int) and isinstance(end, int)) or not (
            last_end <= start < end <= len(prompt)
        ):
            errors.append(
                f"{where}: span [{start}, {end}) out of bounds or unordered "
                f"(prompt is {len(prompt)} chars)"
            )
            return
        if keep not in (0, 1):
            errors.append(f"{where}: keep label {keep!r} must be 0 or 1")
            return
        last_end = end


def collect_distill_errors(
    out_dir: Path,
    *,
    freeze_path: Path | None = None,
    base_dir: Path | None = None,
) -> list[str]:
    """Validate a distillation output dir; empty list = valid.

    Checks, in order: manifest.json parses; labeled.jsonl exists, matches
    the manifest's sha256 + row count, and every row satisfies the schema
    (id unique, load_type known, token spans ordered in-bounds, keep in
    {0,1}); the manifest's counts are internally consistent (chunks -
    kept == dropped == VR + AG drop counts). With ``freeze_path`` the
    frozen identity is additionally re-proved against the live bytes:
    labeled sha/rows, the distill manifest sha, and every pinned corpus
    file + upstream manifest sha. Freeze-recorded relative paths resolve
    against ``base_dir`` (default: the current directory — run from the
    repo root).
    """
    out_dir = Path(out_dir)
    errors: list[str] = []
    if not out_dir.is_dir():
        return [f"{out_dir}: no such distillation output dir"]
    manifest_path = out_dir / "manifest.json"
    labeled_path = out_dir / "labeled.jsonl"

    manifest: dict | None = None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{manifest_path}: missing — not a distillation output dir")
    except (OSError, json.JSONDecodeError) as e:
        errors.append(f"{manifest_path}: cannot parse ({e})")

    labeled_sha: str | None = None
    row_count: int | None = None
    if labeled_path.is_file():
        labeled_sha = _sha256_file(labeled_path)
        seen_ids: set[str] = set()
        row_count = 0
        for line_no, line in enumerate(
            labeled_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            row_count += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"{labeled_path}: line {line_no}: cannot parse JSON: {e}")
                continue
            _check_labeled_row(row, labeled_path, line_no, seen_ids, errors)
    else:
        errors.append(f"{labeled_path}: missing")

    if manifest is not None:
        outputs = manifest.get("outputs", {}).get("labeled", {})
        counts = manifest.get("counts", {})
        drop_counts = manifest.get("quality_control", {}).get("drop_counts", {})
        if labeled_sha is not None and outputs.get("sha256") != labeled_sha:
            errors.append(
                f"{labeled_path}: sha256 {labeled_sha[:12]}… != manifest "
                f"outputs.labeled.sha256 {str(outputs.get('sha256'))[:12]}… — "
                "the labeled bytes drifted from their manifest"
            )
        if row_count is not None:
            if outputs.get("rows") != row_count:
                errors.append(
                    f"{labeled_path}: {row_count} rows != manifest "
                    f"outputs.labeled.rows {outputs.get('rows')!r}"
                )
            if counts.get("labeled_kept") != row_count:
                errors.append(
                    f"{manifest_path}: counts.labeled_kept "
                    f"{counts.get('labeled_kept')!r} != {row_count} rows in "
                    "labeled.jsonl — counts are inconsistent"
                )
        chunks, kept, dropped = (
            counts.get("chunks"),
            counts.get("labeled_kept"),
            counts.get("dropped"),
        )
        if None not in (chunks, kept, dropped) and chunks - kept != dropped:
            errors.append(
                f"{manifest_path}: counts.chunks ({chunks}) - labeled_kept "
                f"({kept}) != dropped ({dropped})"
            )
        vr_dropped = drop_counts.get("variation_rate")
        ag_dropped = drop_counts.get("alignment_gap")
        if None not in (vr_dropped, ag_dropped, dropped) and vr_dropped + ag_dropped != dropped:
            errors.append(
                f"{manifest_path}: quality_control drop counts "
                f"({vr_dropped} + {ag_dropped}) != counts.dropped ({dropped})"
            )

    if freeze_path is not None:
        errors.extend(
            _check_freeze_record(
                Path(freeze_path),
                manifest_path=manifest_path,
                labeled_sha=labeled_sha,
                row_count=row_count,
                base_dir=Path.cwd() if base_dir is None else Path(base_dir),
            )
        )
    return errors


def _check_freeze_record(
    freeze_path: Path,
    *,
    manifest_path: Path,
    labeled_sha: str | None,
    row_count: int | None,
    base_dir: Path,
) -> list[str]:
    """Re-prove a freeze record against the live bytes it pins."""
    errors: list[str] = []
    try:
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"{freeze_path}: cannot parse freeze record ({e})"]
    if freeze.get("schema_version") != FREEZE_RECORD_SCHEMA_VERSION:
        errors.append(
            f"{freeze_path}: schema_version must be "
            f"{FREEZE_RECORD_SCHEMA_VERSION}, got {freeze.get('schema_version')!r}"
        )
    distill = freeze.get("distill", {})
    frozen_labeled = distill.get("labeled", {})
    if labeled_sha is not None and frozen_labeled.get("sha256") != labeled_sha:
        errors.append(
            f"{freeze_path}: frozen labeled sha256 "
            f"{str(frozen_labeled.get('sha256'))[:12]}… != live "
            f"{labeled_sha[:12]}… — the frozen training set drifted"
        )
    if row_count is not None and frozen_labeled.get("rows") != row_count:
        errors.append(
            f"{freeze_path}: frozen labeled rows {frozen_labeled.get('rows')!r} "
            f"!= live {row_count}"
        )
    frozen_manifest_sha = distill.get("manifest_sha256")
    if (
        frozen_manifest_sha is not None
        and manifest_path.is_file()
        and frozen_manifest_sha != _sha256_file(manifest_path)
    ):
        errors.append(
            f"{freeze_path}: frozen distill manifest sha256 != live "
            f"{manifest_path} bytes — the manifest drifted from the freeze"
        )
    for entry in freeze.get("corpus", []):
        for key, recorded_sha, label in (
            ("file", entry.get("sha256"), "corpus file"),
            ("manifest", entry.get("manifest_sha256"), "corpus manifest"),
        ):
            recorded_path = entry.get(key)
            if not isinstance(recorded_path, str) or recorded_sha is None:
                errors.append(f"{freeze_path}: corpus entry lacks {key!r} / sha")
                continue
            live = Path(recorded_path)
            if not live.is_absolute():
                live = base_dir / live
            if not live.is_file():
                errors.append(f"{freeze_path}: pinned {label} {recorded_path} missing")
                continue
            actual = _sha256_file(live)
            if actual != recorded_sha:
                errors.append(
                    f"{freeze_path}: pinned {label} {recorded_path} sha256 "
                    f"{actual[:12]}… != frozen {str(recorded_sha)[:12]}…"
                )
    return errors


def build_freeze_record(
    out_dir: Path,
    *,
    record_dir: str,
    corpus_manifests: list[tuple[Path, str]],
    repo_commit: str | None = None,
    repo_dirty: bool | None = None,
) -> dict:
    """Assemble the stage-3 data-anchor freeze record (issue #20).

    The output dir is validated first — freezing a broken artifact is
    refused. The record pins: the labeled bytes + row count, the distill
    manifest bytes, the corpus files (identities as recorded in the
    distill manifest) AND their upstream manifests' live bytes (the whole
    freeze chain), teacher + QC + counts copied from the distill
    manifest, and the mix in both calibers (entry-level anchor vs
    row-level outcome; docs/baselines/2026-09-26-distill-sizing-decision.md).

    ``corpus_manifests`` pairs each upstream manifest's live path with the
    repo-relative identity string the record carries (pinned invocations
    supply these so the record never carries machine-specific paths).
    """
    out_dir = Path(out_dir)
    errors = collect_distill_errors(out_dir)
    if errors:
        raise DistillError(
            "refusing to freeze a broken distillation output: " + "; ".join(errors)
        )
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    counts = manifest["counts"]
    by_load_type = counts["by_load_type"]
    total_entries = sum(block["entries"] for block in by_load_type.values())
    total_kept = counts["labeled_kept"]

    def _pct(part: int, whole: int) -> float:
        return round(100.0 * part / whole, 1) if whole else 0.0

    corpus_files = manifest["corpus"]["files"]
    if len(corpus_manifests) != len(corpus_files):
        raise DistillError(
            f"corpus_manifests needs one (path, recorded) pair per corpus file "
            f"({len(corpus_files)}), got {len(corpus_manifests)}"
        )
    corpus = []
    for f, (live_path, recorded) in zip(corpus_files, corpus_manifests):
        corpus.append(
            {
                "file": f["file"],
                "sha256": f["sha256"],
                "entries": f["entries"],
                "manifest": recorded,
                "manifest_sha256": _sha256_file(live_path),
            }
        )
    teacher = manifest["teacher"]
    return {
        "schema_version": FREEZE_RECORD_SCHEMA_VERSION,
        "kind": "training-set-freeze",
        "role": FREEZE_ROLE,
        "generated_by": {
            "tool": "trillic.distill",
            "repo_commit": repo_commit,
            "repo_dirty": repo_dirty,
        },
        "distill": {
            "dir": record_dir,
            "manifest_sha256": _sha256_file(out_dir / "manifest.json"),
            "labeled": {
                "file": f"{record_dir}/labeled.jsonl",
                "sha256": _sha256_file(out_dir / "labeled.jsonl"),
                "rows": total_kept,
            },
        },
        "corpus": corpus,
        "teacher": {
            "model": teacher["model"],
            "prompt_version": teacher["prompt_version"],
            "prompt_sha256": teacher["prompt_sha256"],
            "served_models": teacher["served_models"],
        },
        "quality_control": manifest["quality_control"],
        "counts": counts,
        "mix": {
            "anchor": (
                "docs/training-mix.md: rag 30% / system_prompt 35% / "
                "dialogue 35% at ENTRY level (±5pt tolerance at sizing)"
            ),
            "entry_level_pct": {
                lt: _pct(by_load_type[lt]["entries"], total_entries)
                for lt in _LOAD_TYPES
                if lt in by_load_type
            },
            "row_level_pct": {
                lt: _pct(by_load_type[lt]["kept"], total_kept)
                for lt in _LOAD_TYPES
                if lt in by_load_type
            },
            "row_level_policy": _MIX_ROW_POLICY,
        },
        "exclusions": _FREEZE_EXCLUSIONS,
    }
