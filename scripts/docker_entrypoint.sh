#!/bin/sh
set -eu

APP_HOME="${HOME:-/home/appuser}"
APP_ROOT="${APP_ROOT:-/home/appuser/app}"

# Diagnostic logging (off by default). Set DEBUG=1 to see machine-id status.
if [ "${DEBUG:-0}" = "1" ]; then
    if [ -s /etc/machine-id ]; then
        echo "[entrypoint-diag] /etc/machine-id present: $(cat /etc/machine-id)"
    else
        echo "[entrypoint-diag] WARNING: /etc/machine-id missing or empty"
    fi
fi

mkdir -p "$APP_HOME/.tradingagents/cache" "$APP_HOME/.tradingagents/logs" "$APP_HOME/.tradingagents/memory" "$APP_HOME/.streamlit" "$APP_ROOT"
chown -R appuser:appuser "$APP_HOME" "$APP_ROOT" 2>/dev/null || true
chmod -R u+rwX "$APP_HOME" "$APP_ROOT" 2>/dev/null || true

if [ "${DEBUG:-0}" = "1" ]; then
    if [ -f "$APP_HOME/.tradingagents/machine_id" ]; then
        echo "[entrypoint-diag] volume machine_id file exists: $(cat "$APP_HOME/.tradingagents/machine_id" 2>/dev/null | head -c 200)"
    else
        echo "[entrypoint-diag] volume machine_id file does NOT exist (first run or volume was wiped)"
    fi
fi

exec su -s /bin/sh appuser -c "cd $APP_ROOT && tradingagents-web"
