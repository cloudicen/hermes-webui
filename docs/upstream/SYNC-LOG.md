# SYNC-LOG —— 上游同步决策记录

本文件记录本仓库每一次上游同步动作：采纳了什么、拒绝了什么、为什么。
**entry 由每次合入动作（[UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) 模式 A / 模式 B）
执行完成后追加；拒绝同样必须记录**——没有拒绝记录的同步视为未完成。
编号从 `#0` 起，`#0` 是独立线基线（fork-point 建立、尚未同步任何上游内容），
由基线流程写入；此后的每一次同步递增一条。

## Entry 格式（模板）

每条 entry 使用以下字段，顺序与命名不可省略；无内容的清单写 `(none)`：

```markdown
## Entry #N —— YYYY-MM-DD

- 日期: YYYY-MM-DD
- digest 文件: digest-YYYYMMDD-HHMM.md（本轮决策的信息来源；模式 A 逐条 pick 时可写多份）
- 上游范围: <last-sha>..<new-sha>（本轮审视的 upstream/master 区间）
- 模式: A（cherry-pick）/ B（批量 merge + 剔除）/ 无（仅审视，未动作）
- 采纳清单:
  - <upstream-sha> —— 一句话说明（做了什么、为什么收）
  - ...
- 拒绝清单:
  - <upstream-sha> —— 拒绝理由（冲突点、方向不符、暂缓待观察等）
  - ...
- 冲突与偏离记录: 冲突解决是否偏离上游语义、rerere 复用情况；无则 (none)
- 测试证据: ./scripts/test.sh 结果摘要（通过数/失败数，或注明豁免理由）
- 结果 commit sha: 本地 master 上的落点（cherry-pick 的 merge 后 sha /
  模式 B 的 --no-ff merge commit sha）
```

字段细则：

- **sha 一律用上游短 sha**（`git log --format=%h upstream/master` 可直接引用），
  模式 A 的溯源同时由 `-x` trailer 写在 commit 体内，本清单是索引层。
- **拒绝清单与采纳清单同权重**：前者避免未来重复评估，后者支撑 license 溯源
  （MIT 义务随采纳产生，见 [UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) ①⑨）。
- 连带触及 `docs/CONTRACTS.md` / RFC 的上游提交，在"冲突与偏离记录"里点名
  涉及的契约文档（UPSTREAM-SYNC.md ⑤）。
- 一条 entry 对应一次同步动作；跨天决策（先看后收）拆成两条：先"模式: 无"，
  后正式采纳。

<!-- Entry #0（基线）由基线流程按上述模板写入：fork-point tag 名与 sha、
     自有提交数、上游领先数、机制文件清单，采纳/拒绝清单均为 (none)。 -->
