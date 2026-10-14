# refine 接入包(骨架草案)

状态:**草案**(2026-09-11 建立于 grilling 会话;2026-10-14 复核宿主现状、同步
行号并重写 §3);阶段 5 交付前冻结为 v1 定稿。
对象:tokencamp-pro 的 refine sidecar(`sidecars/refine/`)与网关 transform 阶段。
事实基线:2026-10-14 对宿主仓 HEAD `6b03be5` 的复核(下文行号以此为准;
2026-09-11 侦察的旧行号在漂移处括注)。
决策依据:`docs/decisions.md` §6(含 2026-10-14 修订);阶段结构见
`docs/roadmap.md` 阶段 5。

本包是产物包第五件:让宿主**照做即可接入**的单元,不是说明文档。

本文件同时是**接入包草案**:`leia delivery pack` 从被校验的 checkpoint
目录渲染定稿(占位符 → 真实值,单一来源,零手工填入)。

> **复核结论(2026-10-14)**:原列"宿主改造集四处"中,**三处已由宿主自行落地**
> (缓存键含压缩机身份、token 节省指标、`COMPRESSION_MODEL_ID` 评测缝;提交
> `dd2dd06` / `427140a` / `e39126b` / `b338758`)。切换时**只剩一处需要动手**:
> 把 `compressor.py` 的 `MODEL_ID` 默认值指向本地产物。§3 已按此重写。

## 0. 本包对应产物(由 `delivery pack` 渲染)

- 模型标识(`config.json` 的 `_name_or_path`,缺省取目录名):`{{MODEL_ID}}`
- 模型标签(快照路径 / 指标标签用短名):`{{MODEL_TAG}}`
- checkpoint 目录内容摘要:`{{CHECKPOINT_DIGEST}}`
- 随附 `SHA256SUMS` 清单哈希:`{{SHA256SUMS_SHA256}}`
- checkpoint 文件数:{{CHECKPOINT_FILE_COUNT}}(逐文件哈希见随附 `SHA256SUMS`)
- 渲染 harness:leia {{HARNESS_VERSION}}

> **打包前必看:标签从哪来。**`{{MODEL_ID}}` 取 `config.json` 的
> `_name_or_path`,该字段缺失时退回**目录名**;`{{MODEL_TAG}}` 再取它的
> basename——也就是说,**暂存目录名会被直接写进 patch 与指标标签**。目录叫
> `checkpoint`,渲染出来的注入路径就是 `models/checkpoint`(错),宿主的
> `compressor` 标签也不可读。交付前把暂存目录命名为 `leia-v1`(或在导出时
> 写入 `_name_or_path`),再跑 `delivery pack`。2026-10-14 实测:
> `runs/train/pilot-v1/checkpoint` 正是缺该字段的情形,渲染出的标签是
> `checkpoint`。

## 1. drop-in 契约(产物校验清单)

一次切换是否可行,先看这份清单——任何一条不满足,都要求宿主改 `refiner.py`,
那就不再是"替换权重"而是"改造宿主"。

- [ ] `config.json` 的 `architectures` 含 `BertForTokenClassification`,
      `num_labels == 2`,`id2label` = {0: drop, 1: keep};
- [ ] tokenizer 为 **fast**(`return_offsets_mapping=True` 必须可用——
      force-keep 靠 offsets 定位);
- [ ] 模型类暴露 **`.bert`** 属性(`refiner.py:338` 的相似度 Guardrail 直接调
      `self.compressor.model.bert(**inputs)`;2026-09-11 侦察时为 263);
- [ ] 与现网同架构基底(mBERT-base 系列)→ 延迟档案与内存占用可直接对比;
- [ ] 随附对照报告与延迟档案(阶段 5 产物包其余各件)。

交付前在本仓跑一遍(离线、零网络,即本命令族的本体):

```bash
uv run leia delivery verify <checkpoint dir>          # 静态层(默认依赖)
uv run leia delivery verify <checkpoint dir> \
  --report verify.json                                   # + 机读报告落盘
uv sync --group load                                     # 可选:加载层重依赖
uv run leia delivery verify <checkpoint dir>          # 含真实例化断言
```

静态层验架构类、标签语义与 tokenizer 资产;加载层(可选依赖组在场时)
真实例化模型,断言 `.bert` 与运行时 offsets——即下述手工脚本的等价物:

