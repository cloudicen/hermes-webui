#!/usr/bin/env bash
# dev-server.sh — 宿主机开发实例启动器（带聊天/模型功能）。
#
# 为什么需要这个包装器：ctl.sh 在脚本开头就把 HERMES_HOME 预设为 ~/.hermes，
# 之后加载仓库 .env 时"已存在的环境变量优先"，导致 .env 里的 HERMES_HOME
# 被忽略。本脚本显式 export 仓库内路径后再转交 ctl.sh，杜绝踩坑。
#
# 与容器 webui（127.0.0.1:8787）共用仓库内 .hermes/，但**不应同时运行**：
# 开发前 `docker stop hermes-webui`，结束 `docker start hermes-webui`
# （agent 容器可以一直留着，cron 照常跑）。
#
# 用法：scripts/dev-server.sh start|stop|restart|status|logs [-- ...ctl.sh 参数]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export HERMES_HOME="${HERMES_HOME:-$ROOT/.hermes}"
export HERMES_WEBUI_AGENT_DIR="${HERMES_WEBUI_AGENT_DIR:-$ROOT/.hermes/hermes-agent}"
export HERMES_WEBUI_PORT="${HERMES_WEBUI_PORT:-8787}"

cmd="${1:-}"
[[ -n "$cmd" ]] || { echo "usage: scripts/dev-server.sh start|stop|restart|status|logs" >&2; exit 2; }

echo "[dev-server] HERMES_HOME=$HERMES_HOME  port=$HERMES_WEBUI_PORT"
exec "$ROOT/ctl.sh" "$@"
