# Beam

Self-trained prompt compression: an end-to-end pipeline — corpus construction,
teacher distillation, fine-tuning, evaluation — that produces an extractive
compression checkpoint you can drop in as-is.

**English** | [中文](README.zh-CN.md)

## Overview

**Goal** — Domain-fine-tune our own compression model on top of the public
LLMLingua-2 checkpoint (`bert-base-multilingual-cased-meetingbank`, 2024) and
beat it on compression quality, compression ratio and query-awareness, so the
core capability is self-owned.

**Deliverable** — A token-classification checkpoint: per-token keep probability,
same interface as LLMLingua-2, a drop-in replacement for the compression stage
in production (it replaces weights — it is neither a code dependency nor a
service).

**Method family** — Extractive compression: delete only, never rewrite, so the
output is a strict subsequence of the input. Generative compression is
explicitly out of scope — it would forfeit the "output is a strict subsequence"
safety guarantee (rationale in `docs/decisions.md`).

## What Beam does

| Capability | Commands | In → out |
|---|---|---|
| Yardstick | `beam eval run` · `eval sizing` | golden set + TOML config in → immutable run directory (`metrics.json` + `report.md`) out. The only measure of "better than the public checkpoint": no yardstick, no claims. |
| Golden sets & corpora | `beam golden *` · `beam corpus *` | golden-set schema validation and generation, LongBench split/license manifest, training-corpus construction and freeze re-validation |
| Teacher distillation | `beam distill run` · `distill validate` | training-corpus jsonl in → labeled dataset + QC report + manifest out |
| Training | `beam train run` | labeled dataset → HF checkpoint + run record; the artifact must pass both delivery-verify layers |
| Delivery | `beam delivery verify` · `delivery pack` | per-rule validation against the drop-in contract; gated on a passing verify, assembles the delivery form (sha256 manifest + integration pack) |

Chained together, these command families are the whole pipeline: **freeze golden
sets and corpora → distill labels → fine-tune → evaluate → deliver**. Every
artifact is content-addressed and provenance-stamped, and drift is rejected by
validators rather than eyeballed.

## Technical notes

### Model and interface (drop-in contract)

Four rules decide whether a checkpoint can replace the weights; failing any one
means the consumer changes code, and `delivery verify` checks them one by one:

- `config.json` `architectures` contains `BertForTokenClassification`,
  `num_labels == 2`, `id2label` = {0: drop, 1: keep} (positional semantics are
  fixed: index 0 is the drop class);
- the tokenizer is **fast** (`return_offsets_mapping=True` must work — force-keep
  locates facts through offsets);
- the model class exposes a **`.bert`** attribute (the consumer's similarity
  guardrail calls `model.bert(**inputs)` directly; XLM-R models expose
  `.roberta` and fail this rule);
- same base architecture as production (mBERT-base), so the latency profile is
  directly comparable.

### Evaluation

- **Two compression-ratio calibers**: the tiktoken billing caliber
  (`cl100k_base`) plus a parameterized native token counter (`word` /
  `wordpiece` / `sentencepiece`) — swapping the base model is a config change,
  not a code change;
- **fact recall and token F0.5**: pure functions sharing the runtime guardrail's
  caliber (same regex verbatim, same formula, identity alignment instead of
  embeddings — the harness carries no model runtime);
- **Task-level quality**: three load types dispatch downstream tasks (RAG QA /
  system-prompt constraint following / dialogue memory); original and compressed
  prompts are each answered once, and an LLM judge scores key_points 0/1.
  Quality delta = compressed − original; a seeded paired bootstrap (10k) yields
  the 95% CI and the "lower bound not negative" criterion; the judge rubric
  version and sha256 go into the report;
- **Sweep**: `[run] levels` 0.1–0.5, one section per level; per-call compression
  timing, p50/p95 per level;
- **Runnable end to end on stubs**: the compression service (`[sidecar]`), the answer
  model and the judge (`[gateway]`) are all injectable `stub` / `http`; under
  stubs the whole pipeline runs with zero network and zero cost (compression only
  lowers scores, which keeps the direction verifiable). `--resume-from` reuses a
  previous run's ledger by content address, reusing the compressed side only when
  the recompression is byte-identical — drift is honestly re-billed.

### Data and distillation

- **Public corpora**: LongBench subsets, content-addressed halving (sha1 sort,
  first ceil(n/2) items form the eval half) — no item ever crosses a split;
  per-subset **training-use** license checks, research-only grants reach the
  golden set only (MeetingBank corpora are hard-rejected by the validator);
- **Synthetic scenario families**: 10 handwritten family templates each for
  system prompts and multi-turn dialogue, plus seeded slot synthesis. Each
  family has two disjoint integer seed pools (eval 101–110 / train 901–910):
  shared generator code, never shared seeds — same-seed, same-distribution data
  serving as both exam and textbook is contamination;
- **Teacher distillation** (LLMLingua-2 method, arXiv:2403.12968): chunk the
  corpus (≤512 tokens, sentence-boundary first) → teacher compression → sliding
  fuzzy matching producing word-level keep/drop labels → sequential VR 5% /
  AG 10% quality control. Prompt template, thresholds and parameters are pinned
  by sha256 in the manifest;
- **Controllable billing**: a per-chunk crash journal keyed by content address
  — kill a run and relaunch, and you pay only for chunks not yet banked (zero
  double-billing); `--chunk-budget` pins spend per class.

