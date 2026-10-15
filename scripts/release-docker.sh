#!/usr/bin/env bash
set -euo pipefail

# release-docker.sh — local CD for the hermes-webui Docker image.
#
# Local counterpart of the image half of .github/workflows/release.yml: on a
# `v*` / `exp-v*` tag CI builds a multi-arch (linux/amd64,linux/arm64) image
# with `--build-arg HERMES_VERSION=<tag>` and pushes it to ghcr.io. This
# script does the same job from a checkout, defaulting to a LOCAL registry
# (localhost:5000, a plain registry:2) so images are published in-house first;
# the same --image/--tag flags retarget a remote registry later.
#
# Usage:
#   scripts/release-docker.sh [--image NAME] [--tag TAG] [--platforms LIST]
#                             [--no-push] [--also-latest] [--skip-gates]
#                             [--ensure-registry] [--dry-run]
#
# Examples:
#   scripts/release-docker.sh --dry-run
#   scripts/release-docker.sh --ensure-registry
#   scripts/release-docker.sh --tag v0.52.1 --also-latest \
#       --platforms linux/amd64,linux/arm64
#   scripts/release-docker.sh --image ghcr.io/cloudicen/hermes-webui --tag v0.52.1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LOCAL_REGISTRY_CONTAINER="hermes-local-registry"
DEFAULT_LOCAL_REGISTRY="localhost:5000/hermes-webui"

err()  { printf '%s\n' "$*" >&2; }
die()  { err "error: $*"; exit 1; }
die2() { err "error: $*"; exit 2; }
step() { err "==> $*"; }

usage() {
  cat >&2 <<'EOF'
Usage: scripts/release-docker.sh [--image NAME] [--tag TAG] [--platforms LIST] [--no-push]
                                 [--also-latest] [--skip-gates] [--ensure-registry] [--dry-run]

Build (and by default push) the hermes-webui Docker image — the local
counterpart of the image job in .github/workflows/release.yml. Images go to a
LOCAL registry by default; the same flags retarget a remote registry later.

Options:
  --image NAME          Image repository. Resolution: --image >
                        env HERMES_DOCKER_IMAGE > localhost:5000/hermes-webui.
  --tag TAG             Image tag. Default: exact git tag on HEAD, else
                        local-<short-9 SHA of HEAD>. Plain names only —
                        registry host and path belong in --image.
  --platforms LIST      Comma-separated platforms, e.g.
                        linux/amd64,linux/arm64. Default: host arch only.
                        Multiple platforms require docker buildx (plus binfmt
                        for foreign architectures).
  --no-push             Build and tag locally only; nothing is pushed.
  --also-latest         Additionally tag/push <image>:latest (explicit only —
                        there is never an automatic latest).
  --skip-gates          Skip the pre-build compileall + ruff gates.
  --ensure-registry     When the resolved registry is local
                        (localhost/127.0.0.1/0.0.0.0) and unreachable, start a
                        registry:2 container for it (or start the existing
                        stopped one) and wait for it to come up.
  --dry-run             Run preflight + gates, print the fully resolved plan
                        and the exact command lines, then stop before any
                        docker build/run.

Examples:
  scripts/release-docker.sh --dry-run
  scripts/release-docker.sh --ensure-registry
  scripts/release-docker.sh --tag v0.52.1 --also-latest --platforms linux/amd64,linux/arm64
  scripts/release-docker.sh --image ghcr.io/cloudicen/hermes-webui --tag v0.52.1
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

IMAGE_OPT=""
TAG_OPT=""
PLATFORMS_OPT=""
NO_PUSH=0
ALSO_LATEST=0
SKIP_GATES=0
ENSURE_REGISTRY=0
DRY_RUN=0

need_value() {
  # $1 = flag, $2 = candidate value (may be missing)
  if [[ $# -lt 2 || -z "$2" ]]; then
    err "error: $1 requires a value"
    usage
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)           need_value "$@"; IMAGE_OPT="$2"; shift 2 ;;
    --tag)             need_value "$@"; TAG_OPT="$2"; shift 2 ;;
    --platforms)       need_value "$@"; PLATFORMS_OPT="$2"; shift 2 ;;
    --no-push)         NO_PUSH=1; shift ;;
    --also-latest)     ALSO_LATEST=1; shift ;;
    --skip-gates)      SKIP_GATES=1; shift ;;
    --ensure-registry) ENSURE_REGISTRY=1; shift ;;
    --dry-run)         DRY_RUN=1; shift ;;
    -h|--help)         usage; exit 0 ;;
    *)
      err "error: unknown option: $1"
      usage
      exit 2
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Preflight: git repo, docker CLI, docker daemon
# ---------------------------------------------------------------------------