```bash
uv run python - <<'PY'
from transformers import AutoTokenizer, AutoModelForTokenClassification
p = "<checkpoint dir>"
tok = AutoTokenizer.from_pretrained(p)
m = AutoModelForTokenClassification.from_pretrained(p)
assert m.config.num_labels == 2, m.config.num_labels
assert hasattr(m, "bert"), "guardrail needs .bert (XLM-R would fail here)"
assert tok.is_fast and tok("x", return_offsets_mapping=True)["offset_mapping"]
print("drop-in OK:", m.config.architectures)
PY
```

> 已知反例:XLM-R-large 的类属性是 `.roberta`,**不是** drop-in。后手牌激活
> 判据已据此修订(roadmap 阶段 1)。

## 2. 交付物与传输

传输走私有 HF 仓,落盘为**本地快照**——运行时不再依赖 HF 可达性与凭据。

```
sidecars/refine/models/{{MODEL_TAG}}/
  config.json  model.safetensors  vocab.txt  tokenizer_config.json  ...
  SHA256SUMS                       # 逐文件校验清单
sidecars/refine/models/models--microsoft--llmlingua-2-...   # 旧快照，原地保留
```

```bash
huggingface-cli download <org>/{{MODEL_TAG}} --revision <sha> \
  --local-dir sidecars/refine/models/{{MODEL_TAG}}
(cd sidecars/refine/models/{{MODEL_TAG}} && shasum -a 256 -c SHA256SUMS)
```

旧快照目录**不删**:它就是回滚素材(见 §4 第 10 步)。

> 2026-10-14 实况:`sidecars/refine/models/` 当前是 HF hub cache(mBERT +
> XLM-R-large 两个 snapshot),尚无本地快照目录,也没有 `SHA256SUMS`。

## 3. 宿主改动 patch 草案

**2026-10-14 复核结论:四处里三处已在宿主里(3.2-3.4),切换时只需打 3.1
这一处**;其余文件一行不动。

### 3.1 `sidecars/refine/compressor.py` —— 唯一需要动手的一处

宿主现状(`compressor.py:16-19`)已把 `MODEL_ID` 拆成"环境变量 + 默认值",
默认值仍指向公开 checkpoint:

```python
MODEL_ID = os.environ.get(
    "COMPRESSION_MODEL_ID",
    "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
)
```

