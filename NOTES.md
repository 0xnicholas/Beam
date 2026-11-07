# 教学笔记（工作用）

## 用户偏好（2026-10-14 已确认受众）

- **受众是团队，不是用户本人**（原话：「为了帮助团队理解本项目」）。材料要能直接转给同事、能在评审里投影、能打印带走。默认每课自带背景，不假设读者读过其它课或进过仓库。
- 语言：中文。课文、参考文档、解释一律中文；代码与标识符保留英文。
- 决策方式：用户愿意把细节选择交给我（「你推荐」）——按推荐直接推进，方向性变化再确认；不要为「选哪个」停下。
- 请求形态是「写一篇……的原理」——要的是**可讲解的文章**，不只是对话里的结论。默认产出成体系的 HTML 课文。
- 仓库是用户的真实工作仓：原理类说法必须能回指到本仓或宿主仓的代码行；不接受无法复现的数字。
- 交互练习保留，但定位是「加深记忆」，不是通行门槛：不带交互读完也必须是完整的。

## 工作约定

- 教学文件放在仓库根目录：`lessons/`、`reference/`、`assets/`（含 `assets/data/` 与 `assets/repro/`）、`learning-records/`。这些不会被 `.gitignore` 忽略，会出现在 `git status` 里——是否提交由用户决定。
- 数字来源优先级：本机实测 > 冻结基线（`docs/baselines/`、`docs/evaluation.md`）> 论文 > 我的记忆。任何写进课文的数字都要能指出出处。
- 术语以 `reference/glossary.html` 为准；CONTEXT.md 的术语（验收尺、产物包、供货等）优先于自造词。
- 测验选项在中文里按**等字符数**对齐（英文按等词数），避免用长度泄露答案。写选项时用脚本数一遍。

## 本次会话的技术发现（不属于课程，属于项目）

**诊断：mBERT 的 fact recall 0.7699 主要来自解码空格，不是模型丢事实。**

- 证据 1：冻结基线里 mBERT 的 fact recall 在 0.1–0.5 五档恒为 0.7699（事实被正则钉死，阈值动不了它）；XLM-R 全档 1.0000。
- 证据 2：本机实测同一份代码路径，WordPiece 解码把 `#A-1029` 解成 `# A - 1029`、`12.5%` 解成 `12. 5 %`；SentencePiece（XLM-R）解码则原样保留。
- 证据 3：harness 的判据是字符串包含（`src/beam/runner.py:277` → `quality.py:43`）。
- 证据 4（定量）：149 条考卷里，逐条平均 22.79% 的事实带 ASCII 标点（会被解码空格拆开），与实测缺口 23.01%（1 − 0.7699）吻合。
- 待办：需要一次 harness 级复核（比对前做空白归一化 / 改按 token 存活率）才能定案，并决定这个口径问题要不要修、怎么修。适合做成 issue。
- 附带发现：XLM-R 在 0.1 档把 `driven` + `ly` 粘成 `drivenly`——「子序列保证」在字符串层不成立，token 层才成立。

**宿主接入面已自行落地，交付文档过期（2026-10-14 写第 04 课时复核）。**

