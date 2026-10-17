# 上游选择性同步手册（upstream → master 人工决策合并）

本文约定本仓库如何跟进上游 `nesquena/hermes-webui` 的每日变化。
规则一句话：**上游内容只在人工显式决策下进入本仓库；机制负责发现和呈现，
不负责合入。** 每次采纳或拒绝都必须记入
[`SYNC-LOG.md`](SYNC-LOG.md)。命令与术语保留英文；文义冲突时以
AGENTS.md / CONTRIBUTING.md 英文原文为准。

---

## ① 心智模型

| 对象 | 角色 | 事实 |
|---|---|---|
| `master` | 本仓库的**独立产品线** | 自有功能在这里演进；origin 是它的公开 fork 远端 |
| `upstream/master` | **fetch-only 镜像 ref** | remote push 已禁用（`git remote -v` 里显示 `upstream no-push`），只能读，不能写 |
| fork-point 标注 tag | 分叉锚点 | 名称内嵌实际分叉日期（形如 `fork-point-YYYY-MM-DD`，由维护者创建）。**任何时候用 `git tag -l 'fork-point-*'` 查询，不要硬编码日期** |
| rerere | 已启用 | `git config rerere.enabled` = true：解决过的冲突会被记住，后续同步同一片区域时自动复用解法 |

推论：本线的新提交**不是** upstream/master 的后代，任何假设线性关系的工具
（`git pull`、应用内更新器）都不能把我们带上上游最新状态——这是设计使然，
同步只走本手册的 ③/④ 两种模式。

上游实况（用于校准预期，非硬性数字）：每日约 50-60 个 commit、曾单日发 8 个
exp release；合入走 stage 分支 → RM fold 多轮评审 → 自动打 tag 的流水线。
逐条评估不现实，所以先读 digest（②），再挑选，不要试图全量精读。

## ② 每日 digest 怎么读

定时任务每天生成一份 digest（`.omo/upstream-watch/digest-YYYYMMDD-HHMM.md`），
并且：

- **`.omo/upstream-watch/digest-latest.md` 恒指向最新一份**（稳定指针），
  读上游动态只看这一份；历史 digest 按日期名回溯。
- 内容三段：
  1. **New release tags** —— 上游发了哪些版本；
  2. **CHANGELOG 增量** —— 上游人工维护的 changelog 差异，这是**特性信号**，
     决定"值不值得看"以此段为主；
  3. **Commits** —— `--no-merges` 的单行列表，是**细节层**，用于确认某个特性
     由哪些 commit 组成、拿到 ③/④ 要用的 sha。
- 状态文件记录的 last-seen 是"上次生成 digest 时的 upstream HEAD"，与是否
  已合入无关：每个上游 commit 恰好出现在一份 digest 里，漏读不会发生。

## ③ 模式 A：cherry-pick（单特性精确摘取，默认模式）

适合：只想要一个 bugfix / 一个独立特性 / 一组小 commit。

```bash
git fetch upstream --tags          # digest 脚本已做；手工确认时用这条
git cherry-pick -x <sha>           # -x 自动附 "cherry picked from" 溯源 trailer
```

- **多 commit 特性按上游顺序逐个 pick**（旧→新），不要乱序、不要 squash 后 pick。
- 冲突处理原则：**保持上游语义优先**。任何对上游原意的偏离（包括"顺手改成
  我们的写法"），必须写入 [`SYNC-LOG.md`](SYNC-LOG.md) 并附理由。
- 完成后跑全量门禁：`./scripts/test.sh`。
- 涉及 UI 的改动：按 AGENTS.local.md 的规则启动 dev-server（
  `scripts/dev-server.sh`）目检后再算完成。
- rerere 命中时**别直接信任**：解法是历史同场景的复用，仍要人工过目再继续。

## ④ 模式 B：批量 merge + 剔除（大范围同步）

适合：攒了一段区间、上游量大且大部分可接受。全程在临时 `sync/` 分支上操作，
master 只在最后一步动：

```bash
git checkout -b sync/$(date +%Y%m%d) master
git merge upstream/master                    # 冲突在这里解决（rerere 会辅助）
# 对不想要的特性：git revert <sha>（或 git checkout master -- <路径> 恢复自有文件）
./scripts/test.sh                            # 在 sync/ 分支上跑全量
git checkout master
git merge --no-ff sync/<日期分支> \
  -m "Merge upstream range <old>..<new> (see SYNC-LOG)"
git branch -d sync/<日期分支>                # 清理临时分支
```

