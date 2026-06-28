"""TradingAgents A股分析 — Streamlit Web UI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# .env location: APP_ROOT env var overrides project root (for Docker/Cython),
# otherwise fall back to directory two levels up from this file (development).
_DOTENV_PATH = Path(os.environ["APP_ROOT"]) / ".env" if "APP_ROOT" in os.environ else _PROJECT_ROOT / ".env"
load_dotenv(_DOTENV_PATH)


def _save_settings_to_env(settings: dict[str, str]) -> None:
    """Persist key=value pairs into the project .env file.

    Preserves existing entries, updates matching keys, appends new ones.
    Removes keys whose value is empty string.
    """
    lines: list[str] = []
    if _DOTENV_PATH.exists():
        with open(_DOTENV_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()

    # Keys to remove (empty value)
    keys_to_remove = {k for k, v in settings.items() if v == ""}

    # Update existing lines
    keys_written = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in keys_to_remove:
            continue  # skip (remove) this line
        if key in settings:
            new_lines.append(f"{key}={settings[key]}")
            keys_written.add(key)
        else:
            new_lines.append(line)

    # Append new keys (not removed, not already written)
    for key, value in settings.items():
        if key not in keys_written and key not in keys_to_remove:
            new_lines.append(f"{key}={value}")

    with open(_DOTENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")

from tradingagents.log_config import setup_logging  # noqa: E402
setup_logging()

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS  # noqa: E402
from tradingagents.license_service import license_service  # noqa: E402

from web.components.progress_panel import render_progress  # noqa: E402
from web.components.report_viewer import render_report  # noqa: E402
from web.components.sidebar import render_sidebar  # noqa: E402
from web.components.license import (  # noqa: E402
    render_license_banner,
    render_license_sidebar_badge,
    render_license_settings_section,
)
from web.history import extract_signal, load_analysis, delete_history  # noqa: E402

# Note: the background license monitor thread is started lazily by
# ``license_service.get_license_status()`` (via ``_ensure_monitor_running()``),
# which is called by the license UI helpers below. This means the monitor
# starts regardless of whether this plaintext ``app.py`` is intact —
# the compiled ``web/runner.py`` and ``tradingagents/graph/trading_graph.py``
# call ``require_license()`` → ``get_license_status()``, which starts the
# monitor even if an attacker strips the license UI from ``app.py``.
from web.progress import ProgressTracker  # noqa: E402
from web.runner import run_analysis_in_thread  # noqa: E402
from web.session_utils import clear_large_session_state  # noqa: E402

# ── LLM provider constants ──────────────────────────────────────────────────

_PROVIDERS: list[tuple[str, str]] = [
    ("DeepSeek", "deepseek"),
    ("通义千问 Qwen", "qwen"),
    ("MiniMax", "minimax"),
    ("智谱 GLM", "glm"),
    ("OpenAI", "openai"),
    ("Anthropic", "anthropic"),
    ("Google Gemini", "google"),
    ("Ollama（本地）", "ollama"),
]
_PROVIDER_DISPLAY = [name for name, _ in _PROVIDERS]
_PROVIDER_KEYS = [key for _, key in _PROVIDERS]

_PROVIDER_API_KEY_ENV: dict[str, str | None] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "ZHIPU_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "ollama": None,
    "openrouter": "OPENROUTER_API_KEY",
}

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TradingAgents-Astock A股分析",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');

    /* Hide Streamlit chrome for clean video recording.
       IMPORTANT: do NOT `display:none` the whole header OR the whole toolbar.
       In Streamlit >= 1.36 the "expand sidebar" button lives *inside* the
       toolbar (header > stToolbar > stExpandSidebarButton), so hiding either
       one makes a collapsed sidebar impossible to reopen (issue #36). Instead
       keep the header/toolbar in the DOM, make the header transparent, and
       hide only the individual chrome widgets we don't want on camera. */
    #MainMenu,
    footer,
    div[data-testid="stDecoration"],
    div[data-testid="stStatusWidget"],
    div[data-testid="stToolbarActions"],
    div[data-testid="stAppDeployButton"],
    span[data-testid="stMainMenu"] { display: none !important; }
    header[data-testid="stHeader"] {
        background: transparent !important;
        box-shadow: none !important;
    }
    /* Keep the sidebar collapse / expand controls always visible & clickable.
       Selector list spans multiple Streamlit versions. */
    button[data-testid="stExpandSidebarButton"],
    button[data-testid="stSidebarCollapseButton"],
    button[data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
    }

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, sans-serif;
    }
    .stApp {
        background: #0a0a0a;
    }
    section[data-testid="stSidebar"] {
        background: #0f0f0f;
        border-right: 1px solid #1a1a1a;
    }
    .stMetric label { color: #888 !important; font-size: 0.8rem !important; }
    .stMetric [data-testid="stMetricValue"] {
        color: #3b82f6 !important;
        font-weight: 700 !important;
    }
    .stProgress > div > div > div {
        background: linear-gradient(90deg, #3b82f6, #60a5fa) !important;
    }
    button[kind="primary"] {
        background: linear-gradient(135deg, #3b82f6, #60a5fa) !important;
        border: none !important;
        font-weight: 700 !important;
        letter-spacing: 0.05em !important;
        box-shadow: 0 4px 15px rgba(59,130,246,0.3) !important;
        transition: all 0.2s ease !important;
    }
    button[kind="primary"]:hover {
        background: linear-gradient(135deg, #2563eb, #3b82f6) !important;
        box-shadow: 0 6px 20px rgba(59,130,246,0.4) !important;
        transform: translateY(-1px) !important;
    }
    /* Secondary buttons (history items) */
    button[kind="secondary"] {
        background: #161616 !important;
        border: 1px solid #2a2a2a !important;
        color: #ccc !important;
        transition: all 0.2s ease !important;
    }
    button[kind="secondary"]:hover {
        background: #1e1e1e !important;
        border-color: #3b82f6 !important;
        color: #3b82f6 !important;
    }
    .stExpander {
        border: 1px solid #222 !important;
        border-radius: 8px !important;
    }
    .stTabs [data-baseweb="tab"] {
        color: #888 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #3b82f6 !important;
        border-bottom-color: #3b82f6 !important;
    }
    div[data-testid="stDownloadButton"] button {
        background: #1a1a2e !important;
        border: 1px solid #3b82f6 !important;
        color: #3b82f6 !important;
    }
    /* Text input styling */
    input[data-testid="stTextInputRootElement"] input,
    .stTextInput input {
        background: #161616 !important;
        border-color: #2a2a2a !important;
        color: #f5f1eb !important;
    }
    .stTextInput input:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 1px #3b82f6 !important;
    }
    /* Date input styling */
    .stDateInput input {
        background: #161616 !important;
        border-color: #2a2a2a !important;
        color: #f5f1eb !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Build config ─────────────────────────────────────────────────────────────

def _catalog_values_for(provider_key: str, mode: str) -> list[str]:
    """Return the list of model id values for a provider+mode, or [] if absent."""
    if provider_key not in MODEL_OPTIONS:
        return []
    return [value for _, value in MODEL_OPTIONS[provider_key].get(mode, [])]


def _find_option_index(values: list[str], target: str) -> int | None:
    """Return index of target in values, or None if not present."""
    try:
        return values.index(target)
    except ValueError:
        return None


def _find_custom_index(provider_key: str, mode: str) -> int | None:
    """Return the index of the "custom" pseudo-option, or None if absent."""
    return _find_option_index(_catalog_values_for(provider_key, mode), "custom")


def _resolve_env_model(env_value: str, provider_key: str, mode: str, custom_key: str) -> None:
    """If env_value is a non-catalog model, pre-populate the custom text input key.

    Called once at session init so the settings dialog displays the user's
    .env-defined custom model name instead of silently falling back to the
    first catalog option.
    """
    if not env_value:
        return
    values = _catalog_values_for(provider_key, mode)
    if _find_option_index(values, env_value) is not None:
        return  # Known model — nothing to pre-populate
    st.session_state.setdefault(custom_key, env_value)


def _init_session_from_env() -> None:
    """Load persisted settings from .env into session_state on first run."""
    if st.session_state.get("_env_loaded"):
        return
    provider = os.getenv("LLM_PROVIDER", "")
    if provider:
        st.session_state.setdefault("llm_provider", provider)
    quick = os.getenv("QUICK_THINK_LLM", "")
    if quick:
        st.session_state.setdefault("quick_think_llm", quick)
    deep = os.getenv("DEEP_THINK_LLM", "")
    if deep:
        st.session_state.setdefault("deep_think_llm", deep)
    base_url = os.getenv("BACKEND_URL", "")
    if base_url:
        st.session_state.setdefault("llm_base_url", base_url)
    # If the .env model is not in the catalog, surface it as a custom model
    # so the settings dialog shows the actual value rather than a silent fallback.
    _resolve_env_model(quick, provider, "quick", "settings_custom_quick_model")
    _resolve_env_model(deep, provider, "deep", "settings_custom_deep_model")
    st.session_state["_env_loaded"] = True

_init_session_from_env()


def _build_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = st.session_state.get("llm_provider", "minimax")

    quick = st.session_state.get("quick_think_llm", "MiniMax-M2.7-highspeed")
    if quick == "custom":
        quick = st.session_state.get("settings_custom_quick_model", "") or quick
    config["quick_think_llm"] = quick

    deep = st.session_state.get("deep_think_llm", "MiniMax-M2.7")
    if deep == "custom":
        deep = st.session_state.get("settings_custom_deep_model", "") or deep
    config["deep_think_llm"] = deep

    # Optional third-party / proxy endpoint. Settings input wins, else .env BACKEND_URL.
    backend_url = (st.session_state.get("llm_base_url") or os.getenv("BACKEND_URL") or "").strip()
    config["backend_url"] = backend_url or None
    config["data_vendors"] = {
        "core_stock_apis": "a_stock",
        "technical_indicators": "a_stock",
        "fundamental_data": "a_stock",
        "news_data": "a_stock",
        "signal_data": "a_stock",
    }
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["output_language"] = "Chinese"
    return config


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    render_sidebar()


# ── Settings dialog ─────────────────────────────────────────────────────────

@st.dialog("⚙️ 系统设置", width="small")
def _settings_dialog() -> None:
    """Modal dialog with two tabs: LLM settings and license management."""

    tab_llm, tab_license = st.tabs(["🤖 LLM 设置", "🔐 授权管理"])

    # ─────────────────────────────────────────────────────────────────────
    # Tab 1: LLM Settings
    # ─────────────────────────────────────────────────────────────────────
    with tab_llm:
        # ── Provider selection ───────────────────────────────────────────
        current_provider = st.session_state.get("llm_provider", "minimax")
        try:
            provider_default = _PROVIDER_KEYS.index(current_provider)
        except ValueError:
            provider_default = 0

        provider_idx = st.selectbox(
            "LLM 供应商",
            range(len(_PROVIDERS)),
            format_func=lambda i: _PROVIDER_DISPLAY[i],
            index=provider_default,
            key="settings_provider_idx",
        )
        provider_key = _PROVIDER_KEYS[provider_idx]
        st.session_state["llm_provider"] = provider_key

        # ── API Key ──────────────────────────────────────────────────────
        api_key_env = _PROVIDER_API_KEY_ENV.get(provider_key)
        if api_key_env:
            current_key = os.environ.get(api_key_env, "")
            if current_key:
                st.info(f"✅ `{api_key_env}` 已配置（来自 .env 或环境变量）")
            else:
                st.warning(f"⚠️ 未检测到 `{api_key_env}`，请在下方输入或配置 .env 文件")

            new_key = st.text_input(
                f"设置 {api_key_env}",
                type="password",
                placeholder="输入新的 API Key（留空保持不变）",
                key=f"settings_api_key_{provider_key}",
            )
            if new_key:
                os.environ[api_key_env] = new_key
                _save_settings_to_env({api_key_env: new_key})
                st.success(f"✅ `{api_key_env}` 已更新并保存到 .env")

        st.markdown("---")

        # ── Model selection ──────────────────────────────────────────────
        if provider_key in MODEL_OPTIONS:
            quick_options = MODEL_OPTIONS[provider_key]["quick"]
            deep_options = MODEL_OPTIONS[provider_key]["deep"]

            quick_labels = [label for label, _ in quick_options]
            quick_values = [value for _, value in quick_options]
            deep_labels = [label for label, _ in deep_options]
            deep_values = [value for _, value in deep_options]
            custom_quick_idx = _find_custom_index(provider_key, "quick")
            custom_deep_idx = _find_custom_index(provider_key, "deep")

            # Quick model
            current_quick = st.session_state.get("quick_think_llm", quick_values[0])
            if _find_option_index(quick_values, current_quick) is not None:
                quick_default = quick_values.index(current_quick)
            elif custom_quick_idx is not None:
                # .env value is a custom (non-catalog) model — select the "Custom" entry
                # and pre-populate the text input with the .env value.
                quick_default = custom_quick_idx
                st.session_state.setdefault("settings_custom_quick_model", current_quick)
            else:
                quick_default = 0

            quick_idx = st.selectbox(
                "快速思考模型",
                range(len(quick_options)),
                format_func=lambda i: quick_labels[i],
                index=quick_default,
                key="settings_quick_model_idx",
                help="用于常规分析任务，速度优先",
            )
            selected_quick = quick_values[quick_idx]
            if selected_quick == "custom":
                selected_quick = st.text_input(
                    "自定义快速思考模型 ID",
                    value=st.session_state.get("settings_custom_quick_model", ""),
                    key="settings_custom_quick_model",
                    placeholder="输入模型名称，如 qwen-turbo",
                )
            st.session_state["quick_think_llm"] = selected_quick

            # Deep model
            current_deep = st.session_state.get("deep_think_llm", deep_values[0])
            if _find_option_index(deep_values, current_deep) is not None:
                deep_default = deep_values.index(current_deep)
            elif custom_deep_idx is not None:
                deep_default = custom_deep_idx
                st.session_state.setdefault("settings_custom_deep_model", current_deep)
            else:
                deep_default = 0

            deep_idx = st.selectbox(
                "深度思考模型",
                range(len(deep_options)),
                format_func=lambda i: deep_labels[i],
                index=deep_default,
                key="settings_deep_model_idx",
                help="用于辩论/决策等需要深度推理的任务",
            )
            selected_deep = deep_values[deep_idx]
            if selected_deep == "custom":
                selected_deep = st.text_input(
                    "自定义深度思考模型 ID",
                    value=st.session_state.get("settings_custom_deep_model", ""),
                    key="settings_custom_deep_model",
                    placeholder="输入模型名称，如 qwen-max",
                )
            st.session_state["deep_think_llm"] = selected_deep
        else:
            # Provider not in catalog — free-form model input
            custom_quick = st.text_input(
                "快速思考模型 ID",
                value=st.session_state.get("quick_think_llm", ""),
                key="settings_custom_quick_model_fallback",
            )
            custom_deep = st.text_input(
                "深度思考模型 ID",
                value=st.session_state.get("deep_think_llm", ""),
                key="settings_custom_deep_model_fallback",
            )
            st.session_state["quick_think_llm"] = custom_quick
            st.session_state["deep_think_llm"] = custom_deep

        st.markdown("---")

        # ── Backend URL ─────────────────────────────────────────────────
        st.text_input(
            "API Base URL（第三方/代理，可选）",
            value=st.session_state.get("llm_base_url", ""),
            key="settings_base_url",
            placeholder="例: https://your-proxy.com/v1",
            help="通过第三方中转/代理访问模型时填写网关地址；留空则用官方地址。",
        )
        st.session_state["llm_base_url"] = st.session_state.get("settings_base_url", "")

        # ── Save all settings to .env ───────────────────────────────────
        if st.button("💾 保存设置", use_container_width=True, type="primary"):
            env_updates: dict[str, str] = {}
            env_updates["LLM_PROVIDER"] = st.session_state.get("llm_provider", "minimax")
            env_updates["QUICK_THINK_LLM"] = st.session_state.get("quick_think_llm", "")
            env_updates["DEEP_THINK_LLM"] = st.session_state.get("deep_think_llm", "")
            base_url = st.session_state.get("llm_base_url", "")
            if base_url:
                env_updates["BACKEND_URL"] = base_url
            else:
                # If user cleared the base URL, remove it from .env
                env_updates["BACKEND_URL"] = ""
            _save_settings_to_env(env_updates)
            st.success("✅ 所有设置已保存到 .env 文件")

    # ─────────────────────────────────────────────────────────────────────
    # Tab 2: License Management
    # ─────────────────────────────────────────────────────────────────────
    with tab_license:
        render_license_settings_section()


# ── Top bar: license banner + settings ───────────────────────────────────────

# Periodic UI refresh: drop the cached status, reload from the service
# (which the background monitor thread keeps in sync with disk), and trigger
# a full page rerun if the status actually changed. Runs at most every hour
# while the page is open in a browser.
@st.fragment(run_every="1h")
def _license_auto_refresh():
    previous = st.session_state.get("_license_status", {}).get("status")
    # Force a reload in case the monitor thread reloaded the cert
    license_service.ensure_loaded()
    st.session_state.pop("_license_status", None)
    new_status = license_service.get_license_status()
    st.session_state["_license_status"] = new_status
    if previous is not None and new_status.get("status") != previous:
        st.rerun()

_license_auto_refresh()

render_license_banner()

_top_col1, _top_col2 = st.columns([10, 1])
with _top_col1:
    st.markdown(
        '<div style="text-align:center; color:#cc7700; font-size:0.85rem; padding:0.3rem 0;">'
        ' '
        '</div>',
        unsafe_allow_html=True,
    )
with _top_col2:
    if st.button("⚙️ 设置", key="open_settings_btn", use_container_width=True):
        _settings_dialog()


# ── Handle "Start Analysis" trigger ──────────────────────────────────────────

# Keep only the minimal interactive state for the current run. Large cached PDF
# bytes and full report payloads are pruned so repeated history view / report
# navigation does not accumulate memory indefinitely.
clear_large_session_state(st.session_state)

start_req = st.session_state.pop("start_analysis", None)
if start_req:
    # Clear previous analysis state
    st.session_state.pop("tracker", None)
    st.session_state.pop("viewing_history", None)

    tracker = ProgressTracker(
        ticker=start_req["ticker"],
        trade_date=start_req["trade_date"],
    )
    st.session_state["tracker"] = tracker
    try:
        run_analysis_in_thread(
            ticker=start_req["ticker"],
            trade_date=start_req["trade_date"],
            config=_build_config(),
            tracker=tracker,
        )
    except Exception as exc:
        # LicenseError (or any other startup error) — surface to the user
        # and drop the half-created tracker so the UI doesn't show "running".
        st.session_state.pop("tracker", None)
        st.error(f"❌ {exc}")


# ── Main area state machine ─────────────────────────────────────────────────

tracker: ProgressTracker | None = st.session_state.get("tracker")
viewing_history: str | None = st.session_state.get("viewing_history")

# State 1: Viewing a historical analysis
if viewing_history:
    try:
        state = load_analysis(viewing_history)
        signal = extract_signal(state)
        ticker = Path(viewing_history).parent.parent.name
        trade_date = Path(viewing_history).stem.replace("full_states_log_", "")
        render_report(state, ticker, trade_date, signal)
    except Exception as exc:
        st.error(f"加载失败: {exc}")

# State 2: Analysis running
elif tracker and tracker.is_running:
    # Use @st.fragment(run_every=...) for auto-refresh instead of
    # time.sleep + st.rerun().  The old sleep+rerun pattern breaks in
    # Docker when WebSocket connections are unstable — the rerun signal
    # never reaches the browser, so the stop button becomes unresponsive.
    # A fragment only re-renders its own subtree, keeping the rest of the
    # page (including button click handlers) fully interactive.
    @st.fragment(run_every="2s")
    def _live_progress():
        t = st.session_state.get("tracker")
        if t is None or not t.is_running:
            # Analysis finished or cancelled while fragment was sleeping —
            # trigger a full rerun so the state machine transitions.
            st.rerun()
        if st.session_state.get("stop_analysis_btn"):
            t.cancel()
            st.session_state.pop("tracker", None)
            st.rerun()
        render_progress(t)

    _live_progress()

# State 3: Analysis complete
elif tracker and tracker.is_complete:
    render_report(
        tracker.final_state,
        tracker.ticker,
        tracker.trade_date,
        tracker.signal,
        elapsed=tracker.elapsed,
    )

# State 4: Analysis errored
elif tracker and tracker.error:
    st.error(f"分析失败: {tracker.error}")
    if st.button("重试"):
        st.session_state.pop("tracker", None)
        st.rerun()

# State 5: Analysis cancelled
elif tracker and tracker.is_cancelled:
    st.warning("⏹ 分析已停止")
    if st.button("新建分析"):
        st.session_state.pop("tracker", None)
        st.rerun()

# State 0: Idle — welcome screen
else:
    st.markdown(
        """
        <div style="
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 60vh;
            text-align: center;
        ">
            <div style="font-size: 4rem; margin-bottom: 1rem;">📈</div>
            <div style="
                font-size: 2.5rem;
                font-weight: 900;
                margin-bottom: 0.5rem;
            ">
                <span <span style="color: #f5f1eb;">AI TradingAgents</span>
            </div>
            <div style="color: #888; font-size: 1.1rem; max-width: 500px; line-height: 1.6;">
                AI Agent投研分析系统<br>
            </div>
            <div style="
                margin-top: 2rem;
                padding: 1rem 2rem;
                border: 1px solid #222;
                border-radius: 12px;
                color: #666;
                font-size: 0.9rem;
            ">
                ← 在左侧输入股票代码，开始分析
            </div>
            <div style="
                margin-top: 2.5rem;
                padding: 0.8rem 1.5rem;
                color: #555;
                font-size: 0.75rem;
                max-width: 500px;
                line-height: 1.6;
                border-top: 1px solid #1a1a1a;
            ">
                ⚠️ 本项目仅供学习研究与技术演示，不构成任何投资建议。<br>
                投资决策请咨询持牌专业机构。作者不对使用本工具产生的任何损失承担责任。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
