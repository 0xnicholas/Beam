# Leia

**中文** | [English](README.md)

自训 prompt 压缩模型项目:从语料构造、teacher 蒸馏到微调与评测的完整链路,
产出可直接替换压缩环节的抽取式 checkpoint。

> 2026-10-13 由 **trillic** 更名 **leia**(包名 `src/leia`、命令族 `leia …`、
> 远程仓 `0xnicholas/leia`);旧链接由 GitHub 重定向承接。范围与数据锚边界
> 见 `docs/decisions.md` 定案 7。

## 概览

**目标** — 在公开 LLMLingua-2 checkpoint(`bert-base-multilingual-cased-meetingbank`,
2024)之上领域微调出自有压缩模型,在压缩质量、压缩率、query-aware 能力三个轴上
超过它,让核心能力自主可控。

**产出物** — 一个 token 分类 checkpoint:逐 token 输出保留概率,与 LLMLingua-2
同接口,可 drop-in 替换现网压缩环节(替换的是权重,不是代码依赖也不是服务)。

**方法族** — 抽取式压缩:只删不改,输出是输入的严格子序列。明确不做生成式压缩
——那会废掉压缩环节"输出严格子序列"的安全保证(理由见 `docs/decisions.md`)。

## Leia 的作用

| 能力面 | 命令族 | 做什么 |
|---|---|---|
| 验收尺 | `leia eval run` · `eval sizing` | golden 集 + TOML 配置进 → 不可变 run 目录(`metrics.json` + `report.md`)出;是"微调后优于公开 checkpoint"的唯一度量,没有它不许声称赢 |
| golden 与语料 | `leia golden *` · `leia corpus *` | golden 集 schema 校验与生成、LongBench 切分/许可 manifest、训练语料构造与冻结再校验 |
| teacher 蒸馏 | `leia distill run` · `distill validate` | 训练语料 jsonl 进 → 带标签数据集 + 质控报告 + manifest 出 |
| 训练 | `leia train run` | 带标签数据集 → HF checkpoint + run record;产物必须过 delivery verify 两层才算成功 |
| 交付 | `leia delivery verify` · `delivery pack` | 按 drop-in 契约逐条校验候选 checkpoint;以校验通过为闸装配交付形态(sha256 清单 + 接入包) |

上表各命令族串起来即完整链路:**golden/语料冻结 → 蒸馏标注 → 微调 → 评测 → 交付**;
每一步的产物都带内容寻址与溯源,漂移由校验器拒绝而非人工比对。

## 技术说明

### 模型与接口(drop-in 契约)

一次"替换权重"是否可行,由这四条判定(不满足即要求接入方改代码,`delivery verify`
据此逐条校验):

- `config.json` 的 `architectures` 含 `BertForTokenClassification`,`num_labels == 2`,
  `id2label` = {0: drop, 1: keep}(位置语义固定:0 为删除类);
- tokenizer 为 **fast**(`return_offsets_mapping=True` 必须可用——force-keep 靠
  offsets 定位事实);
- 模型类暴露 **`.bert`** 属性(接入侧相似度 guardrail 直接调 `model.bert(**inputs)`;
  XLM-R 系为 `.roberta`,不满足);
- 与现网同架构基底(mBERT-base),延迟档案可直接对比。

### 评测方法

- **压缩率双口径**:tiktoken 计费口径(`cl100k_base`)+ 模型原生 token 计数器
  参数化(`word` / `wordpiece` / `sentencepiece` 三种 flavor,换基底只改配置
  不改代码);
- **fact recall 与 token F0.5**:纯函数,口径与运行时 guardrail 同源(正则逐字复用;
  F0.5 同公式,恒等对齐替代 embedding,harness 不带模型运行时);
- **任务级质量**:三类负载按 `load_type` 分派下游任务(RAG 问答 / system prompt
  约束遵守 / 对话记忆),原文与压缩后两份 prompt 各作答一次,LLM judge 按
  key_points 逐点 0/1 打分;质量 delta = 压缩后 − 原文,种子化 paired bootstrap
  (10k 次)给 95% CI 与"下界不为负"判据,judge rubric 版本号 + sha256 进报告;
- **扫档**:`[run] levels` 0.1–0.5 每档一节,压缩调用逐条计时,p50/p95 按档入报告;
- **假桩可演示**:压缩服务(`[sidecar]`)、作答模型与 judge(`[gateway]`)均为
  `stub` / `http` 可注入,stub 下全链路零网络零花费(压缩只降分,方向性可验证);
  `--resume-from` 以内容寻址复用上次运行的台账(重压缩逐字一致才复用,漂移即
  诚实重计费)。

### 数据与蒸馏

- **公开语料**:LongBench 子集,内容寻址半分(sha1 排序,前 ceil(n/2) 为 eval 半),
  同一条目永不跨 split;逐子集检查**训练用途**许可,research-only 授权只进 golden
  不进训练集(MeetingBank 语料被校验器硬拒);
- **合成场景族**:system prompt 与多轮对话各 10 族手写模板 + 种子化槽位合成;
  每族两个不相交整数种子池(eval 101–110 / train 901–910),两侧共享生成器代码、
  永不共享种子(同种子同分布的数据既当考卷又当教材 = 污染);
- **teacher 蒸馏**(LLMLingua-2 方法,arXiv:2403.12968):语料分块(≤512 token,
  句界优先)→ teacher 压缩 → 滑窗模糊匹配产出词级保留/删除标签 → VR 5% / AG 10%
  顺序质控;prompt 模板、阈值、参数 sha256 全部钉进 manifest;
