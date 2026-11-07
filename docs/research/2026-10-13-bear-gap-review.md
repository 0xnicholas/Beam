# bear(The Token Company)增量复盘:Gap 与下一版迭代参考

调研日期:2026-10-13。**定位:增量**。基线与深挖层见
`docs/research/bear.md`(2026-08-30),本文只记两件事:(a) 相对该快照的变化,
(b) 这些变化对 Beam **当前状态**(阶段 1 完成、阶段 2 进行中)的 gap 含义。
不重复 bear.md 已确立的结论(抽取式 token 分类本体、与 LLMLingua-2 同族、
厂商数字未经独立验证、两家数字口径互不证伪);需要背景时直接引用其章节号。

**北极星纪律(先行声明)**:TTC 框定能力面,其**任何数字不进 Beam 的验收标准**
(见根目录 CONTEXT.md)。本文出现的所有准确率/节省率/延迟类数字均为厂商自述
或单方观测,引用时保持该定性。

标注约定(沿用 bear.md):[官方] = TTC 自有渠道自述(官网/docs/blog/OpenAPI/
自家包仓库);[官方代码] = TTC 公开仓库中的代码事实;[第三方] = 独立来源;
[推断] = 本文分析;[论文] = arXiv 文献。抓取日期除注明外均为 2026-10-13。

**本轮硬约束(沿用 bear.md)**:不注册、不调用其 API、不安装其 SDK。
公开页面、公开仓库、公开包元数据为唯一证据面。因此"注册后才可见"的
一切(免费层是否真实、私有 preview 的 schema、dashboard)只能记为未能确认。

---

## 0. 新增事实总览(相对 2026-08-30 基线)

1. **出现第二条公开产物线 `Endor`(本轮最大变化)**:GitHub org 新增第 4 个仓库
   `TheTokenCompany/endor-python`(创建 2026-10-06,最后 push 2026-10-12),
   PyPI 包 `endor`(0.0.1 @10-06 → **0.6.0 @10-12,7 天内 14 个版本**),MIT。
   包摘要:"Python SDK for Endor: decisions with System One models, and LoRA
   fine-tuning on your own data"。[官方] + [官方代码]
2. **Endor 的形态是"决策模型 + 托管微调平台"**,不是压缩:输入 `state`(文本或
   JSON)+ 若干命名问题,单次前向返回每个选项的概率,**不生成文本、无采样、无
   temperature**;三类问题 `Noul`(是/否,给 P(true))、`Choice`(≤255 个命名选项)、
   `Score`(2–10 个有序档,给期望档位)。base model 为 `decider-2b` / `gev-26b`,
   base URL `api.endor.thetokencompany.com`,key 前缀 `edk_`。[官方代码]
3. **Endor 微调 = LoRA + GPU 秒计费,训练循环由调用方在 Python 里驱动**:数据集
   ≤50k 行、`rank=16/alpha=32` 默认、`forward_backward`/`optim_step`/
   `save_checkpoint` 显式分步、自动 10% holdout 且**先测未调的 base 再测自己的**、
   W&B 集成、每会话最低 60 GPU-秒、5 个并发 run、每 org 7 project。权重可下载
   (PEFT adapter + manifest,逐文件 sha256 校验);另有 `managed` project =
   Endor 用你的决策数据持续学习,售价 +50%(标 "coming soon")。[官方代码]
4. **Endor 的 decisions 底层是第三方 TypeSafe 的 API**(`POST /v1/systemone`),
   README 明写"未改动的 TypeSafe client 换 base_url + model 即可用端到端"。
   [官方代码]
5. **SDK 里有两个未公开端点**:`POST /v1/chat/compress` 与 `POST /v1/search`
   (Python `_client.py:221`、`:266`;Node `client.ts:124`、`:204`)。
   `openapi.json` 只描述 `/v1/compress` 且自称"documented public surface";
   `/docs/llms.txt`、`llms.txt`、`llms-full.txt`、`agents.md` 全文
   **零次**出现 `search` 或 `/v1/chat`。[官方代码] + [官方]
