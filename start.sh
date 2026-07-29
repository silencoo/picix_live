#!/usr/bin/env sh

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd "$SCRIPT_DIR" || exit 1

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        return 0
    fi

    echo "[ERROR] uv was not found." >&2
    echo "Install it from: https://docs.astral.sh/uv/getting-started/installation/" >&2
    return 1
}

run_uv() {
    if [ -f ".env" ]; then
        uv run --locked --env-file .env "$@"
    else
        uv run --locked "$@"
    fi
}

show_usage() {
    echo "Usage: ./start.sh [bot|status|unlock|plan|optimize|token|sync|help]"
}

run_action() {
    case "$1" in
        help)
            show_usage
            return 0
            ;;
        bot|status|unlock|plan|optimize|token|sync)
            ;;
        *)
            echo "[ERROR] Unknown action: $1" >&2
            show_usage >&2
            return 2
            ;;
    esac

    if ! ensure_uv; then
        return 1
    fi

    case "$1" in
        bot)
            echo
            echo "Starting Telegram Bot..."
            run_uv python -u -m picix_bot
            ;;
        status)
            echo
            echo "Loading Picix status..."
            run_uv python auto_unlock_helper.py status
            ;;
        unlock)
            echo
            echo "Running daily unlock..."
            run_uv python auto_unlock_helper.py unlock
            ;;
        plan)
            echo
            echo "Calculating points optimization plan..."
            run_uv python auto_unlock_helper.py plan
            ;;
        optimize)
            echo
            echo "Running points optimization..."
            run_uv python auto_unlock_helper.py optimize
            ;;
        token)
            echo
            echo "Checking Picix authorization..."
            run_uv python check_token_expiry.py
            ;;
        sync)
            echo
            echo "Syncing dependencies from uv.lock..."
            uv sync --locked
            ;;
    esac
}

ACTION=${1:-}
if [ -n "$ACTION" ]; then
    run_action "$ACTION"
    exit $?
fi

while :; do
    if [ -t 1 ] && command -v clear >/dev/null 2>&1; then
        clear
    fi

    echo "=========================================="
    echo "             Picix Control Center"
    echo "=========================================="
    echo
    echo "  1. Start Telegram Bot"
    echo "  2. Show Picix Status"
    echo "  3. Run Daily Unlock"
    echo "  4. Show Points Optimization Plan"
    echo "  5. Run Points Optimization"
    echo "  6. Check Authorization"
    echo "  7. Sync Locked Dependencies"
    echo "  0. Exit"
    echo
    if [ -f ".env" ]; then
        echo "  Environment: .env loaded"
    else
        echo "  Environment: .env not found"
    fi
    echo
    printf "Select [1-7,0]: "

    if ! IFS= read -r CHOICE; then
        exit 0
    fi

    case "$CHOICE" in
        1) ACTION=bot ;;
        2) ACTION=status ;;
        3) ACTION=unlock ;;
        4) ACTION=plan ;;
        5) ACTION=optimize ;;
        6) ACTION=token ;;
        7) ACTION=sync ;;
        0) exit 0 ;;
        *)
            echo "Invalid selection."
            sleep 1
            continue
            ;;
    esac

    run_action "$ACTION"
    RESULT=$?
    echo
    echo "Command finished with exit code $RESULT."
    printf "Press Enter to return to the menu..."
    IFS= read -r _ || exit "$RESULT"
done
