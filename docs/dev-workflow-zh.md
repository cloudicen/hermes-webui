# 本地开发工作流（修改 → 本地验证 → 提交 → 发布/部署）

本文把 [`CONTRIBUTING.md`](../CONTRIBUTING.md)、[`TESTING.md`](../TESTING.md)、[`AGENTS.md`](../AGENTS.md)
中与日常开发相关的规则整合为一份中文速查，便于贡献者与 AI agent 直接遵循。
规则有出入时以英文原文为准。文中工作流已实际验证（Linux）。

## 部署形态：全程宿主机

本工作流的开发与部署都跑在宿主机上（真实过程验证：皮肤系统、gateway 守护、
agent 环境全部以宿主机脚本交付）。上游自带容器部署文档
（[`docs/docker.md`](docker.md)），如确需容器可自行参考，本仓库不附带
容器编排的定制文件。**无论哪种形态，都不要让两个 WebUI 实例同时写同一
状态目录**（例如上游容器部署与本地开发实例并存时，开发前先停部署实例的
webui 服务）。

---

## 运行形态：本地开发的一切都在项目目录内

| 路径 | 内容 |
|---|---|
| `.hermes/` | **HERMES_HOME**：个人数据（`config.yaml`、`memories/`、`skills/`、`sessions/`、`state.db`、`cron/`、`auth.json`、`.env`）+ WebUI 状态（`.hermes/webui/`）+ **agent 源码**（`.hermes/hermes-agent/`，pinned commit）+ **托管工具链**（`.hermes/tools/`：server 运行用的 Python 3.14、node、uv、ffmpeg、ripgrep、chromium 等） |
| `.venv/` | 测试与本地工具链 venv（Python 3.11–3.13，含 agent 依赖，供 pytest 用） |
| `.env` | 本机覆盖键（gitignored）：`HERMES_HOME`、`HERMES_WEBUI_AGENT_DIR`、`API_SERVER_KEY` |
| WebUI 进程 | `scripts/dev-server.sh`（`127.0.0.1:8787`） |
| gateway 守护进程 | `scripts/gateway-daemon.sh`（cron 调度 + 元数据刷新，见 §3） |

以上目录均已 gitignore（`.hermes/`、`.venv/`、`.env`），永远不会进提交。
**⚠️ `git clean -fdx` 会删掉 `.hermes/` 里的全部个人数据与凭据——除非有备份，永远不要跑。**

---

## 0. 环境准备（一次性）

- **Python 3.11–3.13**：`./scripts/test.sh` 自动创建仓库 `.venv` 并安装 dev 测试依赖；
  系统解释器不合规时用 `HERMES_WEBUI_TEST_PYTHON=/path/to/python3.1x` 指定。
- **本地 CI 门禁**：`./scripts/install-hooks.sh`（设 `core.hooksPath scripts/ci`，幂等）：
  - `pre-commit`：全树 `compileall` → ruff 增量门（仅新增/改动行）→ **暂存内容** ruff 门 →
    暂存 `static/**/*.js` 时的 ESLint runtime guard + scope_undef 门。
  - `pre-push`：重跑廉价门禁（防 `--no-verify`）→ **全量 pytest 并行分片**
    （默认 `min(8, nproc)` 且按可用内存封顶，约 2GB/分片）→ 可选 browser smoke
    （`HERMES_WEBUI_PUSH_BROWSER_SMOKE=1` 显式开启）。
  - 跳过开关：`HERMES_WEBUI_SKIP_HOOKS / SKIP_PY_LINT / SKIP_JS / SKIP_TESTS / SKIP_BROWSER_SMOKE`；
    调参：`HERMES_WEBUI_TEST_SHARDS`、`HERMES_WEBUI_PUSH_PYTEST_ARGS`。
  - 卸载：`git config --unset core.hooksPath`。