6. **`/v1/chat/compress` 把"前缀缓存"做成了可观测接口**:整段 messages 一次上传,
   `format: openai|anthropic`,`aggressiveness` 可传 `{role: float}`,
   另有 `system` / `strip_server_tool_results` / `skip_tool_use_ids`;
   响应含 **`cache_hits` / `cache_misses` / `compression_time`** —— 服务端按段
   缓存压缩结果并把命中数回传。[官方代码]
7. **`/v1/search` = 搜索 + 压缩一体**:`query` → 压缩后的结果列表
   (url/title/content/score),`search_depth: basic|advanced`,默认
   `aggressiveness=0.3`。[官方代码]
8. **bear.md 遗留的 assistant 矛盾被代码仲裁**:SDK 0.5.0(2026-08-13)起
   **默认压缩 assistant/agent 轮** —— Python `_compress.py:16`
   `DEFAULT_ROLES = ("user","system","tool","assistant")`;Node
   `tests/assistant-default.test.ts` 明确断言"scalar aggressiveness 必须展开到
   含 assistant,不含 assistant 键的 per-role dict 是 KV-cache opt-out"。
   而官网 `/docs/aggressiveness`、`/docs/openai` 仍写 "Assistant messages are
   never compressed"。→ **冲突的错方是官网 docs,不是 SDK**。[官方代码]
9. **默认档出现第四个数字**:Python SDK README 写 `aggressiveness`
   "(0.0 – 1.0, **default 0.5**)",但代码 `DEFAULT_AGGRESSIVENESS = 0.2`
   (`_compress.py:12`)、Node `options.aggressiveness ?? 0.2`、
   OpenAPI `default: 0.2`、官网 docs "Default: 0.2"。
   → **README 错,0.2 为准**。[官方代码]
10. **档位–场景映射存在三套并存口径**:渲染页 `/docs/compression` 是
    Light 0.05–0.15 / Moderate 0.15–0.4 / Aggressive 0.4–0.9(与 8-30 基线一致);
    **机器可读面**(`/docs/compression.md`、`/docs/llms.txt`,即 agent 实际读的
    那份)是 Light 0.1–0.3 / Moderate 0.4–0.6 / Aggressive 0.7–0.9;
    OpenAPI 描述是 0.05–0.2(供模型直接阅读的文本)/ 0.5–0.8(对话历史)。
    → **渲染面与机器面互斥**。[官方]
11. **新增公开文档与站点能力**:docs 新增 `/docs/hybrid`、`/docs/app-id`、
    `/docs/stats`、`/docs/troubleshooting`、`/docs/data-retention`、
    `/docs/anthropic`、`/docs/openrouter`、`/docs/vercel-ai`;站点新增
    `/pricing`、`/about`;全站每页可加 `.md` 后缀或发 `Accept: text/markdown`
    取 markdown;另有 `/api/openapi.yaml`。[官方]
12. **`hybrid-1` 路由模型(新 SKU,非压缩线)**:gate 模型 + synthesizer,
    alpha 主导、把简单步骤路由给便宜的 beta worker,声称 gate/synthesis 免费、
    按 list price 不加价;模型名 `hybrid-1/glm-5.3+glm-5.3-flash`,走
    **OpenAI 兼容 chat completions**(`api.thetokencompany.com/v1`),
    `x-hybrid-session` 头做 run 归因,响应带 `x_hybrid.served_by` /
    `cost.usd` / `cost.by_role`,`GET /v1/hybrid/models` 列可用模型。
    仅 approved customers。**这是端点族从"一个压缩端点"扩到"压缩 + 推理"的
    信号**。[官方]
13. **零数据保留的确切边界公开**(基线未覆盖):可申请账户级 ZDR,ZDR 下
    prompt/output **完全不落库**,但**时间戳与输入/输出 token 数仍保留**;
    非 ZDR 时 prompt/output 在推理期间 + **3600 秒缓存窗口**内保留后自动删除;
    ZDR 开启后官方无法回溯排障。[官方]
14. **`protect` 被官方标注为 experimental**:`/docs/protect-text` 首行
    "This feature is experimental" —— 8-30 基线记录的观察是"无 experimental 字样"。
    (措辞变化本身即证据;无法排除上轮漏看,但两轮读的是同一页。)[官方]
