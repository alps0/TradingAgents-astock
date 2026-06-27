#!/bin/sh
set -eu

APP_HOME="${HOME:-/home/appuser}"
APP_ROOT="${APP_ROOT:-/home/appuser/app}"

mkdir -p "$APP_HOME/.tradingagents/cache" "$APP_HOME/.tradingagents/logs" "$APP_HOME/.tradingagents/memory" "$APP_HOME/.streamlit" "$APP_ROOT"
chown -R appuser:appuser "$APP_HOME" "$APP_ROOT" 2>/dev/null || true
chmod -R u+rwX "$APP_HOME" "$APP_ROOT" 2>/dev/null || true

exec su -s /bin/sh appuser -c "cd $APP_ROOT && tradingagents-web"