- 宿主 HEAD `6b03be5`，工作树干净。`docs/delivery/refine-integration.md` 写于 2026-09-11 的「宿主改造集四处」，三处已由宿主自己实现：`dd2dd06`（`COMPRESSION_MODEL_ID` 评测缝）、`427140a`（缓存键含压缩机标签 + `refine_tokens_total`）、`e39126b`（指标标签 `model` → `compressor`）、`b338758`（门户展示节省）。网关 `RefineResult` 现已带 `original_tokens` / `refined_tokens` / `compressor_model`。
- **行号漂移**（本仓文档 vs 宿主现值）：`.bert` 调用 `refiner.py:263` → **338**；`make_cache_key` 调用点 `151–154` → **182–185**；`server.py` light mode `22-36` → **22-31**；runbook 的「147 条」实为 **149 条**（`eval/manifests/golden-freeze.json` 的 `item_count`）。
- **部署路径仍未变**：`MODEL_ID` 默认值还指公开 checkpoint；`COMPRESSION_MODEL_ID` 的代码注释明说「只在 beam 评测基线用，任何部署都不设」。所以「切换」仍是 `MODEL_ID` 默认值那一行。
- `sidecars/refine/models/` 目前是 HF hub cache（mBERT + XLM-R-large 两个 snapshot），**没有任何 `SHA256SUMS`**，也没有本地快照目录；本仓 `beam delivery pack` 从未针对交付跑过（全仓无 `integration-pack.md`）。
- **已修（2026-10-14，用户批准）**：`docs/delivery/refine-integration.md` 与 `docs/decisions.md` §6 已按宿主现状同步——行号、runbook 的 **149** 条、「宿主改造集」三处已落地、唯一待动的 3.1；`reference/delivery-contract.html` 与第 04 课随之更新。验证方式：改完用 `beam delivery pack` 对 `runs/train/pilot-v1/checkpoint` 真跑一遍（6 文件包、零残留占位符），跑完即删。
- **新发现（交付前必须处理）**：`delivery pack` 的 `MODEL_ID`/`MODEL_TAG` 取自 `config.json` 的 `_name_or_path`，缺该字段就退回**目录名**。训练导出（`src/beam/train.py`）不写这个字段，所以 pilot 产物渲染出的标签是 `checkpoint`，注入路径会变成 `models/checkpoint`。二选一：导出时写入 `_name_or_path`（推荐，身份随产物走），或交付前把暂存目录命名为 `beam-v1`。已写进接入包 §0 与交付速查 §4。
- 待办（由用户决定）：是否把上面这条落成 issue，并在 `train.py` 导出时补写 `_name_or_path`。

## 下一课候选（按团队提问频率排序）

1. 滑窗模糊匹配与对齐间隙：标签质量从哪来、在哪里坏（偏实现，适合接手代码的人）。
2. v2 query-aware：只加数据形态、不动架构，为什么接入面反而最难——**开讲前先复核宿主 HEAD**（学习记录 0002）。
3. 把 fact recall 0.7699 的诊断做成可复现实验（可以并进数据/口径主题，或做成附录）。

## 已完成

- 2026-10-14 四课齐：第 01 课（压缩原理 + 真实前向模拟器）、第 02 课（怎么读数字 + 配对 bootstrap 模拟器）、第 03 课（数据从哪来、红线在哪 + 真实蒸馏样本演示器）、第 04 课（交付与接入：产物包五件 + drop-in 契约四条 + 供货与回滚 + 契约体检台）。
- 参考：术语表（新增 D·交付与接入 一节，共 12 条）、管线速查、读表五问、**交付与接入速查**（新）；入口页 `lessons/index.html`（含分角色读法，已加「要接入、上线或评审交付」一行）。
- 组件库：`assets/lesson.css`（唯一样式表，新增 `.chk*` 契约检查面板样式）、`assets/quiz.js`（单选/多选/写后对照）、`assets/threshold-sim.js`、`assets/bootstrap-sim.js`、`assets/distill-demo.js`、**`assets/delivery-verify.js`**（契约体检台：五个开关 × 七项检查 × 三种判定，remedy 字串与 `src/beam/delivery.py` 逐字一致）；数据：`assets/data/trace-*.js`、`quality-deltas.js`、`distill-samples.js`（全部由真实产物生成，脚本化的重建路径见各文件头部注释）。
- 每课验证流程（沿用即可）：`node --check` 全部 JS → HTML 标签闭合检查 → 测验选项等长检查 → 内部链接可达检查 → 起本地静态服务用浏览器逐组件点一遍（file:// 下浏览器 MCP 无法打开，必须走 http）。
- 写作约定（第 04 课确立，后续涉宿主的课文沿用）：**先给符号、再给行号**——宿主会漂，符号（`model_label_for`、`record_refine_tokens`）不会；涉现状的段落必须带日期。
- 下一课建议：滑窗模糊匹配与对齐间隙（偏实现）；之后是 v2 query-aware（接入面），最后是 0.7699 诊断实验。
