#!/usr/bin/env bash
# Rebuild this checkout's distributions and refresh the validation-only deployment beside it.
#
# The mini installs from its own wheelhouse, and pip treats an installed distribution at the same version as already
# satisfied -- so every run force-reinstalls the three names rather than trusting "already installed". The live
# dashboard owns port 5000: this script never uses it, and --smoke picks a free port of its own.
#
#   scripts/build_mini.sh            # build, copy the wheels and force-reinstall
#   scripts/build_mini.sh --smoke    # ...and prove the mini answers on a throwaway port
set -euo pipefail

REPO="${REPO:-/mnt/data/wee/detergent-md-gui}"
MINI="${MINI:-/mnt/data/wee/detergent-gui-mini}"
LIVE_PORT=5000

smoke=false
for arg in "$@"; do
    case "$arg" in
        --smoke) smoke=true ;;
        -h|--help) printf 'usage: %s [--smoke]\n' "$0"; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

for executable in "$REPO/.venv/bin/pip" "$MINI/.venv/bin/pip"; do
    if [[ ! -x "$executable" ]]; then
        printf 'missing %s\n' "$executable" >&2
        exit 1
    fi
done

printf 'building wheels from %s\n' "$REPO"
rm -rf "$REPO/dist"
(
    cd "$REPO"
    .venv/bin/pip wheel packages/core packages/validation packages/pdc . \
        -w dist --no-deps --no-build-isolation
)

printf 'refreshing %s/dist\n' "$MINI"
# The wheelhouse is mirrored, not accumulated: pip picks the highest version it finds, so a leftover wheel of a
# newer version would silently win over the one just built.
rm -f "$MINI/dist"/detergent_*.whl
cp "$REPO"/dist/*.whl "$MINI/dist/"

# By name, from the mini's own wheelhouse: a same-version install is otherwise skipped as already satisfied.
"$MINI/.venv/bin/pip" install --force-reinstall --no-deps --find-links "$MINI/dist" \
    detergent-core detergent-validation detergent-md-gui

if [[ "$smoke" == true ]]; then
    if ! command -v curl >/dev/null 2>&1; then
        printf 'curl is required for --smoke\n' >&2
        exit 1
    fi
    port="$("$MINI/.venv/bin/python" - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(('127.0.0.1', 0))
    print(sock.getsockname()[1])
PY
)"
    if [[ "$port" == "$LIVE_PORT" ]]; then
        printf 'refusing to smoke-test on port %s: the live dashboard owns it\n' "$LIVE_PORT" >&2
        exit 1
    fi
    log="$(mktemp)"
    pid=''
    cleanup() {
        if [[ -n "$pid" ]]; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
        rm -f "$log"
    }
    trap cleanup EXIT
    printf 'starting the mini on port %s\n' "$port"
    DASHBOARD_PORT="$port" "$MINI/run.sh" >"$log" 2>&1 &
    pid=$!
    ready=''
    for _ in $(seq 1 120); do
        if curl --silent --output /dev/null --max-time 1 "http://127.0.0.1:$port/"; then
            ready=1
            break
        fi
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.25
    done
    if [[ -z "$ready" ]]; then
        printf 'the mini did not start on port %s; log follows\n' "$port" >&2
        cat "$log" >&2
        exit 1
    fi
    expect() {
        local path="$1" want="$2" got
        got="$(curl --silent --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:$port$path")" || {
            printf 'GET %s failed\n' "$path" >&2
            exit 1
        }
        if [[ "$got" != "$want" ]]; then
            printf 'GET %s: expected %s, got %s\n' "$path" "$want" "$got" >&2
            exit 1
        fi
        printf 'GET %s -> %s\n' "$path" "$got"
    }
    expect / 200
    expect /detergent-validation/runs 200
    expect /protein-detergent/runs 404
    printf 'smoke passed\n'
fi
