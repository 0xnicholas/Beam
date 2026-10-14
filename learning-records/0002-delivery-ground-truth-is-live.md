# 交付那一课的地基是活的：宿主接入面已经自己长出来了

2026-10-14 写第 04 课时复核宿主仓发现：`docs/delivery/refine-integration.md`（2026-09-11 侦察）列出的「宿主改造集四处」已经在宿主里落地了大半（2026-09-12 的 #213 一批：缓存键含压缩机身份、网关接出 token 计数与压缩机标签、`COMPRESSION_MODEL_ID` 评测缝），本仓交付文档里的行号随之漂移（`.bert` 调用 `refiner.py:263` → `338`、runbook 的「147 条」实为 **149 条**）。更关键的是：本仓 pilot checkpoint 已经通过那条评测缝在真实 sidecar 里加载并压缩过（`runs/20260913T110118217217Z-smoke149-pilot-plumbing-252d69d3/`，带 PLUMBING-ONLY 边界声明）。这不是「我们推着宿主改」，是宿主自己补的——但结论一样：接入面不再是瓶颈。

**Implications**：涉交付/接入的课文必须带日期、带「现状」一节，并且**先给符号、再给行号**——仓库里的交付文档本身会过期，符号（`model_label_for`、`record_refine_tokens`）才是稳的。下一次涉及宿主的课（v2 query-aware 接入面）不能假设宿主未变：先复核 `crates/gateway` 与 `sidecars/refine` 的 HEAD，再决定讲什么；第 04 课 §08 的现状表需要每次会话重新验证。另外，第 04 课确认了一个此前没写进课文的判断依据——**接入面能一票否决一个更好的模型**（XLM-R-large 因 `.roberta` 不是 drop-in），这条在讲 v2「为什么接入面最难」时要复用。