### Training and reproducibility

- The project venv and CI deliberately carry no torch; fine-tuning runs in a
  dedicated `.venv-train` (Python 3.12 + torch 2.2.2 / transformers 4.57.6),
  bootstrapped by `scripts/train_pilot.py`;
- seeds, hyperparameters, dataset sha256 and base revision are all pinned in the
  run record; re-running the same identity re-pins in place, byte-identical;
- dataset bytes are validated against the distillation manifest before training
  is allowed to start.

### Delivery and verification

- `delivery verify` has two layers. The **static layer** runs on default
  dependencies with zero network (architecture class, num_labels, id2label
  semantics, fast tokenizer with usable offsets). The **load layer** — with
  transformers / torch present, see Development — instantiates the real model and
  asserts the `.bert` attribute and runtime offsets. When it cannot run, the
  result is explicitly reported as "unverified": the three states (verified /
  unverified / violation) never blur into each other;
- `delivery pack` is gated on a passing verify: a per-file `sha256sum -c`
  compatible manifest plus the integration pack (draft placeholders → real model
  id, directory digest and manifest hash, zero hand-filling). It refuses to
  overwrite an existing directory, and packing the same input twice is
  byte-identical.

### Engineering conventions

- **Zero-network tests**: every boundary is an injectable stub — `uv run pytest`
  never touches the network;
- **Content addressing and freezes**: golden sets, corpora and distillation
  outputs are frozen by sha256; regeneration drift is rejected by validators;
  every artifact records `generated_by` (tool / repo_commit / repo_dirty);
- **Pure functions first**: metrics and bootstrap are pure, with numbers pinned
  by seeded literal unit tests;
- **No secrets in the repo**: service keys are injected through environment
  variables only.

## Layout

```
src/beam/     harness and pipeline (CLI, eval, corpora, distillation, training, delivery)
eval/         golden sets, run configs, generated manifests, offline tiktoken/tokenizer caches
training/     training corpora and distillation outputs, frozen manifests
scripts/      rebuild entry points (corpus / synthetic / distill / freeze / train pilot)
tests/        full test suite (zero network)
docs/         decisions, roadmap, data strategy, evaluation, delivery, frozen baseline archive
runs/         run outputs (gitignored; immutable run directories)
```

## Development

Stack: Python 3.12+, uv for dependencies, pytest for tests. Dependencies stay
deliberately minimal: httpx, tiktoken, tokenizers (pytest for tests), with no
training stack.

```bash
uv sync                    # install dependencies
uv run pytest              # full suite (zero network: deterministic stubs everywhere)
uv run beam eval run \
  --config eval/configs/fixture.toml \
  --golden eval/golden/fixture.jsonl \
  --out runs               # fixture mini-set (stub mode, zero network, zero cost)
```

Optional dependencies and dedicated environments:

```bash
# The delivery load layer (real instantiation asserting `.bert` + offsets) needs
# transformers + torch. The project venv deliberately has no training stack, so
# run it from the training environment (bootstrap: scripts/train_pilot.py):
.venv-train/bin/beam delivery verify <checkpoint dir>

# Training-side tests (torch fine-tune loop)
.venv-train/bin/python -m pytest tests/test_trainloop.py

# Alternatively, add the optional dependency group to the project venv. Note that
# torch wheels for macOS x86_64 stop at 2.2.2 — on that platform use .venv-train
# as shown above.
uv sync --group load
```

## Documentation map

- `CONTEXT.md` — glossary (north star / yardstick / v1·v2 / artifact pack / integration pack / supply)
- `docs/decisions.md` — project decisions (revision history, rename record, exclusions)
- `docs/roadmap.md` — stage structure, gates and stop-loss (sole authority on stages)
- `docs/data-strategy.md` — data strategy: distillation pipeline, corpora sources and mix, hard constraints
- `docs/training-mix.md` — training-corpus mix design (v1: public base plus two weighted layers)
- `docs/evaluation.md` — the yardstick: task-level evaluation caliber and criteria
- `docs/delivery/refine-integration.md` — integration pack: drop-in contract, consumer changes, switch/rollback runbook
- `docs/baselines/` — frozen baseline archive (sizing decisions, dual-checkpoint comparison, stage exit reviews)
- `docs/references.md` — index of papers, predecessor-project docs and comparison research
- `docs/agents/` — agent skill conventions (issue tracker / triage labels / domain docs)

## Status

**Stage 1 (evaluation baseline = yardstick): done.** 149 golden items (RAG 49 +
system 50 + dialogue 50) swept 0.1–0.5 against both checkpoints, plus the latency
profile and the golden freeze (`fb728d6a5042…`); exit review in
`docs/baselines/2026-09-12-stage1-exit.md`.

**Stage 2 (data pipeline): in progress.** Training corpus of 1000 items frozen
(public base 300 + synthetic 700, item-level mix 30/35/35); teacher distillation
pilot of 255 items working end-to-end (crash recovery measured against the real
gateway, zero double-billing); training plumbing pilot done (mBERT-base
fine-tune whose checkpoint passes both delivery-verify layers — plumbing only, no
quality claims). Remaining: `#20` full-scale distillation + training-set freeze +
stage exit review (sizing decision archived in
`docs/baselines/2026-09-26-distill-sizing-decision.md`).

Stages 3–5 (v1 fine-tune acceptance / v2 query-aware / delivery), with their
capability lines and stop-loss, live in `docs/roadmap.md`.
