# 许可证与换证路线图（fork licensing roadmap）

本文只讨论许可义务的履行方式，以及未来换证/闭源的可行性与路径。
上游内容的同步流程（cherry-pick / merge / SYNC-LOG 记录）见
[`UPSTREAM-SYNC.md`](UPSTREAM-SYNC.md)，不在本文重复。配套文件：
根目录 [`NOTICE`](../../NOTICE)（归属与贡献政策声明）与
[`LICENSE`](../../LICENSE)（MIT 原文 + fork 版权行）。命令与术语保留英文。

---

## ① MIT 义务清单

上游 `nesquena/hermes-webui` 采用 MIT 许可证。本仓库 LICENSE 保留其
原文（只在版权区插入一行 fork 版权，未删改其他任何行），义务核心两条：

- 在**所有副本或实质部分（all copies or substantial portions）**中保留
  版权声明 `Copyright (c) 2025 Hermes Web UI Contributors`；
- 同时保留 MIT 许可全文（permission notice），即 LICENSE 正文本身。

义务由**再分发（distribution）**触发：对外传播 clone、打包发布、Docker
镜像分发都算；纯自用（不分发给任何人）不触发。所以本仓库任何对外发布物
都必须原样携带 LICENSE（或其等价附文）。

本仓库的履行载体：

| 载体 | 内容 |
|---|---|
| `LICENSE` | 上游 MIT 原文，版权区插入 `Copyright (c) 2026 cloudicen (independent fork modifications)` 一行 |
| `NOTICE` | fork 身份声明；分叉锚点以 `git tag -l 'fork-point-*'` 查询为准（tag 名称内嵌实际分叉日期，勿硬编码）；归属划分；inbound = outbound 的贡献政策 |
| 本文 | 换证与闭源迁移路径的工程分析 |

## ② 归属划分

MIT 义务跟着**内容来源**走，不跟仓库整体走：

| 内容 | 版权归属 | 可否换证 |
|---|---|---|
| 上游原创代码与文件 | Hermes Web UI Contributors | 否，永久携带 MIT 义务 |
| cherry-pick 自上游的提交（commit message 带 `cherry picked from` 溯源 trailer） | 上游原作者 | 否，同样永久携带 MIT 义务 |
| 改动过的上游文件 | 双方版权并存 | 自有改动部分可换证，其中的上游原样内容仍受 MIT 约束 |
| 完全新写的自有文件 | cloudicen | 可任意授权，包含专有许可 |

要点：想换证某个文件，先判断它是否 wholly-new。只要文件内还含有来自
上游的代码，那部分上游版权就永远按 MIT 附加在其可分发副本上。

## ③ 换证选项

- **自有部分**（② 表第 4 行）：可以 dual-license（MIT 与商业许可并行
  提供），也可以直接改为 proprietary；落地只需在新发布的文件中替换
  授权声明，git 历史不需要重写。
- **整仓闭源**：可行。MIT 不要求衍生作品开源，唯一条件是分发时保留
  上游版权声明与许可全文。做法：发行物附上 LICENSE 原文即可（随仓库
  分发的 LICENSE 文件已满足）。
- 换证对**已经按 MIT 分发出去的副本**无追溯力，见 ④ 与 ⑤。

## ④ 闭源迁移路径

GitHub 平台约束：本仓库是 nesquena/hermes-webui 的 fork，处于上游的
fork 网络（fork network）中，**无法直接把可见性切换为 Private**。
这是平台限制，不是 git 能解决的问题，只能先改变仓库在 fork 网络中的
位置。两条可行路径：

1. **联系 GitHub Support**：申请将本仓库脱离 fork 网络（detach from
   the fork network），脱离后即可正常变更可见性为 Private；
2. **新建独立仓库**：创建一个不带 fork 关系的空仓库，把本地历史整体
   推送过去（`git remote set-url origin <new-repo>` 之后
   `git push --all` 加 `git push --tags`），旧的公开仓库 archive 或
   保留原样都可以。

注意：已经公开过的历史**永远保持 MIT 可获得**，这一点是无害的：MIT
只授权他人使用那些历史副本，并不阻止本线的新版本闭源。闭源的含义是
"新产物不再公开"，不是"已公开内容消失"。

## ⑤ 回馈上游与换证不冲突

- 已合入上游的代码，在上游及其下游的副本**永远是 MIT**：不试图更改，
  也改不了。
- 同一份代码在本仓库仍是作者自己的版权作品。MIT 授予的许可不可撤销，
  但它约束的是已按 MIT 分发出去的那些副本；作者对本仓库的未来版本与
  未来授权方式保有完全决定权。
- 结论：向 upstream 贡献与本线日后换证/闭源可以并行不悖。贡献出去的部分
  在上游按 MIT 永存，留在本线的部分按 ②/③ 的划分处理。

## ⑥ 商标注意

- 开源许可证**不授予商标权**。"Hermes" 名称属于 Nous Research 生态
  （Hermes Agent 产品线）。
- 若走向商业化或闭源分发，应评估改名范围：产品名、UI 文案、镜像名、
  域名。
- **此处只记录决策点：本计划不执行任何改名动作**，届时另行立项评估。

## ⑦ 第三方内容

- README 引用的 GitHub user-attachments 图片（截图类）版权归**原上传
  者**所有，不在 MIT 覆盖范围内。商用或闭源分发前逐张复核来源与可用
  范围；拿不准就替换为自有截图。
- `docs/images/` 内的截图随本仓库分发，按仓库整体 MIT 条款处理（上游
  收录时默认已获授权；有疑问的同样按上一条复核）。

## ⑧ 声明

**本文为工程分析，非法律意见。** 换证、闭源、商标相关的正式商用决策，
请在执行前咨询执业律师。本文只保证与 git / GitHub 实际机制的一致性。