- `--no-ff` 的 merge commit 把整个区间打包为一个可整体回退的节点；
  范围写进 message 并对应 SYNC-LOG 的一条 entry。
- revert 掉的特性同样要进 SYNC-LOG 的拒绝清单（含 sha），否则历史说不清。

## ⑤ 通用规则（模式 A / B 都适用）

**上游提交可能连带 `docs/CONTRACTS.md` 与 RFC 文档的变化**（contract-affecting
change 在上游 PR 规范里要求显式 `Contract Routing`，见
[`docs/CONTRACTS.md`](../CONTRACTS.md) 的 Contract Routing 节与
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) 的 Contract-affecting PRs 节）。
这类文档变化**随代码合入原样带入**，不要单方面"本地化改写"；同时在
SYNC-LOG 记录该 entry 连带触及了哪些契约文档，方便后续按
CONTRIBUTING.md 的 `Contract Routing`/`Contract Change` 格式做本线说明。

## ⑥ 决策准则

| 类别 | 倾向 | 备注 |
|---|---|---|
| bugfix / perf / a11y | **优先采纳** | 回归风险低、收益直接 |
| 新特性 | 逐条评估是否与自有方向冲突 | **已知雷区：custom-provider 区域**——上游 #8256 活跃于此，与本线自有的 provider write path 同区，首次同步该区域预计有真实冲突，pick 前先读两边的实现 |
| i18n（locale 补全） | 按需 | 不影响行为的翻译可批量跟，也可整体跳过 |

拒绝不是错误，但**必须记录**（[`SYNC-LOG.md`](SYNC-LOG.md) 拒绝清单），
避免下次面对同一 commit 重新做一遍判断。

## ⑦ 应用内更新器（in-app updater）说明

WebUI 设置页自带更新检查（`api/updates.py`），它服务的是"跟着 origin 跑的上游
用户"，**对本独立线基本无用甚至有误导**：

- 它只 `git fetch origin`（updates.py:298 只识别 `fetch origin` 命令族；
  1305/1535/2402 全是 `fetch origin`），永远不读 `upstream` remote。
  也就是说它眼里"最新"只等于我们 fork 远端的历史，而我们的远端**故意**不
  自动跟随上游。
- 更新应用走 `git pull --ff-only`（updates.py:1097-1102）；本线与上游分叉后
  上游不再是 HEAD 的后代，ff-only 天然不可达。
- 频道路径：stable 频道下 WebUI 仓库比较的是发布 tag 家族，HEAD 已包含
  latest stable tag 时直接自报"已是最新"、不回退追分支
  （updates.py:1105-1166）。独立线大多落在这个自报最新的路径上。
- 设置页"**落后 N 版**"横幅对比的是 **nesquena 仓库的 release tags**
  （硬编码 GitHub API 源，updates.py:83-87），对本独立线而言是**噪音**：
  它数的是上游 tag，不代表我们"缺了什么"，我们缺的只有 digest 知道。

**结论：不要用应用内的 Update 按钮获取上游特性。** 上游特性只能走本手册
的 模式 A（③ cherry-pick）或 模式 B（④ 批量 merge），且都要求先有 SYNC-LOG
记录。

## ⑧ 定时 digest 与 cron 回退

首选实现是 systemd user timer（`scripts/systemd/upstream-watch.timer`，每日
09:00，`Persistent=true` 补跑错过时段）。**无 systemd 的环境**（容器、纯 cron
机器）退回 crontab：

```bash
crontab -e
# 追加一行：
0 9 * * * /home/cloudicen/hermes-webui/scripts/upstream-watch.sh
```

脚本本身纯 git、确定性、只 fetch 与写 digest，不做任何合入动作（见上表红线）。

## ⑨ 红线

**永不自动合入。** 上游内容进入本仓库的唯一通道是人读完 digest 后显式执行的
③/④ 流程；digest 生成、tag 观察、冲突记忆（rerere）都不构成合入授权。
任何将来加入的自动化（脚本、timer、agent）都继承这条红线：可以准备分支、
可以提问，不可以代替人按下 merge/cherry-pick，也不可以向 upstream push
（该 remote 无 push URL）。
