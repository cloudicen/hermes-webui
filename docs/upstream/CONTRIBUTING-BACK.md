# 回馈上游手册（本仓库 → upstream 的 PR 草案提取）

本文约定如何把本仓库自身的功能整理成可以提交给上游
`nesquena/hermes-webui` 的 PR 草案。它是
[UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) 的镜像文档：那边管上游内容如何进入
本仓库，本文管本仓库的自有价值如何反向输出。规则一句话：**本流程只
产出本地草案分支与 PR 文案；推送分支与开 PR 的动作永远由用户手动执行。**
全文都以"草案"定位——提高被认真评审的概率，不承诺上游接受任何提交。
命令与术语保留英文；PR 规范以
[CONTRIBUTING.md](../../CONTRIBUTING.md) 英文原文为准。

---

## ① 回馈判断（该不该回馈）

先分类，再动手。判断标准只有一个问题：**去掉本 fork 的部署场景、中文
文档与本机脚本之后，这个改动对普通上游用户是否仍然成立？**

| 信号 | 判定 | 示例 |
|---|---|---|
| bugfix / perf / a11y / 通用行为改进 / 可复用的 UI 模式 | 回馈候选 | custom-provider write path 系列 |
| 跟随上游可白拿的本地化翻译之外的 fork 特化内容 | 不回馈 | 中文 dev 文档（`docs/dev-workflow-zh.md`）、本机 CI/CD 脚本（`scripts/dev-server.sh`、`scripts/gateway-daemon.sh`、`scripts/systemd/`）、skin pack 资产（`static/skins/aurora/`、生成的 pack manifests） |

**动手写代码之前，先查上游 issues/PRs 有没有人在做同样的事。** 上游的
stage 分支 → RM fold 流水线每天合入约 50-60 个 commit，在途评审常年
排队（实况见 [UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) ①），与在途上游工作
撞车是常态而非意外。实例：custom-provider 区域上游 #8256 活跃，与本线
自有的 `feat(api): WebUI write path for custom providers` 系列既构成最佳
回馈候选，也构成最大冲突区。若上游同区域已有实施或计划，先在那个
issue 下留言说明你的角度，比直接开 PR 有效得多。查近期上游动态时，
daily digest（`.omo/upstream-watch/digest-latest.md`）是现成的信息源。

较大的特性（改架构、重塑工作流、新增 substantial UI）按上游 CONTRIBUTING.md
的 Path 2 规则**先开 issue 对齐方向**，避免 surprise rewrite。本文档
各节针对的都是已经确定要做的草案。

## ② 提取流程（extraction flow）

草案分支永远从上游当前 HEAD 重放，不带 master 的 fork 特化历史：

```bash
git fetch upstream
git checkout -b upstream/pr/<feature> upstream/master
# 从 master 逐个 cherry-pick 自有 commits（保持上游可读的提交序）:
git cherry-pick -x <own-commit-sha>
# 解决冲突后:
./scripts/test.sh
git diff upstream/master...HEAD --stat   # 逐文件审，确认未夹带 fork 特化内容
```

操作细则：

- **枚举自有 commits** 用分叉锚点 tag，不要硬编码日期
  （同 [UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) ① 的规则）：

  ```bash
  FP=$(git tag -l 'fork-point-*' | tail -1)
  git log --oneline --reverse "$FP"..master          # 旧→新，即 pick 的顺序
  ```

- `-x` 会在 commit 体内保留溯源 trailer，方便上游评审核对出处。
- 冲突处理与 ③ 模式的思路相反方向，但原则一致：**以所基上游现状为
  准调整自有实现**，不要把 master 上为适配 fork 而做的妥协一并带出。
- `git diff upstream/master...HEAD --stat` 必须**逐文件过目**。出现本
  机 CI 脚本、中文 dev 文档、skin pack 资产这类 fork 特化内容时，不要
  手工"抠 diff"，回到 master 修正 commit 边界（见 ⑦）后重新提取。
- 需要合并或调整提交序时，在草案分支上做交互式 rebase：一个 commit
  只装一个逻辑变更，旧→新保持可读的演进顺序。
- UI 类改动在草案分支上补采集 before/after 截图：before 在未叠 commit
  的基分支上截，after 在叠完后截，两张图缺一不可。
- 全量门禁 `./scripts/test.sh` 绿了才进入 ③/④ 的文案组装。

## ③ 上游 PR 规范（essentials，引上游 CONTRIBUTING.md）

以下要求全部来自上游
[CONTRIBUTING.md](../../CONTRIBUTING.md)，本线回馈时逐条对照：

- **一个 PR 一个逻辑变更**。一个 bugfix 加一个 CSS 清理再加一个重构
  不会被认真评审。
- PR 描述自拟六节（上游当前没有 PR 模板）：**Thinking Path /
  What Changed / Why It Matters / Verification / Risks / Model Used**。
  Thinking Path 用从项目目标到具体修复的递进要点开头，Verification
  要写实际跑过的命令与结果。
- **AI 参与必须如实披露**：Provider、exact model name or ID、影响结果
  的 notable mode 或工具使用；全程人写的也要明确写
  `None — human-authored`。这一节不可省略、不可以模糊措辞带过。
