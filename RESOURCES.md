# Beam 压缩原理 Resources

## Knowledge

- [论文: LLMLingua-2: Data Distillation for Efficient and Faithful Task-Agnostic Prompt Compression (ACL 2024 Findings)](https://arxiv.org/abs/2403.12968)
  一手出处。§3 是数据蒸馏管线（3.1 生成 / 3.2 训练 / 3.3 质控），也是「把压缩形式化为 token 分类」的论证来源。用途：任何机制性说法的最终依据；教师 prompt 取舍、超参数、跨域泛化的原始数字都在这里。
- [模型卡: microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank](https://huggingface.co/microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank)
  现网基底 checkpoint（Apache-2.0）。用途：训练集与许可、官方 API 用法；注意其训练数据是 MeetingBank，本项目的评测必须排除该语料。
- [数据集: microsoft/MeetingBank-LLMCompressed](https://huggingface.co/datasets/microsoft/MeetingBank-LLMCompressed)
  论文释出的压缩标注数据集。用途：理解标签长什么样（逐词的 keep/drop）；本项目不得用它训练或评测。
- [仓库: microsoft/LLMLingua](https://github.com/microsoft/LLMLingua)
  官方实现。用途：对照本仓实现的语义差异（阈值取法、force_keep、drop_consecutive 等）；issue 区有作者对边界的解释。
- [本仓: `docs/decisions.md`](decisions.md)
  决策与排除项。用途：任何「为什么不那样做」的问题先查这里（生成式压缩、从零训练、env 覆盖版本号等）。
- [本仓: `docs/evaluation.md`](evaluation.md)
  验收尺：指标口径、冻结考卷、双 checkpoint 基线数字。用途：一切「好多少」的问题。
- [本仓: `docs/data-strategy.md`](data-strategy.md)
  蒸馏管线与语料红线（MeetingBank 排除、客户 prompt 排除、train/eval 切分）。
- [本仓: `src/beam/distill.py`](../src/beam/distill.py)
  蒸馏管线的本地实现（分块、滑窗匹配、VR/AG 质控）。用途：论文没写清的启发式细节，以这里为准。
- [宿主: `tokencamp-pro/sidecars/refine/compressor.py`](../../tokencamp-pro/sidecars/refine/compressor.py)
  生产运行时实现——本项目的原理最终以它为准。用途：任何「线上到底怎么走」的问题。
- [宿主: `tokencamp-pro/sidecars/refine/refiner.py`](../../tokencamp-pro/sidecars/refine/refiner.py)
  rewrite 阶段与双 guardrail（相似度 F0.5、事实召回）以及 `_FACT_PATTERN` 的定义处。
- [竞品研究: `docs/research/bear.md`](research/bear.md)
  The Token Company bear 系列的深挖（同技术族的公开证据与口径分析）。

## Wisdom (Communities)

- [microsoft/LLMLingua 的 Issues](https://github.com/microsoft/LLMLingua/issues)
  作者会回机制性问题（阈值语义、force_keep、多语言表现）。用途：把「我读到的是这样」变成「作者确认是这样」。
- [HF 模型卡 Discussions 页](https://huggingface.co/microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank/discussions)
  部署者踩坑记录（语言覆盖、长文分块、延迟）。用途：真实负载与论文设定的差距。
- [r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA/)
  关于 prompt compression 实践的高流量讨论区。用途：不同压缩方案的横向经验；信噪比波动大，需自带判据。
- 本仓 GitHub Issues（0xnicholas/beam）
  自己的问题追踪与验收记录。用途：把诊断结论落成可复核的 issue，而不是留在对话里。

## Gaps

- **中文负载上的独立复现材料基本没有**：LLMLingua-2 的公开数字以英文为主，中文场景只有零散经验贴。本仓的 149 条考卷是目前手上唯一可信的中文口径——这也意味着「我们的数字对不对」没有外部参照，只能靠内部一致性（口径注记）判断。
- **阈值—压缩率的映射没有公开研究**：官方实现与本仓都用「绝对概率阈值」，但没人公开发过校准曲线。第一课的实测是这个方向的第一份本地证据。
- **社区偏好未确认**：用户尚未表达是否愿意进社区提问。

## 社区偏好记录

- 待确认（2026-10-14）：是否需要外部社区；如不需要，后续课程不再主动推荐。