15. **免费层表述只出现在 LLM 面**:`llms.txt` / `llms-full.txt` 写
    "Free tier: up to 1B processed tokens per month, bear-2 & bear-1.2";
    而 `/pricing` 只有 Pro / Enterprise 两档(CTA 均是 Get a quote / Talk to us)、
    `/docs/quickstart` 仍写 "currently invite-only"、站点主 CTA 是 `/meet` 预约。
    → 三处互斥,如实记录。[官方]
16. **gzip 吞吐表(spec 外的新数字)**:`/docs/compression` 给出
    10k→182K tok/s(1.9×)、100k→887K tok/s(1.9×)、1M→**1.44M tok/s**(2.2×)。
    注意这是**吞吐**口径,与首页 "<50ms"、"p95 150ms"、SDK README "100K tokens
    in ~85ms" 是三种不同量,不可互相换算。[官方,厂商自述]
17. **`/benchmarks` 是悬空引用**:该路径返回 200,但正文渲染出的是 logo 尺寸 /
    品牌色 / blog 索引(疑似品牌素材页),不在 `sitemap.xml` 内;`/benchmarks.md`
    404;而 `llms-full.txt` 把 "Benchmarks" 指向该路径。[官方]
18. **Benchmarks 仓库内容零变化**:`main` 的 HEAD 仍是 `9271804…`
    (2026-04-22,"Add EC2 benchmark scripts, long-run monitor, and latency
    report");仓库 `pushed_at` 仍是 2026-07-29(与基线一致,main 无新提交);
    `config.yaml` 里 `bear_models` 仍是 `["bear-1.2","bear-1.1"]`、
    judge/作答模型仍是 `gpt-5-mini`;QA 结论目录依旧未提交。[官方代码]
19. **SDK 版本纹丝不动**:PyPI `the-token-company` 最新 **0.5.1**
    (2026-08-13 21:40),npm `the-token-company` 最新 **0.5.0**
    (2026-08-13 00:03);Python SDK 最后一次 commit 也是 2026-08-13
    ("fix: don't leak TTC key into a caller-supplied httpx client")。
    org 里该仓 `updated_at` 是 2026-10-09 但 `pushed_at` 停在 08-13
    → 元数据/互动变化,**不是新提交**。[官方]
20. **客户端 fail-open 只覆盖 3 个 wrapper 中的 2 个**:Node `src/openai.ts`
    与 Python `anthropic.py` 在压缩失败时 warn + **原样发送未压缩 messages**
    ("a compression-backend fault must never break the customer's underlying
    LLM call");但 **Python `openai.py` 的 wrapper 没有 try/except**
    (0.5.1 源码,异常会直接抛给调用方)。
    → 基线记录的"fail-open"不只是服务端承诺,SDK 侧有独立一层,**但实现不齐**。
    [官方代码]
21. **第三方实机观测(bear.md 未收录,2026-06-20 成文)**:MIT、246 stars 的
    Accordion 仓库 ADR-0024 记录了对 bear-2 的实机 API 测试结论:
    τ=0.2 在散文上省 **~10–15%** 且输出仍可读;τ=0.5 省 **~45%** 但输出
    telegraphic、不能直接交给 agent;bear-2 对**纯结构化内容(JSON/代码)自然
    no-op(~0% 节省)**,但在混排块里会啃掉少量空白。另明确记录:
    压缩改写前缀会**打掉 provider 的 prompt cache**。[第三方]
    (脚本未公开,位于私有桌面路径 → 有数字但**不可复现**。)
22. **第三方:ReCompress(UC Berkeley 黑客松,TTC 赞助的"最佳压缩模型"奖)**:
    MIT、Zenodo DOI 预印本 + Colab 复现 notebook;query-aware **rewriting**
    蒸馏到 Qwen2.5-1.5B + LoRA;HotpotQA 上下文压到 ~3.5% token 仍答对;
    作者自述"不是 bear 的竞品,是 bear 明确让出的 abstractive/query-aware 那一段"。
    [第三方]
23. **第三方集成面成立但无复现评测**:GitHub 上存在若干 TTC API 的第三方集成
    (opencode 插件 2026-07-09、用 bear-1.2 的 MCP server、PromptOpsKit 引用等),
    均为接入,不是对 bear 声明的独立复现测量。[第三方]
24. **状态页只监控三项**:`status.thetokencompany.com`(Better Stack)监控
    app dashboard / compression API / marketing site,90 天 100% uptime,
    **未单列 Endor 或 hybrid**。[官方]

---

## A. 重抓触发逐条核查(bear.md 末尾五项)

| # | 触发条件 | 结论 | 证据 |
|---|---|---|---|
| 1 | bear-2-finance 转 GA(重查 openapi.json diff) | **未成立** | blog 页头仍是 "now in private preview"(August 2026),[官方];`openapi.json` 仍 **v2.2.0**、唯一端点 `POST /v1/compress`、请求体仍只有 `model` / `input` / `compression_settings.aggressiveness` / `app_id`,**无任何 query/task/focus/budget 字段**;全站 docs 无 query-aware 参数页 [官方] |
| 2 | 新模型版本(bear-3 或新变体) | **未成立(压缩线)**;但新增两个非压缩 SKU | 压缩线模型表仍只有 `bear-2` / `bear-1.2`;SDK 常量 `BEAR_1/1.1/1.2/2`;全站无 bear-3 [官方] + [官方代码]。**新出现**:`hybrid-1`(路由,§0.12)与 Endor 的 `decider-2b` / `gev-26b`(§0.2)——不同品类 [官方] |
| 3 | SDK 0.6+ | **未成立** | PyPI 0.5.1 / npm 0.5.0,均 2026-08-13 起未动;Python SDK 末次 commit 2026-08-13 [官方] |
| 4 | Benchmarks 仓库新 push | **未成立** | `main` HEAD `9271804…` @2026-04-22;仓库 `pushed_at` 2026-07-29(与基线同值),`config.yaml` 与目录树逐项核对无变化 [官方代码] |
| 5 | 独立第三方可复现实测 | **未成立**(但有两处新证据) | ① Accordion ADR-0024 有实机数字但**脚本未公开** → 不可复现 [第三方];② ReCompress 可复现(DOI + Colab)但评的是**自己的改写模型**,不是 bear 的声明 [第三方]。→ 仍**无人**对 bear 的准确率声明做过可复现的独立验证 |

**触发 1 的附加收获**:bear-2-finance 的完整表 1 显示,两个 reader 在
**保留率 90%→50% 全程与全文档基线不可区分**,但 **50% 以下开始掉**
(Claude Haiku 4.5:全文档 81.1 → 33% 档 77.7 → 22% 档 74.6;Gemini 3.5
Flash Lite:79.3 → 76.9 → 73.8)。即"保留预算"这条曲线有一个**拐点在 50% 附近**;
bear.md §B.1 只记了"90%→50% 不可区分",本轮补上拐点之后的形状。[官方,厂商自述]

---

## B. Gap 分析(相对 Beam 当前状态)

Beam 现状锚点:阶段 1 完成(149 条 golden 冻结 `fb728d6a5042…`,双 checkpoint
扫档 0.1–0.5,延迟 p95 已测);阶段 2 进行中(1000 条训练语料冻结、255 条蒸馏
pilot、plumbing pilot 完成,`#20` 未闭环);v2(query-aware)为**数据形态扩展**,
进入门是 v1 验收通过;硬规则:assistant/已缓存前缀不可压缩。

### (1) 可在本仓闭合的 gap

**G1 —— 结构化内容没有考卷,也没有观测项。**
证据:第三方实机观测 bear-2 对 JSON/代码"自然 no-op(~0% 节省)"(§0.21);
TTC 官方也把 JSON schema / SQL / config 列入 "when not to use",并要求
`protect_json` 或 `<ttc_safe>`(bear.md §C.3 + 本轮 `/agents.md`)。
Beam 的 golden 三类负载(RAG 长文 / system prompt / 多轮对话)里没有"结构化
段落"这一类;**且没有任何指标度量"不该动的没被动"** —— fact recall 与 token F0.5
都只度量"该留的留了没"。
闭合方式:harness 增加一个观测项(不改题、零成本),例如"结构化段落压缩后
逐字不变的比例"。注意这不是训练目标 —— 在严格子序列 + 删除语义下,"不动"更
可能来自阈值/正则(宿主已有 `_FACT_PATTERN`),所以它是**观测**而非能力。

**G2 —— "不破坏已缓存前缀"是硬规则,但没有可执行的检验。**
证据:TTC 把这件事做成了接口语义 —— `/v1/chat/compress` 返回
`cache_hits` / `cache_misses`,服务端按段缓存并复用(§0.6)[官方代码];
第三方独立记录"压缩改写前缀会打掉 provider prompt cache"(§0.21)[第三方];
decisions.md §5 已把"assistant 消息与已缓存前缀不可压缩"定为硬约束。
但 Beam 现有评测是**整段压缩**口径,没有"多轮场景下,已发出的前缀在增量压缩后
逐字不变"的断言 —— 硬规则目前只停留在设计前提。
闭合方式:在 harness 的多轮场景里加一条前缀不变性断言(零成本,不改 golden 内容,
只加一层观测)。

**G3 —— 扫描上沿压在自家拐点上,看不到曲线形状。**
证据:三处独立信号都指向"存在拐点,且位置随语料/模型变" —— TTC finance 表 1
(90–50% 平台、50% 以下掉,§A 触发 1 附加收获)[官方];SQuAD 2.0 高档掉到基线以下
(bear.md §A.2)[官方];Beam 自测 mBERT 0.4 档质量 delta CI 下界已转负
(-0.0670 [-0.1075, -0.0279],`docs/evaluation.md`)。
Beam 现扫 0.1–0.5,上沿刚好落在自家拐点上,报告里看不到平台段的长度。
评估成本档:把 0.6 / 0.7 两档补进扫档(纯评测,不改模型)。

**G4 —— 档位语义在厂商侧是漂移的,己方报告须自证口径。**
证据:同一厂商的默认档有 0.2 与 0.5 两个说法、档位–场景映射有三套并存
(§0.9、§0.10)。这不是 Beam 的缺陷,但它说明"档位数字"本身不是可移植语义。
建议核对项:对照报告与接入包应显式写出**宿主侧默认档位的来源与数值**
(现网 `compressor.py` 的阈值),使"同档比较"在报告里可自证。

### (2) 属于宿主产品、本仓记录但不做的 gap

依 decisions.md §6(产品化特性归 tokencamp-pro,不在本仓):

- `app_id` 维度用量分账、`client.compression` 客户端统计、gzip 请求体;
- wrapper 覆盖矩阵(OpenAI / Anthropic / OpenRouter / Vercel AI SDK;两语言);
- **`/v1/search`(= 检索 + 压缩一体)** 与 **`hybrid-1`(路由)** —— 品类扩张,
  不是压缩能力本身;
- ZDR / BAA / on-prem / 状态页等信任面(site 侧新增,与模型无关);
- **per-role 分档 + "传一个省略 `assistant` 键的 dict"是官方钦定的 KV cache
  逃生口**(§0.8)[官方代码] —— 这是 decisions §5 的**宿主侧设计输入**;
  本仓侧只需要做到:不把"是否压缩 assistant"写进模型逻辑,而是留给调用方
  用数据形态(只对 context 打标)与阈值表达。这一点与 roadmap 阶段 4 的
  `[task; context]` 设计同向,无冲突。

### (3) 明确不追(non-goals)

| 不追的东西 | 来源 | 理由 |
|---|---|---|
| 生成式/改写式压缩 | ReCompress(第三方,§0.22) | decisions.md 排除项:破坏严格子序列保证;与 refine 的 rewrite 阶段功能重叠 |
| 决策模型 / 路由 gate | Endor(§0.1–4)、`hybrid-1`(§0.12) | 不同任务、不同买主;与"压缩"共享不了数据与评测面 |
| 客户数据托管训练 | Endor 的 LoRA 平台(§0.3) | 与自托管定位相反,且直接踩"不使用客户 prompt"红线 |
| 免费层 / 定价 / GTM 叙事 | `llms.txt` 免费层(§0.15)、SEO 博客 | 基线已排除同类(GTM 叙事,无方法学信息) |
| 端到端推理服务 | `hybrid-1` 的 chat completions 端点 | 宿主已是网关,重复建设 |

---

## C. 对 Beam 下一版迭代的参考

以下每项给:**证据强度** / **成本档** / **冲突检查**。按建议优先级排序。

### C1. harness 加"结构化段落零改动率"观测(不改考卷)

- **证据强度**:第三方实机观测(不可复现但方向明确,§0.21)+ 官方"when not to
  use"清单(TTC 自家文档承认这一类)**两源同向** → 中高。
- **成本档**:**零成本** —— 纯 harness 改动 + 一次重跑(不需重训、不需新数据)。
- **冲突检查**:不冲突。golden 冻结纪律只禁"改题",加观测项不改题面;
  但仍须按冻结纪律走"扩充 + 重跑基线",不能悄悄改口径。
- **做法**:harness 侧在压缩前按模式识别结构化片段(JSON/代码块),记录其在
  0.1–0.5 全档下逐字不变的比例 —— **不修改已冻结的 golden 内容**(避免动哈希),
  识别规则与正则版本随报告落版本。这条同时是**差异点**的度量:
  TTC 把这件事交给调用方手工标 `<ttc_safe>`,而宿主已有 `_FACT_PATTERN` 强制保留。

### C2. 多轮场景加"已发出前缀逐字不变"断言(v2 的硬规则前置检验)

- **证据强度**:官方代码级事实(TTC 用 `cache_hits`/`cache_misses` 把这件事
  做成了接口语义,§0.6)+ 第三方独立复述(§0.21)+ 自家硬规则(decisions §5)
  → **高**。
- **成本档**:**零成本** —— harness 断言,不改模型、不改数据。
- **冲突检查**:与阶段 4 无冲突;它是 roadmap 阶段 4"接入面 spike 必须把
  '不破坏已缓存前缀'列为设计前提"的**可执行形式**。建议把它排在 v2 spike
  之前完成 —— spike 若被拒,这条断言仍是 research artifact 的一部分。

### C3. 扫档上沿从 0.5 扩到 0.7,报告以"曲线 + 拐点"呈现

- **证据强度**:三源同向(§G3:TTC finance 表 1 / TTC SQuAD 高档 / 自家 0.4 档
  CI 转负)→ **中高**。注意三处都不是同一模型同一语料,所以它是"存在拐点"的
  证据,不是"拐点在哪"的证据。
- **成本档**:**零成本到低成本**(纯推理 + judge 成本,已冻结 checkpoint,
  不改模型/数据);代价是报告篇幅与一次全量重跑。
- **冲突检查**:不冲突。`docs/evaluation.md` 明确"负结果先例存在,应预设
  压缩率-质量权衡曲线为标准产出",扩档正是该纪律的执行。

### C4. 把"宿主默认档位来源"写进对照报告与接入包

- **证据强度**:官方事实(厂商侧默认档 0.2/0.5 两说、档位映射三套并存,
  §0.9/§0.10)→ 中(作为**风险提示**,不是能力建议)。
- **成本档**:**零成本文档改动**。
- **冲突检查**:不冲突;decisions §6 要求对照报告标注 force-keep 的影响面,
  本条是其同类(报告须自证口径)。

### C5. v2 的 retention budget 语义:本轮新增一条先验

- **证据强度**:官方事实(finance 的 budget 定义域 **10%–90%,是保留比例**,
  与 aggressiveness 的删除阈值反向;§A 触发 1 附加收获)+ 拐点在 50% 附近 → 中。
- **成本档**:**需要新数据/新 schema**(v2 数据形态)。
- **冲突检查**:与 roadmap 阶段 4"评估 budget 作为第二参数语义候选"**一致**,
  本轮只是给它加了具体先验:budget 与 aggressiveness 是**反向参数化**,
  接入面 spike 时不要把它们当同一个旋钮的两种刻度。
- **注意**:bear.md 消费点 C.3 记的 `compression_ratio`(文档外模式)与
  finance 的 retention budget 是**两个不同的东西**(前者是 latency blog 的静态
  删除比例,后者是 query-aware 的保留率);本轮仍无法确认它们的字段名与关系。

### C6. 一句话校准:对手的迭代速度

- **证据强度**:官方事实 —— 压缩线 8 个月 4 版、bear-2-finance 仍在 private
  preview、Benchmarks 仓库 6 个月未动(`main` HEAD 2026-04-22);但 **SDK 之外
  另开了一条 7 天 14 版的产物线(Endor)** → **中**。
- **成本档**:**零成本**(只影响排期判断,不产出代码)。
- **冲突检查**:不冲突。对 Beam 的直接含义是"窗口期仍然成立":query-aware
  压缩至今**没有公开 API 面**(openapi 无字段、无 SDK 支持、无自助入口),
  v2 没有"落后一代"的既成事实。同时它提示:对手的工程速度在**托管平台**方向,
  不在压缩质量方向。

---

## D. 来源清单

抓取日期除注明外均为 2026-10-13。

### TTC 官网 / docs / blog
- [官方] [首页](https://thetokencompany.com/)(含 `Accept: text/markdown` 镜像)、
  [about](https://thetokencompany.com/about)、[pricing](https://thetokencompany.com/pricing)、
  [contact](https://thetokencompany.com/contact)、[blog 索引](https://thetokencompany.com/blog)
- [官方] [docs 索引](https://thetokencompany.com/docs)、
  [docs/compression](https://thetokencompany.com/docs/compression)、
  [docs/aggressiveness](https://thetokencompany.com/docs/aggressiveness)、
  [docs/protect-text](https://thetokencompany.com/docs/protect-text)、
  [docs/quickstart](https://thetokencompany.com/docs/quickstart)、
  [docs/openai](https://thetokencompany.com/docs/openai)、
  [docs/anthropic](https://thetokencompany.com/docs/anthropic)、
  [docs/openrouter](https://thetokencompany.com/docs/openrouter)、
  [docs/vercel-ai](https://thetokencompany.com/docs/vercel-ai)、
  [docs/hybrid](https://thetokencompany.com/docs/hybrid)、
  [docs/app-id](https://thetokencompany.com/docs/app-id)、
  [docs/stats](https://thetokencompany.com/docs/stats)、
  [docs/troubleshooting](https://thetokencompany.com/docs/troubleshooting)、
  [docs/data-retention](https://thetokencompany.com/docs/data-retention)
- [官方] [openapi.json](https://thetokencompany.com/openapi.json)(v2.2.0)、
  [agents.md](https://thetokencompany.com/agents.md)、
  [llms.txt](https://thetokencompany.com/llms.txt)、
  [llms-full.txt](https://thetokencompany.com/llms-full.txt)、
  [docs/llms.txt](https://thetokencompany.com/docs/llms.txt)、
  [sitemap.xml](https://thetokencompany.com/sitemap.xml)、
  [robots.txt](https://thetokencompany.com/robots.txt)
- [官方] blog:[compressing-sec-filings](https://thetokencompany.com/blog/compressing-sec-filings)、
  [coqa](https://thetokencompany.com/blog/coqa)、[latency](https://thetokencompany.com/blog/latency)、
  [cut-llm-api-costs](https://thetokencompany.com/blog/cut-llm-api-costs)(2026-05,GTM,
  本轮首次核对,无方法学内容)、
  [why-rag-token-costs-are-high](https://thetokencompany.com/blog/why-rag-token-costs-are-high)
  (同上)
- [官方] [status.thetokencompany.com](https://status.thetokencompany.com/);
  `app.thetokencompany.com` → 被 Cloudflare 挑战拦截(403),未能确认内容
- [官方→404] `/endor`、`/docs/endor`、`/system-one`、`/typesafe`、`/careers`、
  `/benchmarks.md`(均 404);`/benchmarks` 返回 200 但内容为品牌素材页(§0.17)

### TTC GitHub / 包仓库
- [官方代码] [TheTokenCompany/Benchmarks](https://github.com/TheTokenCompany/Benchmarks)
  (`main` HEAD `9271804…` @2026-04-22;`config.yaml`、`shared_config.py`、
  coqa/ squad_v2/ financebench/ longbench_v2/ latency/)
- [官方代码] [TheTokenCompany/endor-python](https://github.com/TheTokenCompany/endor-python)
  (创建 2026-10-06、push 2026-10-12;README 462 行、CHANGELOG 13 个版本)
- [官方代码] [the-token-company-python](https://github.com/TheTokenCompany/the-token-company-python)
  (末次 commit 2026-08-13;`_compress.py`、`_client.py`、`openai.py`、`_types.py`)
- [官方代码] [the-token-company-node](https://github.com/TheTokenCompany/the-token-company-node)
  (`src/client.ts`、`src/openai.ts`、`tests/assistant-default.test.ts`)
- [官方] [GitHub org repos API](https://api.github.com/orgs/TheTokenCompany/repos)(4 仓库时间戳)
- [官方] [PyPI the-token-company](https://pypi.org/pypi/the-token-company/json)(0.5.1 @2026-08-13)、
  [PyPI endor](https://pypi.org/pypi/endor/json)(0.0.1 @2026-10-06 → 0.6.0 @2026-10-12)、
  [npm the-token-company](https://registry.npmjs.org/the-token-company)(0.5.0 @2026-08-13)

### 第三方
- [第三方] [a-Fig/Accordion ADR-0024(bear2-hybrid-conductor)](https://github.com/a-Fig/Accordion/blob/main/docs/adr/0024-bear2-hybrid-conductor.md)
  (MIT,246 stars;实机 API 观测,日期 2026-06-20;脚本未公开)
- [第三方] [Kart-ing/ReCompress](https://github.com/Kart-ing/ReCompress)
  (MIT;Zenodo DOI 10.5281/zenodo.20787487;TTC 赞助黑客松最佳压缩模型奖)
- [第三方] GitHub 搜索:`opencode-ttc-plugin`、`ttc-compress-mcp`、
  `promptopskit`、`api-evangelist/providers`(集成为主,无复现评测)
- [第三方] [HN Algolia 搜索](https://hn.algolia.com/api/v1/search?query=thetokencompany)
  (全站仅 1 条提及,2026-06-05,为玩笑式评论,无评测内容)

### 本轮未取到
- Wayback CDX 查询(首页 + openapi.json)超时失败 → 无法做存档级 diff,
  本文"相对基线"的比较以 `docs/research/bear.md` 的记录为参照,而非存档字节对比。

---

## E. 未能确认项 + 下一次重抓触发

**未能确认(本轮硬约束内无解)**

1. **免费层是否真实存在**:`llms.txt` / `llms-full.txt` 说"1B tokens/月免费",
   `/pricing` 与 `/docs/quickstart` 说不存在(invite-only)。不注册无法验证。
   **这条直接关系到 bear.md"重议触发:第一方实测 bear API"的入口条件 ③
   (TTC 准入可得)—— 若免费层成立,该条件的满足成本从"商务接触"降为
   "自注册"。本轮不验证(硬约束),但值得在下次决策时点明。**
2. **bear-2-finance 的私有 API schema**:focus 是新字段、塞 input、还是独立端点;
   budget 的字段名、类型、响应是否带 span 坐标;计费口径。仍全部未知。
3. **每请求 token 上限与 429 配额数字**:413 只写 "the per-request token limit",
   429 无配额、无 Retry-After 数值;顶部 README 与 OpenAPI 均无数字。
4. **Endor 与 bear 的关系**:`decider-2b` 是否与 bear 同源、是否共享底座/数据;
   Endor 是否只是 TypeSafe 的白标。全部未知。
5. **`/benchmarks` 页的真实意图**(品牌素材页 vs 未上线页面)、
   `/careers` 404 但页脚有链接。
6. **第三方 Accordion 的实机脚本**不可得(私有桌面路径)→ 有数字不可复现。
7. **`app.thetokencompany.com`** 被 Cloudflare 拦截,无法确认自助开通是否已开放。
8. **`protect` 标注为 experimental 是否为本轮新增**(§0.14):只能确认"现在有",
   无法确认"上轮没有"。

**下一次重抓触发(满足任一即重查)**

1. `openapi.json` 版本号变化,或 `/v1/compress` 出现 query/task/focus/budget 类字段
   (bear-2-finance 转 GA);
2. 压缩线出现新模型(bear-3 或新变体),或 `bear-1.1` 从 `Benchmarks/config.yaml`
   消失(说明旧模型退役);
3. PyPI/npm `the-token-company` 出现 **0.6+**;
4. `TheTokenCompany/Benchmarks` 的 `main` 出现 2026-04-22 之后的新 commit;
5. **Endor 出现官网/文档面**(现在只有 PyPI + GitHub,官网全 404)—— 那意味着
   它从"开发者可见"转入"销售可见";
6. 第三方出现**带公开脚本**的 bear 复现评测(Accordion 的 `ttc-test` 脚本若公开
   即触发;同时满足 bear.md"独立第三方可复现实测"触发);
7. 免费层表述从 LLM 面进入 `/pricing` 或 `/docs/quickstart`(准入条件变化)。