- **Node ≥ 20**：仅提交 `static/**/*.js` 时需要（`eslint@^10` 在旧 Node 上按设计 fail-closed）。
- **聊天/模型功能 + gateway 守护（一次性）**：`./scripts/setup-agent-local.sh`（幂等）：
  1. 确保仓库 `.venv`（复用 test.sh 机制）；
  2. 把 `NousResearch/hermes-agent` 源码克隆到 `.hermes/hermes-agent/`（固定 commit，
     默认与已验证的 agent 镜像构建同源，`HERMES_AGENT_PIN` 可覆盖）；
  3. 放宽其 `pyproject.toml` 的 `python_version >= '3.14'` 依赖标记（webui venv 是 3.11–3.13；
     备份为 `pyproject.toml.orig`）；
  4. 以 editable 方式把 agent 与依赖装入 `.venv`（上游 `setup.py` 拒绝非 editable 构建）；
  4b. 若存在托管 Python（`.hermes/tools/python-3.14…`），同步完整依赖到它
      （server 与 gateway 守护的运行时解释器；agent 重依赖是懒加载，聊天触发时才需要）；
  5. `import run_agent` 自检。
  完成后自动补写 `.env` 的 `HERMES_HOME` / `HERMES_WEBUI_AGENT_DIR`。

## 1. 修改

- **一个 PR 一个逻辑变更**；无关的清理/重构分开提（CONTRIBUTING.md「One Logical Change Per PR」）。
- 保持项目约束：**无构建步骤、无打包器、无前端框架**；不引入新依赖/基础设施，
  除非收益明确且给出回滚说明。
- 服务端逻辑进 `api/`（`server.py` 保持薄）；前端行为进现有 `static/*.js` 模块。
- **契约相关 PR**（改了公开契约文档/RFC/产品语义测试或实现其描述的行为）：
  PR 正文需 `Contract Routing` 小节；有意改契约另加 `Contract Change`（旧规则/新规则/理由）。
  见 [`docs/CONTRACTS.md`](CONTRACTS.md)。
- **安全敏感面**（认证、路径处理、上传、流式、环境变量）：PR 说明中显式声明并说明验证方式。
- 运行时/流式/恢复/压缩/会话元数据类变更：指明被改的状态层、权威值与所有者，
  并证明相关不变量（含清理路径）。

## 2. 本地验证

- 提交时快速门禁自动运行（§0 hooks）。
- **测试套件**：`./scripts/test.sh`（约 1.1 万+ 测试，隔离 server/state fixtures，不触真实状态）。
  - 聚焦：`./scripts/test.sh tests/test_xxx.py -v`
  - 本地分片：`./scripts/test.sh tests/ -q --shard-id=i --num-shards=N`（pytest-shard，0 起索引）
  - agent 相关测试需要 §0 的 agent 依赖（装在 `.venv`）。
- **Python lint 门**：`python3 scripts/ruff_lint.py --diff origin/master`（`--all` 为信息性积压报告）。
- **JS runtime 门**：`npm run lint:runtime` 与 `python3 scripts/scope_undef_gate.py`。
- **浏览器冒烟**：`pip install playwright && python -m playwright install chromium && python tests/browser_smoke.py`。
- **UI/UX 变更**：按 [`TESTING.md`](../TESTING.md) 手测计划覆盖桌面/窄屏/移动，PR 必须附前后对比截图。
- 行为变更尽量带回归测试；bug 修复给出「修复前失败/修复后通过」的证据；
  issue 已固定 bug 形态时测试必须绑定该形态（GUIDELINES.md）。

## 3. 本地启动与查看效果（聊天开发循环）

本地开发同时涉及**两个独立进程**：

```bash
scripts/dev-server.sh start      # WebUI（127.0.0.1:8787，进程内聊天）
scripts/gateway-daemon.sh start  # gateway 守护（cron 调度 + 元数据刷新，可选但推荐常驻）
# 打开 http://127.0.0.1:8787 —— provider 的 API key 由你本人在 onboarding 输入
scripts/dev-server.sh stop       # 开发结束；gateway 守护按需独立启停
```

### 3.1 WebUI：dev-server.sh