- **计费面可控**:逐 chunk 的 crash journal 内容寻址,杀掉重跑只补未入账 chunk
  (零重复计费);`--chunk-budget` 按类钉死花费。

### 训练与可复现性

- 项目 venv 与 CI 刻意不含 torch;微调走专用 `.venv-train`(Python 3.12 +
  torch 2.2.2 / transformers 4.57.6),由 `scripts/train_pilot.py` 自动 bootstrap;
- 种子、超参、数据集 sha256、基底 revision 全钉进 run record;同 identity 重跑
  原地 re-pin,产物 byte-identical;
- 数据集字节先对照蒸馏 manifest 校验才放行训练。

### 交付与校验

- `delivery verify` 分两层:**静态层**默认依赖、零网络(架构类 / num_labels /
  id2label 语义 / fast tokenizer + offsets 可用);**加载层**(transformers / torch
  在场时,见「开发」)真实例化模型,断言 `.bert` 属性与运行时 offsets。缺席时显式
  标注"未验证",三态(已验通过 / 未验证 / 违规)永不相混;
- `delivery pack` 以 verify 通过为闸:逐文件 `sha256sum -c` 兼容清单 + 接入包
  (草案占位符 → 模型标识 / 目录摘要 / 清单哈希真实值,零手工填入);拒绝覆盖
  已存在目录,同输入两次打包逐字节一致。

### 工程约定

- **零网络测试**:上下游全部可注入假桩,`uv run pytest` 不触网;
- **内容寻址 + 冻结**:golden、语料、蒸馏产物均以 sha256 冻结,manifest 重生成
  漂移即拒;每个产物记 `generated_by`(tool / repo_commit / repo_dirty);
- **纯函数优先**:指标与 bootstrap 为纯函数,数值由种子化字面量单测钉死;
- **密钥不进仓**:服务密钥只经环境变量注入,不落配置文件。

## 目录结构

```
src/leia/     harness 与管线(CLI、评测、语料、蒸馏、训练、交付)
eval/         golden 集、run 配置、生成 manifest、离线 tiktoken/tokenizer 缓存
training/     训练语料与蒸馏产物、冻结 manifest
scripts/      重建入口(语料 / 合成 / 蒸馏 / 冻结 / 训练 pilot)
tests/        全量测试(零网络)
docs/         决策、roadmap、数据策略、评测、交付、冻结基线归档
runs/         运行输出(gitignored;不可变 run 目录)
```

## 开发

技术栈:Python 3.12+,uv 管理依赖,pytest 测试。依赖刻意保持最小:httpx、
tiktoken、tokenizers(测试用 pytest),不含训练栈。

```bash
uv sync                    # 安装依赖
uv run pytest              # 全量测试(零网络:上下游用确定性假桩)
uv run leia eval run \
  --config eval/configs/fixture.toml \
  --golden eval/golden/fixture.jsonl \
  --out runs               # 跑 fixture 迷你集(stub 模式,零网络零花费)
```

可选依赖与专用环境:

```bash
# delivery verify 加载层(真实例化断言 `.bert` + offsets)需要 transformers + torch;
# 项目 venv 刻意不含训练栈,用训练环境跑即可(自举见 scripts/train_pilot.py):
.venv-train/bin/leia delivery verify <checkpoint dir>

# 训练侧测试(torch 微调回路)
.venv-train/bin/python -m pytest tests/test_trainloop.py

# 或者给项目 venv 加装可选依赖组。注意 torch 对 macOS x86_64 的轮子止于
# 2.2.2,该平台请走上面的 .venv-train 路径。
uv sync --group load
```

## 文档地图

- `CONTEXT.md` — 项目术语表(北极星 / 验收尺 / v1·v2 / 产物包 / 接入包 / 供货)
- `docs/decisions.md` — 立项决策(含修订史、更名记录与排除项汇总)
- `docs/roadmap.md` — 阶段结构、门禁与止损(阶段结构唯一权威)
- `docs/data-strategy.md` — 数据策略:蒸馏管线、语料来源与配比、硬约束
- `docs/training-mix.md` — 训练语料配比设计(v1:公开打底 + 两类加重)
- `docs/evaluation.md` — 验收尺:任务级评测基线的口径与判据
- `docs/delivery/refine-integration.md` — 接入包:drop-in 契约、接入改动集、切换/回滚 runbook
- `docs/baselines/` — 冻结基线归档(定容决策、双 checkpoint 对照、阶段出口核销)
- `docs/references.md` — 论文、旧项目文档、对标调研的索引
- `docs/agents/` — agent 技能约定(issue tracker / triage 标签 / domain 文档)

## 状态

**阶段 1(评测基线 = 验收尺):完成。**149 条 golden(RAG 49 + system 50 + 对话 50)
× 0.1–0.5 扫档的双 checkpoint 基线、延迟档案、golden 冻结(`fb728d6a5042…`),
出口核销见 `docs/baselines/2026-09-12-stage1-exit.md`。

**阶段 2(数据管线):进行中。**训练语料 1000 条冻结(公开打底 300 + 合成 700,
条目层配比 30/35/35);teacher 蒸馏 pilot 255 条打通(真网关断点恢复实测,
零重复计费);训练 plumbing pilot 跑通(mBERT-base 微调,checkpoint 过 delivery
verify 两层,纯 plumbing、不做质量声称)。剩余:`#20` 全量蒸馏 + 训练集冻结 +
阶段出口核销(定容决策已归档,见 `docs/baselines/2026-09-26-distill-sizing-decision.md`)。

阶段 3–5(v1 微调验收 / v2 query-aware / 交付)的能力线与止损见 `docs/roadmap.md`。