`COMPRESSION_MODEL_ID` 是**评测缝**,不是部署路径——宿主代码注释写明它"只为
leia 的评测基线(issue #9 双 checkpoint 扫描)而存在、在任何部署里都不设"。
所以**部署切换 = 改默认值那一行**,保持"版本单一来源、可审计"(decisions.md
§6 的排除项不变):

```diff
 MODEL_ID = os.environ.get(
     "COMPRESSION_MODEL_ID",
-    "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
+    # Leia v1 — local snapshot, sha256-verified (SHA256SUMS)
+    os.path.join(os.path.dirname(__file__), "models", "{{MODEL_TAG}}"),
 )
```

注:

- `os.path.dirname(__file__)` 给出**绝对路径**——`model_label_for` 的 docstring
  明确要求部署指向绝对路径(相对路径按进程 CWD 解析);
- 本地路径下 `from_pretrained` 忽略 `cache_dir`,无副作用;启动加载完全离线;
- 身份标签由 `model_label_for`(`compressor.py:33-43`)从路径末端取,自动等于
  `{{MODEL_TAG}}`——与加载路径同源,不会手工漂移;
- 失败语义不变——`server.py:22-31`(旧记 22-36)仍会落到 light mode
  (`compressor=None`,继续服务 rewrite)。

**不需要**的改动:`Compressor.__init__` 已接 `model_id` 参数并已设
`self.model_label`(`compressor.py:47-49`);原草案里那两行 patch 已无必要。

### 3.2 `sidecars/refine/refine_cache.py` —— 宿主已做,核对即可

原风险(键里不含压缩机 → 换权重后旧结果**静默继续命中**)已关闭:
`make_cache_key` 的第九个参数就是压缩机标签。

**切换时要做的**:零改动。核对三处即可——参数(`refine_cache.py:21`)、键分量
(`refine_cache.py:42`)、调用点实参 `self.compressor_model`
(`refiner.py:182-185`,旧记 151-154;该属性在 `refiner.py:141-146`,light mode
下为 `"none"`)。它同时是"回滚不残留脏缓存"的机制来源。

### 3.3 网关 `crates/gateway/src/refine.rs` —— 宿主已做,核对即可

token 计数与压缩机标签已贯通,且字段落在**每个结果**上而非响应信封:
`RefineResult`(`refine.rs:200-216`)带 `refined_text` / `fallback` /
`original_tokens` / `refined_tokens` / `compressor_model` / `warnings`;
信封 `RefineResponse`(`refine.rs:228-233`)只含 `results`。

**切换时要做的**:零改动。

### 3.4 `crates/gateway/src/metrics.rs` + `pipeline/transform.rs` —— 宿主已做(按原推荐 B)

原推荐的 (B)(标签由 sidecar 单一来源供给)已落地;实现签名与原草案不同——
按"一对计数"记录,标签名是 `compressor` 而非 `model`(宿主 CONTEXT.md 把裸
`model` 保留给 catalog 模型):

```rust
pub fn record_refine_tokens(compressor: &str, original_tokens: u64, refined_tokens: u64) {
    for (direction, tokens) in [("original", original_tokens), ("refined", refined_tokens)] {
        metrics::counter!(
            REFINE_TOKENS_TOTAL,
            "direction" => direction.to_owned(),
            "compressor" => compressor.to_owned()
        )
        .increment(tokens);
    }
}
```

(`metrics.rs:112-121`;调用点 `transform.rs:220-224`,旧记 85-103。)

**切换时要做的**:零改动。观察阶段读
`refine_tokens_total{direction=original|refined, compressor=<标签>}`——**新旧
权重的前后对比是现成的**,`compressor` 标签值即 `{{MODEL_TAG}}`。

隐私:只记计数,不记 prompt 内容——与宿主既有边界一致。

## 4. 切换 runbook

1. 落盘快照并跑 §2 的 sha256 校验(`leia delivery verify <快照目录>`
   同步跑契约校验);
2. 打 §3.1 的**一处** patch(3.2-3.4 只核对,不改);
3. 冷启动 sidecar(uvicorn);
4. `GET /health` → `{"status":"ok","compressor":true}`(false = light mode,停);
5. stub 冒烟:本仓 `uv run leia eval run --config eval/configs/fixture.toml`
   (零网络零花费);
6. 真链路回归:本仓 pinned harness 跑冻结评测包全量(**149 条** ≈ 600 次网关
   调用),走宿主网关的账本;
7. 对照冻结基线核判据:质量 delta 95% CI 下界 ≥ 0 且压缩率或 fact recall 有
   一项显著提升——**持平即停,不切换**;
8. 切换(改 `MODEL_ID` 默认值 + 重启);
9. 观察:applied/fallback/skipped 计数 + token 节省指标
   (`refine_tokens_total` 按 `compressor` 标签分组);
10. 异常回滚:`git revert` + 重启;旧快照仍在原地,缓存键已变,老条目自然
    失效——回滚不残留脏缓存。

## 5. 非差异清单(切换后**不变**的东西)

- `/refine` 与 `/compress` 协议、请求/响应字段语义;
- `x-tc-refine*` 头与 `refine_mode` / `refine_tier` / aggressiveness 语义;
- rewrite 阶段(LLM 经网关回调)与 `x-tc-refine: false` 递归防护;
- fail-open 与 light mode(宿主 ADR-0011)及 `x-tc-refine: skipped` 标记;
- 三项 guardrail 与 `_FACT_PATTERN` force-keep;
- 缓存 LRU/TTL 行为、超时(`REFINE_TIMEOUT_MS`)、隐私边界(sidecar 只见
  prompt 文本)。

## 6. 回归与再交付触发器

回归纪律:stub 模式进宿主 CI(零成本);**影响压缩面/权重的改动**必须跑真链路
全量(Leia 侧执行,结果摘录入 `docs/baselines/`)。

再交付(Leia → refine)触发器,无触发不交付:

1. 真链路回归跌破验收线;
2. 负载分布漂移——操作化为 golden 主动扩集 + 线上聚合指标(节省率/
   fallback/延迟)漂移告警;**均为代理信号,不声称测质量**(客户 prompt 不可
   用于评测,硬约束 2);
3. 训练语料许可变化;
4. v2 作为独立能力线立项。

## 7. 断供说明

产物自包含:本地快照 + 旧模型并存,`from_pretrained(local_path)` 离线可跑。
**Leia 项目停止不影响 refine 运行与回滚**——这是"交付物供货"优于"代码
依赖"的地方。

## 8. 待现场确认(本仓侦察无法确定)

- 生产宿主是否有仓外的容器/编排 → **2026-10-14 复核:宿主仓内仍无 Dockerfile
  / compose / k8s(仅 CI 里的 postgres service,以及一个被 gitignore 的上游
  副本),部署形态是裸机**(`scripts/dev.sh` + `docs/deployment-smoke.md`);
- `sidecars/refine/models/` 在目标环境是否持久(裸机进程重启后仍在);
- 是否存在会带上 sidecar 的自托管客户包(SaaS-only 判断来自宿主 ADR-0017,
  但环上没有直接证据)。