- **为什么不用 `./ctl.sh`**：ctl.sh 在脚本开头把 `HERMES_HOME` 预设为 `~/.hermes`，之后加载
  仓库 `.env` 时"已存在的环境变量优先"，`.env` 里的 `HERMES_HOME` 会被忽略（实测踩坑）。
  `dev-server.sh` 显式 export 仓库内路径后再转交 ctl.sh，杜绝此问题。
- **首次启动行为**：bootstrap 检测到 agent 源要求 Python ≥3.14 而 `.venv` 不满足时，会自动下载
  托管 CPython 与工具链到 `.hermes/tools/`（node/uv/ffmpeg/ripgrep/chromium 等）。
  守护模式下该下载**零输出**，慢网络表现为"长时间静默"——想知道进度就用前台方式跑一次：
  `python3 -u bootstrap.py --no-browser --foreground --host 127.0.0.1 8787`。
- **改动 → 生效语义**：

| 改什么 | 怎么生效 |
|---|---|
| `api/*.py`、`server.py` | **必须重启** `scripts/dev-server.sh restart`（模块在进程启动时一次性 import，无热重载） |
| `static/*.js/.css`、`index.html` | 不重启，浏览器刷新即可（服务端按 mtime 下发新字节） |
| `config.yaml` | 热加载（mtime 检测），无需重启 |
| `settings.json` | 多数即时；host/port/状态目录等启动期值需重启 |
| 环境变量 | 必须重启 |

- **经典坑**（"改了却看不到"时按序排查）：
  1. 旧进程仍占端口：新实例静默退出，浏览器还在跟旧进程说话 → `scripts/dev-server.sh status`。
  2. 带 `?v=` 指纹的资源是 `immutable` 缓存；不重启时 URL 不变 → 强刷（Ctrl-Shift-R）。
  3. service worker 覆盖主壳资源（network-first）；`static/outline.js`、
     `static/extension_settings.js`、`static/login.js` 不在覆盖名单 → 需强刷。
  4. 最省心：改动后重启一次服务再刷新——重启使 dirty-digest 变化，`?v=` 全部击穿。
  5. 运行时会写 checkout：`__pycache__`/`.venv` 正常；**不要在 UI 里点"检查更新/自更新"**
     （它会对仓库执行 `git fetch`/`stash`/`pull`，污染工作区）。

### 3.2 gateway 守护：gateway-daemon.sh（cron 调度与元数据刷新）

**为什么是独立进程**：webui 的启动流程**不会**拉起 gateway——这是上游的架构切分。
webui 进程负责界面与进程内聊天，并在启动/运行时**写** gateway 状态元数据；
而 cron 的自动调度（每 60s tick）与元数据的持续刷新由独立的 gateway 守护负责。
守护缺席时，`.hermes/gateway_state.json` 仍显示 "running" 但无人刷新，
WebUI 即报 **"Gateway metadata stale"**。

```bash
scripts/gateway-daemon.sh start    # 常驻；stop/status/logs 同理
```

- 使用托管 3.14（`.hermes/tools/python-3.14…/bin`）**直接调用 `hermes_cli.main:main`**，
  绕过 `hermes` launcher 的自管理运行时（其预配会发起外部网络请求，慢网络下
  SSL EOF 反复重试，实测 90s 无法完成）；依赖由 §0 的 4b 步骤装好，秒级启动。
- repo `.env` 提供 `API_SERVER_KEY` 时，守护额外绑定 `127.0.0.1:8642` API 监听，
  WebUI 的 Tasks/System 健康探针据此变绿；不设则纯守护模式（cron 照常 tick）。
- 验证：`gateway_state.json` mtime 每 tick 刷新、`/api/health/agent` 的 gateway 块、
  `curl -H "Authorization: Bearer $API_SERVER_KEY" http://127.0.0.1:8642/health/detailed`。
- **何时可以不跑**：完全不用 cron 定时任务时。守护停止后 stale 警告会再现
  （信息性提示，不影响聊天）；任务仍可手动 "Run now"（webui 进程内执行）。
