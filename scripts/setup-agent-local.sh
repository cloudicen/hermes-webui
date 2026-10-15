#!/usr/bin/env bash
# setup-agent-local.sh — 把 Hermes Agent 源码与依赖收敛到本项目目录内，
# 使宿主机开发实例具备聊天/模型功能（无需把 agent 依赖装到系统环境）。
#
# 做什么（幂等，可重复运行）：
#   1. 确保仓库 .venv 存在且依赖齐全（复用 scripts/test.sh 的机制）
#   2. 把 NousResearch/hermes-agent 源码克隆到 $HERMES_HOME/hermes-agent
#      （默认 <repo>/.hermes/hermes-agent，固定 commit，与容器镜像保持同源）
#   3. 放宽 pyproject.toml 中 `python_version >= '3.14'` 依赖标记
#      （webui venv 是 3.11–3.13；保留 sys_platform 子句，不影响 Windows 条目）
#   4. 把 agent 及其依赖安装进仓库 .venv
#   5. 导入自检（import run_agent）
#
# 环境变量：
#   HERMES_AGENT_PIN   覆盖固定的 agent commit（默认与已验证的 agent 镜像构建同源）
#   HERMES_HOME        覆盖 home 位置（默认读 repo .env，再退到 <repo>/.hermes）
#
# 完成后：仓库 .env 应有 HERMES_HOME 与 HERMES_WEBUI_AGENT_DIR 两个键，
# 然后 `HERMES_WEBUI_PORT=8788 ./ctl.sh start` 即可启动带聊天功能的开发实例。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# agent 镜像 nousresearch/hermes-agent:latest（digest sha256:c69536a3…）的构建源 commit。
# 升级容器镜像后，用 `docker inspect` 的镜像 labels/官方仓库核对新 commit 并更新此处。
AGENT_PIN="${HERMES_AGENT_PIN:-0e427d788d253630d38a3a51cd76849e73cd6925}"
AGENT_REPO_URL="https://github.com/NousResearch/hermes-agent.git"

# --- .env 读取（不打印值；.env 已 gitignore） ---------------------------------
env_get() {
  local key="$1" line
  line="$(grep -E "^${key}=" .env 2>/dev/null | tail -1 || true)"
  printf '%s' "${line#*=}"
}

HERMES_HOME="${HERMES_HOME:-$(env_get HERMES_HOME)}"
HERMES_HOME="${HERMES_HOME:-$ROOT/.hermes}"
AGENT_DIR="${HERMES_WEBUI_AGENT_DIR:-$(env_get HERMES_WEBUI_AGENT_DIR)}"
AGENT_DIR="${AGENT_DIR:-$HERMES_HOME/hermes-agent}"
# 必须 export：pip -e 会执行 agent 的 setup.py，其安装注册/更新锁逻辑按默认
# home（~/.hermes）落盘——不继承就会在仓库外散落脚手架目录。
export HERMES_HOME HERMES_WEBUI_AGENT_DIR