step "Preflight"
cd "$ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  die2 "not inside a git repository ($ROOT) — run this from a hermes-webui checkout"
fi

if ! command -v docker >/dev/null 2>&1; then
  err "error: the docker CLI was not found on PATH."
  err "Install Docker Engine (https://docs.docker.com/engine/install/) or Docker Desktop, then re-run."
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  err "error: cannot reach the Docker daemon (docker info failed)."
  err "Is the docker daemon running? Start it (e.g. 'systemctl start docker' or open Docker Desktop)"
  err "and make sure your user can access it (the 'docker' group on Linux)."
  exit 2
fi

# ---------------------------------------------------------------------------
# Resolve image, tag, platforms, builder
# ---------------------------------------------------------------------------

IMAGE="${IMAGE_OPT:-${HERMES_DOCKER_IMAGE:-$DEFAULT_LOCAL_REGISTRY}}"
if [[ -z "$IMAGE" || "$IMAGE" =~ [[:space:]] || "$IMAGE" == *: || "${IMAGE##*/}" == "" ]]; then
  die2 "invalid image name: '$IMAGE' (expected [host[:port]/]name, e.g. $DEFAULT_LOCAL_REGISTRY)"
fi

if [[ -n "$TAG_OPT" ]]; then
  TAG="$TAG_OPT"
elif GIT_TAG="$(git describe --tags --exact-match 2>/dev/null)"; then
  TAG="$GIT_TAG"
else
  TAG="local-$(git rev-parse --short=9 HEAD)"
fi
if [[ ! "$TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]]; then
  die2 "invalid tag '$TAG': tags are plain names (letters, digits, '.', '_', '-'; no '/'); put registry host/path in --image"
fi

ALL_TAGS=("$TAG")
if [[ $ALSO_LATEST -eq 1 ]]; then
  ALL_TAGS+=("latest")
fi

if [[ -n "$PLATFORMS_OPT" ]]; then
  PLATFORMS="$PLATFORMS_OPT"
else
  case "$(uname -m)" in
    x86_64)        PLATFORMS="linux/amd64" ;;
    aarch64|arm64) PLATFORMS="linux/arm64" ;;
    *)
      die2 "unsupported host architecture '$(uname -m)': pass --platforms explicitly (e.g. --platforms linux/amd64)"
      ;;
  esac
fi

PLATFORM_LIST=()
for _p in ${PLATFORMS//,/ }; do
  _p="${_p#"${_p%%[![:space:]]*}"}"
  _p="${_p%"${_p##*[![:space:]]}"}"
  [[ -z "$_p" ]] && die2 "invalid --platforms value '$PLATFORMS' (empty entry)"
  PLATFORM_LIST+=("$_p")
done
PLATFORM_COUNT=${#PLATFORM_LIST[@]}

HOST_ARCH="$(uname -m)"
case "$HOST_ARCH" in
  x86_64)        HOST_PLATFORM="linux/amd64" ;;
  aarch64|arm64) HOST_PLATFORM="linux/arm64" ;;
  *)             HOST_PLATFORM="" ;;
esac

if docker buildx version >/dev/null 2>&1; then
  BUILDER="buildx"
else
  BUILDER="classic"
fi

if [[ $PLATFORM_COUNT -gt 1 ]]; then
  if [[ "$BUILDER" != "buildx" ]]; then
    _arch_list=""
    for _p in "${PLATFORM_LIST[@]}"; do
      _a="${_p#linux/}"
      _arch_list="${_arch_list:+$_arch_list,}$_a"
    done
    err "error: multi-platform build (--platforms $PLATFORMS) requires docker buildx, which is not available."
    err "Set it up once on this machine:"
    err "  docker buildx create --use --name hermes-builder"
    err "  docker run --privileged --rm tonistiigi/binfmt --install $_arch_list"
    exit 1
  fi
  if [[ $NO_PUSH -eq 1 ]]; then
    die2 "--no-push with multiple platforms is not supported: buildx --load cannot import a multi-platform manifest into the local daemon. Either drop --no-push (push to the registry) or build a single platform."
  fi