- 与 webui 生命周期独立：**重启 webui 不需要重启 gateway**；守护也不随 webui 退出。

### 3.3 provider 凭据

provider 的 API key 等凭据**由人输入**（onboarding 向导或 `hermes model`），
写入 `.hermes/` 随项目持久化。

## 4. 提交

### 4.1 提交信息规范

- 主题行：英文语义式 `type(scope): subject`（与仓库历史一致：feat / fix / test / docs / chore …）。
- **主体双语**：中文段落 + 英文段落各一段，说明"为什么改、改了什么"；
  主题行让审阅者 30 秒内看懂，细节进主体。
- 一次提交只描述一件事——不要在信息里罗列多个不相关变更。

### 4.2 提交切分

- **一个提交一个逻辑变更**；实现与其测试放在同一提交。
- 生成物/批量内容（如生成的清单文件）单独成提交，不与手写代码混排。
- 依赖序：地基（引擎/工具）→ 依赖方（路由/UI）→ 文档；每个提交独立可绿、可独立回滚。
- 单文件携带多个关注点时做 **hunk 级暂存**（`git diff` 提取相关 hunk 后
  `git apply --cached`），不让无关变更搭车。

### 4.3 历史与安全

- **永不重写已推送的历史**；未推送的本地历史也要在明确指示下才重组
  （折并 fixup、修改信息），且重组后必须校验最终树哈希一致（内容零变化）。
- 提交身份未配置时用环境变量（`GIT_AUTHOR_NAME/EMAIL` 等），不改全局配置。
- **不编辑 `CHANGELOG.md`**（发布流程维护）；release-note 措辞写进 PR 描述。
- 不养成 `--no-verify` 的习惯；确需跳过时用 §0 的显式跳过开关（会打印警告）。

### 4.4 PR 结构

- Thinking Path / What Changed / Why It Matters / Verification / Risks / Follow-ups / Model Used。
- **AI 披露**：provider、精确模型名、起关键作用的模式/工具；未用 AI 则写 `None — human-authored`。
- 本地 hook 的 `pre-push` 会跑全量套件：push 前先本地跑通。

## 5. 发布与部署

部署就是让 §3 的两个进程常驻：`scripts/dev-server.sh start` +
`scripts/gateway-daemon.sh start`（开机自启可参照上游
[`docs/supervisor.md`](supervisor.md) 的 systemd/launchd 配法）。

可选的镜像发布：`scripts/release-docker.sh` 构建并推送 WebUI 镜像
（默认本地 registry:2，`--image` 可指向远端 registry，`--dry-run` 先看计划）。
构建前自动跑 compileall + ruff 门禁；完整用法见
[TESTING.md → Local CI/CD](../TESTING.md#local-cicd-git-hooks--docker-cd)。

## 6. AI agent 检查清单

- `.hermes/` 内含**凭据与个人数据**：不打印 API key/token/完整 `.env`/`auth.json`，不删改其中内容。
- **永不跑 `git clean -fdx`**（会删光 `.hermes/` 个人数据）；需要清理未跟踪文件时逐个确认。
- `dev-server` 与 `gateway-daemon` 是**两个独立进程**：重启 webui 不需要重启 gateway；
  排障时分别看 `.hermes/webui.log` 与 `.hermes/gateway-daemon.log`。
- 隔离试运行规则照旧（[`docs/onboarding-agent-checklist.md`](onboarding-agent-checklist.md)）：
  试验用临时 `HERMES_HOME`/`HERMES_WEBUI_STATE_DIR`，除非用户明确要求真实状态。
- 非密钥证据命令：`/health`、`/api/health/agent`（gateway 块）、`/api/onboarding/status`
  白名单字段、两个日志文件尾部。
- 冷启动路径：读本文 §0 → `./scripts/setup-agent-local.sh`（幂等）→
  `scripts/dev-server.sh start` → `scripts/gateway-daemon.sh start`。