log()  { printf '\033[1;34m[setup-agent]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[setup-agent] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1. 确保 .venv（复用 test.sh 的解析/建库机制） ------------------------------
log "1/5 确保 .venv 与 dev 依赖（./scripts/test.sh --version）"
./scripts/test.sh --version >/dev/null 2>&1 || fail ".venv 初始化失败 —— 先单独运行 ./scripts/test.sh 看具体错误"
VENV_PY="$ROOT/.venv/bin/python"
[[ -x "$VENV_PY" ]] || fail ".venv 缺少 bin/python"
log "    venv: $VENV_PY ($("$VENV_PY" --version))"

# --- 2. agent 源码（pinned 克隆） ----------------------------------------------
log "2/5 agent 源码目录: $AGENT_DIR"
if [[ -d "$AGENT_DIR/.git" ]]; then
  cur="$(git -C "$AGENT_DIR" rev-parse HEAD 2>/dev/null || true)"
  if [[ "$cur" == "$AGENT_PIN"* ]]; then
    log "    已是目标 commit ($cur)，跳过克隆"
  else
    log "    注意：现有 checkout 在 ${cur:-未知}，与期望 pin $AGENT_PIN 不同 —— 保留不动。"
    log "    如需重置到 pin：rm -rf '$AGENT_DIR' 后重跑本脚本。"
  fi
elif [[ -e "$AGENT_DIR" ]]; then
  fail "$AGENT_DIR 已存在但不是 git checkout（可能是容器预创建的占位或旧拷贝）。确认无价值后删除再重跑。"
else
  log "    克隆 $AGENT_REPO_URL @ ${AGENT_PIN:0:12}（shallow+blobless）"
  mkdir -p "$(dirname "$AGENT_DIR")"
  git init -q "$AGENT_DIR"
  git -C "$AGENT_DIR" remote add origin "$AGENT_REPO_URL"
  git -C "$AGENT_DIR" fetch -q --depth 1 --filter=blob:none origin "$AGENT_PIN" \
    || fail "git fetch $AGENT_PIN 失败（网络或 commit 不存在）"
  git -C "$AGENT_DIR" checkout -q --detach FETCH_HEAD
  log "    OK: $(git -C "$AGENT_DIR" rev-parse HEAD)"
fi
[[ -f "$AGENT_DIR/pyproject.toml" ]] || fail "$AGENT_DIR/pyproject.toml 不存在 —— 源码不完整"

# --- 3. 放宽 3.14 依赖标记（webui venv 是 3.11–3.13） ---------------------------
log "3/5 检查 pyproject.toml 的 python_version >= '3.14' 标记"
if grep -qE "( and|;) python_version >= '3.14'" "$AGENT_DIR/pyproject.toml"; then
  cp -n "$AGENT_DIR/pyproject.toml" "$AGENT_DIR/pyproject.toml.orig" 2>/dev/null || true
  sed -i -e "s/ and python_version >= '3.14'//g" \
         -e "s/; python_version >= '3.14'//g" "$AGENT_DIR/pyproject.toml"
  log "    已放宽并备份原文件为 pyproject.toml.orig"
else
  log "    无需放宽（已是 3.11–3.13 兼容）"
fi

# --- 4. 安装 agent + 依赖进仓库 .venv -------------------------------------------
# 上游 setup.py 明确拒绝非 editable 构建（只认 shell 安装器/Docker/Nix），
# 开发场景的官方路径就是 editable 安装（容器内的 docker_init 同样用 editable）。
log "4/5 editable 安装 agent 与依赖到 .venv（首次约 2-5 分钟）"
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$VENV_PY" --quiet -e "$AGENT_DIR" \
    || fail "uv pip install -e 失败"
else
  "$VENV_PY" -m pip install --quiet -e "$AGENT_DIR" || fail "pip install -e 失败"
fi

# --- 4b. 托管运行时（server 实际使用的解释器）同步完整依赖 -----------------------
# bootstrap 首启会在 $HERMES_HOME/tools/ 准备托管 Python（agent 要求 >=3.14），
# server 以它运行；agent 重依赖是懒加载，聊天触发时才需要。这里主动补全，
# 避免第一次聊天时才撞上 ImportError。
MANAGED_PY="$(ls -d "$HERMES_HOME"/tools/python-3.1[4-9]*/bin/python3 2>/dev/null | sort -V | tail -1 || true)"
if [[ -n "$MANAGED_PY" ]]; then
  log "4b/5 托管运行时依赖同步: $MANAGED_PY"
  "$MANAGED_PY" -m pip install --quiet -e "$AGENT_DIR" \
    || fail "托管 3.14 依赖安装失败"
else
  log "4b/5 未发现托管运行时（首次 dev-server.sh start 时 bootstrap 会自动准备）"
fi
log "5/5 导入自检"
if PYTHONPATH="$AGENT_DIR" "$VENV_PY" -c "import run_agent" 2>/dev/null; then
  log "    run_agent 导入 OK"
else
  "$VENV_PY" -c "import run_agent" 2>&1 | tail -3 >&2 || true
  PYTHONPATH="$AGENT_DIR" "$VENV_PY" -c "import run_agent" 2>&1 | tail -5 >&2 || true
  fail "import run_agent 失败 —— 依赖可能不完整，查看上方报错"
fi

# --- .env 两个键（缺则补，已有则不动） ------------------------------------------
ensure_env_key() {
  local key="$1" value="$2"
  grep -qE "^${key}=" .env 2>/dev/null || printf '%s=%s\n' "$key" "$value" >> .env
}
touch .env
ensure_env_key "HERMES_HOME" "$HERMES_HOME"
ensure_env_key "HERMES_WEBUI_AGENT_DIR" "$AGENT_DIR"

cat <<EOF

[setup-agent] 完成。摘要：
  HERMES_HOME            = $HERMES_HOME
  HERMES_WEBUI_AGENT_DIR = $AGENT_DIR (pinned ${AGENT_PIN:0:12})
  venv                   = $VENV_PY

下一步（宿主机开发实例，带聊天功能）：
  1. 容器 webui 与宿主机实例不要同时写同一状态目录：
       docker stop hermes-webui        # agent 容器可保留（cron 照常）
  2. scripts/dev-server.sh start             # 强制仓库内 HERMES_HOME（标准端口 8787）
  3. 打开 http://127.0.0.1:8787 完成 onboarding（provider key 由你本人输入）
  4. 开发结束：scripts/dev-server.sh stop && docker start hermes-webui
  （不要直接用 ./ctl.sh —— 它的 HERMES_HOME 默认值会压过 .env，见 dev-server.sh 头注）
EOF