fi

if [[ "$BUILDER" == "classic" && $PLATFORM_COUNT -eq 1 && -n "$HOST_PLATFORM" \
      && "${PLATFORM_LIST[0]}" != "$HOST_PLATFORM" ]]; then
  step "note: classic docker build for non-host platform ${PLATFORM_LIST[0]} (host is $HOST_PLATFORM) may fail without buildx + binfmt (docker buildx create --use --name hermes-builder; docker run --privileged --rm tonistiigi/binfmt --install ${PLATFORM_LIST[0]#linux/})"
fi

# ---------------------------------------------------------------------------
# Resolve the registry host/port from the image name
# ---------------------------------------------------------------------------

REG_HOST=""
REG_PORT=""
REG_IS_LOCAL=0
_first="${IMAGE%%/*}"
if [[ "$IMAGE" == */* && ( "$_first" == *.* || "$_first" == *:* || "$_first" == "localhost" ) ]]; then
  if [[ "$_first" == *:* ]]; then
    REG_HOST="${_first%%:*}"
    REG_PORT="${_first##*:}"
  else
    REG_HOST="$_first"
    REG_PORT=""
  fi
  case "$REG_HOST" in
    localhost|127.0.0.1|0.0.0.0) REG_IS_LOCAL=1 ;;
  esac
fi
if [[ $REG_IS_LOCAL -eq 1 ]]; then
  if [[ -z "$REG_PORT" ]]; then
    REG_PORT="5000"  # standard registry:2 port when the image name carries none
  elif [[ ! "$REG_PORT" =~ ^[0-9]+$ ]]; then
    die2 "invalid port in image name: '$IMAGE'"
  fi
fi

# ---------------------------------------------------------------------------
# Pre-build gates (mirror the CI lint job: never ship an image from a broken tree)
# ---------------------------------------------------------------------------

run_gates() {
  step "Gate 1/2: python3 -m compileall -q api server.py bootstrap.py mcp_server.py tests scripts"
  if ! python3 -m compileall -q api server.py bootstrap.py mcp_server.py tests scripts; then
    err "error: compileall gate failed — fix the syntax errors above before building a release image."
    exit 1
  fi

  step "Gate 2/2: scripts/ruff_lint.py --diff origin/master (new/changed lines only)"
  local lint_base="origin/master"
  if ! git rev-parse --verify --quiet "${lint_base}^{commit}" >/dev/null 2>&1; then
    step "origin/master not resolvable — attempting a best-effort shallow fetch"
    git fetch --no-tags --depth=1 origin master >/dev/null 2>&1 || true
  fi
  if git rev-parse --verify --quiet "${lint_base}^{commit}" >/dev/null 2>&1; then
    local py="python3"
    if [[ -x "$ROOT/.venv/bin/python" ]]; then
      py="$ROOT/.venv/bin/python"  # repo venv has ruff installed
    fi
    if ! "$py" scripts/ruff_lint.py --diff "$lint_base"; then
      err "error: ruff lint gate failed — fix the findings above (they are on new/changed lines only)."
      exit 1
    fi
  else
    step "notice: cannot resolve origin/master even after a fetch; skipping the ruff gate (non-blocking)."
  fi
}

if [[ $SKIP_GATES -eq 1 ]]; then
  GATES_DESC="skipped (--skip-gates)"
else
  run_gates
  GATES_DESC="passed (compileall + ruff)"
fi

# ---------------------------------------------------------------------------
# Local-registry handling
# ---------------------------------------------------------------------------

probe_registry() {
  local host="$1" port="$2"
  if command -v timeout >/dev/null 2>&1; then
    timeout 2 bash -c "</dev/tcp/$host/$port" >/dev/null 2>&1
  else
    bash -c "</dev/tcp/$host/$port" >/dev/null 2>&1
  fi
}

wait_for_registry() {
  local host="$1" port="$2" i
  for ((i = 0; i < 15; i++)); do
    if probe_registry "$host" "$port"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

ensure_local_registry() {
  local host="$1" port="$2" names
  if probe_registry "$host" "$port"; then
    step "Local registry $host:$port is reachable"
    return 0
  fi
  step "Local registry $host:$port is unreachable — looking for container '$LOCAL_REGISTRY_CONTAINER'"
  if names="$(docker ps -a --format '{{.Names}}' 2>/dev/null)" && grep -qx "$LOCAL_REGISTRY_CONTAINER" <<<"$names"; then
    step "Container '$LOCAL_REGISTRY_CONTAINER' exists; starting it"
    docker start "$LOCAL_REGISTRY_CONTAINER"
  else
    step "Starting registry:2 as '$LOCAL_REGISTRY_CONTAINER' (host port $port -> 5000)"
    docker run -d --restart unless-stopped --name "$LOCAL_REGISTRY_CONTAINER" -p "$port:5000" registry:2
  fi
  step "Waiting for $host:$port to accept connections"
  if ! wait_for_registry "$host" "$port"; then
    err "error: local registry $host:$port did not become reachable within ~15s."
    err "Check 'docker logs $LOCAL_REGISTRY_CONTAINER' — is host port $port free and mapped (-p $port:5000)?"
    return 1
  fi
  step "Local registry $host:$port is up"
}

# ---------------------------------------------------------------------------
# Build command construction (shared by --dry-run and the real run)
# ---------------------------------------------------------------------------

BUILD_CMD=()
if [[ "$BUILDER" == "buildx" ]]; then
  BUILD_CMD=(docker buildx build --platform "$PLATFORMS"
             --build-arg "HERMES_VERSION=$TAG"
             --provenance=false --sbom=false)
else
  BUILD_CMD=(docker build --build-arg "HERMES_VERSION=$TAG")
fi
for _t in "${ALL_TAGS[@]}"; do
  BUILD_CMD+=(-t "${IMAGE}:${_t}")
done
if [[ "$BUILDER" == "buildx" ]]; then
  if [[ $NO_PUSH -eq 1 ]]; then
    BUILD_CMD+=(--load)
  else
    BUILD_CMD+=(--push)
  fi
fi
BUILD_CMD+=(.)

BUILDER_DESC="docker buildx"
[[ "$BUILDER" == "classic" ]] && BUILDER_DESC="classic docker build"

if [[ $REG_IS_LOCAL -eq 1 ]]; then
  REGISTRY_DESC="$REG_HOST:$REG_PORT (local)"
elif [[ -n "$REG_HOST" ]]; then
  REGISTRY_DESC="$REG_HOST (remote)"
else
  REGISTRY_DESC="default registry / Docker Hub"
fi

print_cmd() {
  # Quote only args that would not survive a shell round-trip (never printf %q: it escapes commas).
  local _a _out=""
  for _a in "$@"; do
    if [[ "$_a" == *[[:space:]\'\"\*\?\[\]\$]* ]]; then
      _a="'$_a'"
    fi
    _out="${_out:+$_out }$_a"
  done
  printf '    %s\n' "$_out"
}

# ---------------------------------------------------------------------------
# Dry run: print the resolved plan and stop
# ---------------------------------------------------------------------------

if [[ $DRY_RUN -eq 1 ]]; then
  step "Dry run — printing the resolved plan; no docker build/run/push will execute."
  echo
  echo "Plan:"
  echo "  image:       $IMAGE"
  echo "  tags:        $(IFS=,; echo "${ALL_TAGS[*]}")"
  echo "  platforms:   $PLATFORMS"
  echo "  builder:     $BUILDER_DESC"
  echo "  build arg:   HERMES_VERSION=$TAG"
  echo "  gates:       $GATES_DESC"
  if [[ $NO_PUSH -eq 1 ]]; then
    echo "  push:        no (--no-push; local --load / classic build only)"
  else
    echo "  push:        yes"
  fi
  echo "  registry:    $REGISTRY_DESC"
  if [[ $NO_PUSH -eq 1 ]]; then
    echo "               (not used — --no-push never contacts a registry)"
  elif [[ $REG_IS_LOCAL -eq 1 ]]; then
    if [[ $ENSURE_REGISTRY -eq 1 ]]; then
      echo "               (would verify reachability and start '$LOCAL_REGISTRY_CONTAINER' if needed)"
    else
      echo "               (would fail if unreachable unless --ensure-registry is passed)"
    fi
  elif [[ -n "$REG_HOST" ]]; then
    echo "               (log in first: docker login $REG_HOST)"
  fi
  echo
  echo "Commands that would run:"
  print_cmd "${BUILD_CMD[@]}"
  if [[ "$BUILDER" == "classic" && $NO_PUSH -eq 0 ]]; then
    for _t in "${ALL_TAGS[@]}"; do
      print_cmd docker push "${IMAGE}:${_t}"
    done
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# Registry readiness before building/pushing
# ---------------------------------------------------------------------------

if [[ $NO_PUSH -eq 1 ]]; then
  if [[ $ENSURE_REGISTRY -eq 1 ]]; then
    step "--ensure-registry ignored: --no-push contacts no registry."
  fi
elif [[ $REG_IS_LOCAL -eq 1 ]]; then
  if [[ $ENSURE_REGISTRY -eq 1 ]]; then
    ensure_local_registry "$REG_HOST" "$REG_PORT" || die "could not bring up the local registry $REG_HOST:$REG_PORT"
  elif ! probe_registry "$REG_HOST" "$REG_PORT"; then
    err "error: local registry $REG_HOST:$REG_PORT is unreachable, refusing to push."
    err "Either:"
    err "  1. re-run with --ensure-registry to auto-start a registry:2 container, or"
    err "  2. start one manually:"
    err "     docker run -d --restart unless-stopped --name $LOCAL_REGISTRY_CONTAINER -p ${REG_PORT}:5000 registry:2"
    exit 1
  else
    step "Local registry $REG_HOST:$REG_PORT is reachable"
  fi
else
  if [[ $ENSURE_REGISTRY -eq 1 ]]; then
    step "--ensure-registry only applies to local registries (localhost/127.0.0.1/0.0.0.0); $REG_HOST is not local — skipping."
  fi
  if [[ -n "$REG_HOST" ]]; then
    step "Reminder: log in to $REG_HOST before the push if you have not (docker login $REG_HOST) — auth problems will surface at push time."
  else
    step "Reminder: log in to your registry before the push if you have not (docker login) — auth problems will surface at push time."
  fi
fi

# ---------------------------------------------------------------------------
# Build (and push)
# ---------------------------------------------------------------------------

step "Building ${IMAGE}:${TAG} (${PLATFORMS}) with the ${BUILDER_DESC} builder"
"${BUILD_CMD[@]}"

if [[ "$BUILDER" == "classic" && $NO_PUSH -eq 0 ]]; then
  for _t in "${ALL_TAGS[@]}"; do
    step "Pushing ${IMAGE}:${_t}"
    docker push "${IMAGE}:${_t}"
  done
fi

# ---------------------------------------------------------------------------
# Summary + next steps
# ---------------------------------------------------------------------------

step "Done."
echo
echo "Summary:"
if [[ $NO_PUSH -eq 1 ]]; then
  for _t in "${ALL_TAGS[@]}"; do
    echo "  built (not pushed): ${IMAGE}:${_t}"
  done
else
  for _t in "${ALL_TAGS[@]}"; do
    echo "  pushed: ${IMAGE}:${_t}"
  done
fi
INSPECT_LINE="$(docker image inspect --format '{{.Id}} {{.Size}}' "${IMAGE}:${TAG}" 2>/dev/null || true)"
if [[ -n "$INSPECT_LINE" ]]; then
  echo "  image id/size: ${INSPECT_LINE%% *} (${INSPECT_LINE##* } bytes)"
fi
echo
echo "Next steps:"
echo "  Run the image (loopback only):"
echo "    docker run -p 127.0.0.1:8787:8787 ${IMAGE}:${TAG}"
echo "  Exposing it beyond 127.0.0.1? Set a password first (e.g. -e HERMES_WEBUI_PASSWORD=...) — see docs/docker.md."
echo "  Compose: point the 'image:' field of docker-compose.yml at ${IMAGE}:${TAG}."
echo "  Sync to a remote registry later (do the remote login first: docker login <remote-registry>):"
echo "    docker pull ${IMAGE}:${TAG} && \\"
echo "      docker tag ${IMAGE}:${TAG} <remote-registry>/hermes-webui:${TAG} && \\"
echo "      docker push <remote-registry>/hermes-webui:${TAG}"
echo "  The same --image/--tag flags on this script retarget everything at the remote registry directly."