- UI 改动**必附 before/after 图**；缺图的上游原话是可能收不到有意义的
  review。
- contract-affecting 改动在 PR body 加 `Contract Routing` 节；有意变更
  契约再加 `Contract Change`（见上游 `docs/CONTRACTS.md`）。
- **文档随代码同 PR 更新**：行为、架构、测试、setup、用户流程变化要
  同步改 README / ARCHITECTURE / TESTING 等对应文档，不留"代码先到、
  文档后补"。
- release-note-worthy 的内容把措辞写进 PR body，**不要直接编辑
  CHANGELOG.md**——上游的 changelog 由 release workflow 独占。

## ④ 内嵌 PR 草案模板

复制到 PR body 后填空；标记为"仅……时保留"的节不适用就整节删除：

```markdown
## Thinking Path
- <项目目标层面的一句话>
- <该系统/流程的现状>
- <问题或机会在哪里>
- <为什么本 PR 的解法是对路的>
- <合入后用户得到什么>

## What Changed
- <按 commit 序逐条列出本 PR 做的事，一条一个逻辑变更>

## Why It Matters
- <对普通用户的实际价值；关联的 issue/讨论编号（若有）>

## Verification
- ./scripts/test.sh: <通过数/失败数/收集数>
- 手动验证: <场景、步骤、结果>
- <issue 钉住了 bug 形状时：测试如何绑定该形状；自己重建时：声明假设>

## Risks / Follow-ups
- <已知风险、未覆盖路径、后续计划>

## Model Used
- Provider: <provider 名称，或 None — human-authored>
- Model: <exact model name 或 ID>
- Mode/tools: <影响结果的 notable mode 或工具使用；无则 (none)>

## Screenshots（UI 改动必填）
- Before: <贴图/链接>
- After: <贴图/链接>

## Contract Routing（仅 contract-affecting 时保留）
- Touched: <契约家族，如 providers / streaming>
- Evidence: <连带更新的契约文档与钉住行为的测试>

## Release note wording（仅 release-note-worthy 时保留；写在这里，不改 CHANGELOG.md）
- <一行 release-note 措辞>
```

## ⑤ 提交前检查清单

草案就绪、交还用户决策之前，逐项自查：

- [ ] `./scripts/test.sh` 全量绿（确有豁免时，豁免理由写进 Verification）
- [ ] `git diff upstream/master...HEAD --stat` 逐文件审过，无 fork 特化
      内容夹带（本机 CI 脚本、中文 dev 文档、skin pack 资产等）
- [ ] `Model Used` 已如实填写，含 `None — human-authored` 的情形
- [ ] UI 改动已附 before/after 两张图
- [ ] 文档与代码同 PR；release-note 措辞在 PR body，未直接编辑
      CHANGELOG.md
- [ ] 已先查上游 issues/PRs，确认撞车情况并在 PR 内说明关系

## ⑥ 红线

- 本流程的一切自动化止步于**本地草案分支 + PR 文案**。
- **把草案分支 push 到 origin、向 `nesquena/hermes-webui` 开 PR，这两个
  动作永远由用户手动执行。** agent、脚本、hooks、定时任务都不得代劳，
  也不得在任何 remote 上代替用户确认。
- 本仓库的 `upstream` remote 本身就是 fetch-only（无 push URL，见
  [UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) ⑧⑨），回馈草案在用户手动 push
  之前只存在于本地，这是设计，不是缺陷。
- 回馈是提案不是义务。上游合不合、怎么改，不由本文决定；草案被拒或被
  重写成别的形状都属正常结果。

## ⑦ 可提取性提交卫生（日常开发准则）

回馈成本几乎完全由日常 commit 的形状决定。本线写 commit 时默认遵守：

- **一个 commit 一个逻辑变更**——与 ③ 的 PR 规范同构，日常就按"将来
  要能被单独 pick"的标准提交。
- **通用价值与 fork 特化绝不混进同一个 commit**。混在一起的改动，提取
  时要么回 master 重写历史，要么手工重演 diff，两条路都比事前拆好贵。
- 路径直觉可作第一遍分类：`api/`、`static/`、`tests/` 里的行为改动通常
  有通用价值；中文 `docs/*-zh*`、本机 `scripts/` 工具链、`.hermes/`
  状态路径、skin pack 资产通常是 fork 特化。存疑的按 ① 的判断标准问
  一遍。
- **好形状示例**：本仓库历史中的
  `feat(api): WebUI write path for custom providers` →
  `feat(i18n): providers_custom_* strings...` →
  `feat(ui): custom provider management...` →
  `docs(providers): document...` 四段式系列——后端、文案、界面、文档
  各自成 commit，旧→新排布；提取时按序 pick 四个 commit 即得一个结构
  完整的上游 PR，多一个少一个都能单独说明理由。
- 文档改动可以独立成 commit（如示例中的 `docs(providers)`），但必须
  留在同一特性序列里，保证"同一 PR 内 docs 与代码同行"在上游侧成立。

自己的草案被上游合入后，它同样会出现在 daily digest 里；按
[UPSTREAM-SYNC.md](UPSTREAM-SYNC.md) 模式 A 把它摘回本线即可。回馈与
同步共用同一套人工决策纪律，闭环到此完成。
