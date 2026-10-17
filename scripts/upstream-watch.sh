#!/usr/bin/env bash
# upstream-watch.sh — 每日上游 digest 生成器（纯 git，确定性）。
#
# 目的：记录"上次看过的上游位置"（.omo/upstream-watch/state），每次运行生成
# 覆盖 LAST..upstream/master 的 Markdown digest（新 release tags、CHANGELOG
# 增量、commit 列表），然后把 state 前移。digest 语义：last-seen = 上次 digest
# 生成时的 upstream HEAD，与是否合并过任何东西无关——每个上游 commit 恰好
# 出现在一个 digest 里，不重不漏。
#
# 确定性保证：只依赖 git/date，不发网络 API 请求（fetch 之外不碰网络），
# 不修改任何 ref（唯一写操作是 git fetch）；state 只在 digest 完整落盘后
# 原子更新（同目录临时文件 + mv）。
#
# 产物（均在 gitignored 的 .omo/upstream-watch/ 下）：
#   digest-YYYYMMDD-HHMM.md  本次 digest（文件名按生成分钟，确定性）
#   digest-latest.md         指向最新 digest 的稳定符号链接（每日交付落点）
#   state                    两行：sha=<上次看到的 upstream/master>，at=<ISO8601>
#
# 用法：scripts/upstream-watch.sh（无参数；REPO_ROOT 可用 HERMES_WEBUI_ROOT 覆盖）
set -euo pipefail

REPO_ROOT="${HERMES_WEBUI_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_ROOT"

WATCH_DIR=".omo/upstream-watch"
STATE_FILE="$WATCH_DIR/state"

# 上游 remote 必须存在（T1 已配置：fetch=github.com/nesquena/hermes-webui，push 禁用）
if ! git remote get-url upstream >/dev/null 2>&1; then
    echo "[upstream-watch] 错误：本仓库没有配置 upstream remote。" >&2
    echo "[upstream-watch] 先执行：git remote add upstream https://github.com/nesquena/hermes-webui.git" >&2
    exit 1
fi

# 拉取上游。失败时直接退出，绝不触碰 state（state 只在 digest 落盘后更新）。
if ! git fetch upstream --quiet --tags; then
    echo "[upstream-watch] 错误：git fetch upstream 失败（网络或 remote 不可用）。state 未更新。" >&2
    exit 1
fi

mkdir -p "$WATCH_DIR"

# 确定 LAST（上次看过的上游位置）：state 存在则读 sha= 行；否则基线 =
# fork-point（master 与 upstream/master 的 merge-base），首跑即为全量基线 digest。
if [[ -f "$STATE_FILE" ]]; then
    LAST=""
    while IFS='=' read -r key value; do
        if [[ "$key" == "sha" ]]; then
            LAST="$value"
        fi
    done < "$STATE_FILE"
    if [[ -z "$LAST" ]]; then
        echo "[upstream-watch] 错误：state 文件存在但缺少 sha= 行：$STATE_FILE" >&2
        exit 1
    fi
else
    LAST="$(git merge-base master upstream/master)"
fi

NEW="$(git rev-parse upstream/master)"

# 无新提交：打印提示并退出，不写 digest、不动 state。
if [[ "$LAST" == "$NEW" ]]; then
    echo "no new upstream commits"
    exit 0
fi

# 生成 digest（顺序固定：标题+元数据 → 新 release tags → CHANGELOG 增量 → Commits）
TS="$(date +%Y%m%d-%H%M)"
DIGEST="$WATCH_DIR/digest-$TS.md"
COUNT="$(git rev-list --count "$LAST..$NEW")"
TAGS="$(git tag --merged "$NEW" --no-merged "$LAST")"

{
    echo "# Upstream digest $TS"
    echo
    echo "- generated_at: $(date +%Y-%m-%dT%H:%M:%S%z)"
    echo "- upstream/master: $NEW"
    echo "- range: $LAST..$NEW"
    echo "- commit_count: $COUNT"
    echo
    echo "## New release tags"
    echo
    if [[ -n "$TAGS" ]]; then
        printf '%s\n' "$TAGS"
    else
        echo "*none*"
    fi
    echo
    echo "## CHANGELOG 增量（上游人工维护的特性信号）"
    echo
    git diff "$LAST" "$NEW" -- CHANGELOG.md
    echo
    echo "## Commits"
    echo
    git log --no-merges --format='- %h %s [%an]' "$LAST..$NEW"
} > "$DIGEST"

# digest 已完整落盘：原子前移 state（同目录临时文件 + mv），再挂稳定符号链接。
STATE_TMP="$WATCH_DIR/.state.tmp.$$"
printf 'sha=%s\nat=%s\n' "$NEW" "$(date +%Y-%m-%dT%H:%M:%S%z)" > "$STATE_TMP"
mv -f "$STATE_TMP" "$STATE_FILE"
ln -sf "${DIGEST##*/}" "$WATCH_DIR/digest-latest.md"

echo "[upstream-watch] digest 已生成：$DIGEST（$COUNT commits, $LAST..$NEW）"
