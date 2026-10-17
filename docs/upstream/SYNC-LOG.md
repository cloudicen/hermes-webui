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

## Entry #0 —— 2026-10-18

- 日期: 2026-10-18
- digest 文件: digest-20261018-0351.md（基线 digest，生成于 `.omo/upstream-watch/`，
  该目录不入 git，本地查阅）
- 上游范围: fd681377310b4590acfd7b69d255b3e75f6e47bb..77c8fc1745734262c88324e5d4b545a13953baa5
- 模式: 无（基线建立，非同步动作）
- 采纳清单: (none)
- 拒绝清单: (none)
- 冲突与偏离记录: (none)
- 基线事实（建立 fork-point tag 时记录）：
  - fork-point tag: `fork-point-2026-10-15`（annotated tag，peel 到提交 sha
    fd681377310b4590acfd7b69d255b3e75f6e47bb，即本线与 upstream/master 的 merge-base）
  - 自有提交数（fork-point..master）: 25
  - 上游领先数（master..upstream/master）: 421（与基线 digest 头部计数一致）
- 声明: 本仓库自此以独立线开始，**尚未同步任何上游内容**；此后每一次同步动作
  按 [UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) 执行并在本文件递增一条 entry。
- 机制文件清单（本轮落地的全部机制文件，均已入库）：
  - scripts/upstream-watch.sh（digest 生成器）
  - scripts/systemd/upstream-watch.service、scripts/systemd/upstream-watch.timer
    （systemd user timer，定时刷新 digest）
  - docs/upstream/UPSTREAM-SYNC.md（选择性同步手册）、docs/upstream/SYNC-LOG.md（本文件）、
    docs/upstream/LICENSING.md（license 合规细则）、docs/upstream/CONTRIBUTING-BACK.md（反哺上游指南）
  - NOTICE（仓库根，溯源清单骨架）、LICENSE（含 fork 版权行）
- 测试证据: 随本 entry 的单次推送触发 pre-push 全量门禁（scripts/ci/pre-push，
  sharded pytest ~11.5k tests），结果见 .omo/evidence/task-7-upstream-sync.log
- 结果 commit sha: （本 entry 即基线提交：`git log -1 -- docs/upstream/SYNC-LOG.md`）
