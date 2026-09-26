# 蒸馏定容决策(2026-09-26,issue #20)

依据:issue #20(parent #15)的全量蒸馏授权;#18 pilot 实测
(`training/distill/pilot-v1/`);`docs/training-mix.md` 的配比锚点;
花费门状态 = 阶段 1 基线数字已产出(`2026-09-12-stage1-exit.md`)。
本文件类比阶段 1 的 `2026-08-31-pilot30-sizing-decision.md` 先例:
先决策归档,后花钱。

## 决策一览

| 变量 | 决定 | 理由要点 |
|---|---|---|
| 总量 | 冻结语料 v1 **全集**:1000 条目 → 7322 chunks(≤512 token,cl100k_base,本地确定性分块实测);其中 65 个 token-empty chunk(纯标点/空白残片,零可标注词)跳过不计费 → **实际压缩 7257** | 见下 |
| 配比 | **条目层 30.0/35.0/35.0**(rag/system_prompt/dialogue,语料冻结时已达锚点);行层(chunk 层)如实记录自然倾斜,冻结集保留全部 QC 通过行 | 见下 |
| teacher | `deepseek/deepseek-v4-pro`(与 pilot 同钉),prompt `llmlingua2-paper-v1`(sha256 `84581c12…`)不变 | 见下 |
| 预算 | ≤7257 次网关调用(其中 299 次 pilot 重放零费,新计费 ≤6958);墙钟 ≈5.8h;账本归因 ledger `4fa4734ddd57fcec` | 见下 |
| 质控口径 | VR top 5% → AG top 10%(论文默认,pilot 同钉;阈值随总体自适应,落进 manifest) | 与 pilot 可比 |

## 总量:全量,无选择

- 语料两层均已在 #16/#17 冻结(1000 条目:hotpotqa 150 + gov_report 150
  + system_prompt 350 + dialogue 350),条目数本身就是 #16/#17 定容的
  产物;本决策的"总量"变量是**蒸馏覆盖率**,取 100%。
- 预算机制从"条目选择"退化为恒等式:chunk budgets = 各类 chunk 总数
  (rag=6167, system_prompt=350, dialogue=805),脚本运行时从冻结字节
  重算并断言 100% 条目入选——gov_report 的长条目(pilot 因预算限制未
  入选,已在其 manifest 注记)本次全部进入。
- **token-empty 跳过**(2026-09-26 stub 全量冒烟发现):分块边界打包的
  残片(如孤立的 `", "`)无词可标、指标 0/0 无定义——蒸馏管线在任务
  构造处跳过并计数(`counts.token_empty_chunks_skipped`),其余 chunk
  的索引与 journal 键逐字节不变(内容寻址完整性不受影响)。跳过量为
  65(hotpotqa 26 + gov_report 39),全部为标点/空白残片。
- 不测子集的理由:pilot(#18)已在 115 条目 / 299 chunks 上证明管线与
  账本归因;阶段 3 止损为"最多 3 次验收尝试",每次尝试的数据版本锚必须
  是全量冻结集——蒸馏只跑一次、冻结一次,迭代变量留给训练侧。

## 配比:条目层守锚点,行层如实记录

- **条目层 30/35/35 不动摇**:`docs/training-mix.md` 的锚点在语料冻结时
  已达成(30.0/35.0/35.0,容差 ±5pt 内),且语料字节已冻结——本决策不
  重建语料。
- **行层(chunk 层)倾斜是长文的固有后果**:rag 条目均 20.6 chunks/条,
  system_prompt 1.0、dialogue 2.3;全量蒸馏后行层约为
  rag 84% / system_prompt 5% / dialogue 11%(QC 前口径)。
- **决策:冻结集 = 全部 QC 通过行,不做行层下采样**。理由:
  1. 行层下采样到 30/35/35 需丢弃 ~86% 已付费且 QC 合格的 rag 监督
     信号——花钱买数据再扔掉,且只保留每文档头部/stride 片段会引入
     新的位置偏差;
  2. 条目层配比已控制**分布覆盖**(决策意图所在:两类缺口各 350 条目
     入集);行层差异只影响梯度质量分配,其效应未知、应由数据回答;
  3. 阶段 3 止损纪律要求"每轮迭代前写下这轮赌什么"——行层配比正是
     可迭代的假设变量;若尝试间做行层再平衡,衍生文件的 sha256 与采样
     规则进该次 run record,冻结池仍是版本锚(冻结 manifest 预留此
     语义的明文)。
- 对冲记录:合成占比行层仅 ~16%,training-mix.md 的"合成封顶 2/3 防
  模板过拟"在行层自动满足;反向风险(rag 梯度淹没缺口类)列为阶段 3
  首次尝试的观察项,由分负载验收数据裁决。

## teacher:与 pilot 同钉,不换

- `deepseek/deepseek-v4-pro` 经 tokencamp 自有网关(成本进内部账本,
  data-strategy.md 蒸馏管线节);2026-09-26 网关探针确认 served 口径
  仍为 `deepseek/deepseek-v4-pro`(单调用验证,2e-6 账本单位)。
- 同钉的直接收益:账本 id 由 语料字节 + teacher + prompt + 分块参数
  内容寻址,全量与 pilot 同账(ledger `4fa4734ddd57fcec`),pilot 已
  计费的 299 chunks 在全量跑中**零成本重放**。
- 不换型的理由:pilot↔全量质控口径可比(同一 teacher 分布);无任何
  证据指向需要更强的 teacher;换型 = 新账本 + pilot 花费沉没。

## 预算

| 项 | 量 | 口径 |
|---|---|---|
| 网关调用 | ≤7257(新计费 ≤6958,299 重放) | 每 chunk 一次;journal 逐条归因 |
| 输入 token | 3,077,323(chunk 本体,实测)+ 模板 ~160/次 ≈ **4.2M** | cl100k_base 计费口径 |
| 输出 token | 估 ~2.2M | pilot 实测 mean word_compressed_rate 0.7319 外推 |
| 账本成本 | 探针 2e-6/103 tokens → 全量 ≈ **0.13 账本单位**(上限按 7257 次全费估 ≤0.2) | 网关 usage.cost 字段口径 |
| 墙钟 | ≈5.8h(20 calls/min:3s pacing × 4 workers) | 低于 2026-09-12 实测 ~35/min 跳闸点,pilot 同 posture |
| 中断容忍 | kill/崩溃重跑只补未记录 chunk,零重复计费;瞬时重试双计容忍 +5% calls | journal 内容寻址(#18 已证) |

超支处置:实际 calls 超 7257×1.05 或 served model 漂移 → 中止并回 issue
重新定容,不静默追加。

## 已知局限(解读时记住)

- 行层 rag 主导(上节)是阶段 3 首次尝试的显式观察项,不是疏漏;
- teacher 输出分布漂移不可控(网关后端版本):served_models 逐 chunk 进
  journal、汇总进 manifest,漂移即可见;
- 6h 窗口内网关可用性风险由 journal 吸收(断点恢复为零成本重放),唯一
  不可吸收的是 in-flight ≤4 次调用的服务端已计费未记录(口径与 #18 一致,
  已在 pilot 运行履历中同类注记)。
