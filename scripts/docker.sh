#!/usr/bin/env bash
# Compatibility helper; the standard Hilo stack uses LocalSandbox.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

detect_sandbox_mode() {
    local config_file="${HILO_CONFIG_PATH:-${DEER_FLOW_CONFIG_PATH:-$PROJECT_ROOT/config.yaml}}"
    local sandbox_use=""
    local provisioner_url=""

    if [ ! -f "$config_file" ]; then
        echo "local"
        return
    fi

    sandbox_use=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*use:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]*use:[[:space:]]*/, "", line)
            print line
            exit
        }
    ' "$config_file")

    provisioner_url=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*provisioner_url:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]*provisioner_url:[[:space:]]*/, "", line)
            print line
            exit
        }
    ' "$config_file")

    if [[ "$sandbox_use" == *"src.sandbox.local:LocalSandboxProvider"* ]]; then
        echo "local"
    elif [[ "$sandbox_use" == *"src.community.aio_sandbox:AioSandboxProvider"* ]]; then
        if [ -n "$provisioner_url" ]; then
            echo "provisioner"
        else
            echo "aio"
        fi
    else
        echo "local"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    action="${1:-help}"
    case "$action" in
        mode) detect_sandbox_mode ;;
        start) exec make -C "$PROJECT_ROOT" docker-start ;;
        stop) exec make -C "$PROJECT_ROOT" docker-stop ;;
        logs) exec make -C "$PROJECT_ROOT" docker-logs ;;
        *) echo "Usage: $0 {mode|start|stop|logs}"; exit 1 ;;
    esac
fi
