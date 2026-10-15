#!/usr/bin/env bash
# gateway-daemon.sh — 宿主机常驻 gateway 守护（cron 调度 + 运行时元数据刷新）。
#
# 为什么需要：cron 的自动调度（每 60s tick）与 gateway 运行时元数据的持续刷新
# 由 gateway 守护驱动，webui 自身不做这两件事。守护缺席时 webui 报
# "Gateway metadata stale"（state 文件还是 running 但无人刷新）。
#
# 为什么绕过 `hermes` launcher：launcher 自管理隔离运行时，预配时会发起外部
# 网络请求（慢网络下 SSL EOF 反复重试，实测 90s 无法完成）；直接调用
# hermes_cli.main:main 则使用托管 3.14（scripts/setup-agent-local.sh 步骤 4b
# 装好的全量依赖），秒级启动。后果：不要用 `hermes pm repair` 之外的姿势
# 升级该运行时——升级 agent 源后重跑 setup-agent-local.sh 即可。
#
# 与 webui 的关系：共享仓库内 HERMES_HOME（与官方双容器拓扑的共享方式一致），
# 可与 dev-server.sh 同时运行；8642 API 监听仅绑定 127.0.0.1。
#
# 用法：scripts/gateway-daemon.sh start|stop|status|logs [N]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export HERMES_HOME="${HERMES_HOME:-$ROOT/.hermes}"
export HERMES_WEBUI_AGENT_DIR="${HERMES_WEBUI_AGENT_DIR:-$ROOT/.hermes/hermes-agent}"

PID_FILE="$HERMES_HOME/gateway-daemon.pid"
LOG_FILE="$HERMES_HOME/gateway-daemon.log"

MANAGED_PY="$(ls -d "$HERMES_HOME"/tools/python-3.1[4-9]*/bin/python3 2>/dev/null | sort -V | tail -1 || true)"
[[ -n "$MANAGED_PY" ]] || { echo "[gateway-daemon] 未找到托管 Python —— 先运行 scripts/setup-agent-local.sh" >&2; exit 2; }

# API_SERVER_KEY（可选）：设置后守护额外绑定 127.0.0.1:8642 API 监听，
# webui 的 Tasks/System 健康探针据此变绿；不设则纯守护模式（cron 照常 tick）。
if [[ -z "${API_SERVER_KEY:-}" && -f "$ROOT/.env" ]]; then
  API_SERVER_KEY="$(grep -E '^API_SERVER_KEY=' "$ROOT/.env" | tail -1 | cut -d= -f2-)"
  [[ -n "$API_SERVER_KEY" ]] && export API_SERVER_KEY
fi

cmd="${1:-}"
[[ -n "$cmd" ]] || { echo "usage: scripts/gateway-daemon.sh start|stop|status|logs" >&2; exit 2; }

is_alive() { [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

case "$cmd" in
  start)
    if is_alive; then
      echo "[gateway-daemon] 已在运行 (PID $(cat "$PID_FILE"))"
      exit 0
    fi
    rm -f "$PID_FILE"
    echo "[gateway-daemon] 启动 ($MANAGED_PY)"
    nohup "$MANAGED_PY" -c "
import sys
from hermes_cli.main import main
sys.argv = ['hermes', 'gateway', 'run']
sys.exit(main())
" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 3
    if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[gateway-daemon] 启动失败，日志尾部:" >&2
      tail -n 10 "$LOG_FILE" >&2 || true
      rm -f "$PID_FILE"
      exit 1
    fi
    echo "[gateway-daemon] 运行中 (PID $(cat "$PID_FILE"))"
    echo "  cron: 每 60s tick    日志: $LOG_FILE"
    if [[ -n "${API_SERVER_KEY:-}" ]]; then
      echo "  API 监听: 127.0.0.1:8642（API_SERVER_KEY 已设）"
    else
      echo "  API 监听: 未启用（repo .env 提供 API_SERVER_KEY 可开启）"
    fi
    ;;
  stop)
    if is_alive; then
      pid="$(cat "$PID_FILE")"
      echo "[gateway-daemon] 停止 (PID $pid)"
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      echo "[gateway-daemon] 已停止"
    else
      echo "[gateway-daemon] 未在运行"
    fi
    rm -f "$PID_FILE"
    ;;
  status)
    if is_alive; then
      echo "[gateway-daemon] 运行中 (PID $(cat "$PID_FILE"))"
      echo "  gateway_state mtime: $(stat -c %y "$HERMES_HOME/gateway_state.json" 2>/dev/null || echo '?')"
      echo "  日志: $LOG_FILE（tail -5:）"
      tail -n 5 "$LOG_FILE" || true
    else
      echo "[gateway-daemon] 未在运行"
      exit 1
    fi
    ;;
  logs)
    tail -n "${2:-100}" -f "$LOG_FILE"
    ;;
  *)
    echo "usage: scripts/gateway-daemon.sh start|stop|status|logs [N]" >&2
    exit 2
    ;;
esac
