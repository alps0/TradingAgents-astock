"""Sidebar: stock input and history list."""

from __future__ import annotations

from datetime import date

import streamlit as st

from web.components.license import render_license_sidebar_badge
from web.history import delete_history, get_history


def _resolve_user_input(raw: str) -> tuple[str, str | None]:
    """Resolve raw user input to (ticker_code, error_msg).

    Accepts 6-digit codes or Chinese stock names (e.g. '宝光股份').
    Returns (code, None) on success or ("", error_msg) on failure.
    """
    from tradingagents.dataflows.a_stock import resolve_ticker

    try:
        code = resolve_ticker(raw)
        return code, None
    except ValueError as e:
        return "", str(e)


def render_sidebar() -> None:
    """Render the sidebar with input controls and history."""

    st.markdown(
        """
        <div style="text-align:center; margin-bottom:1.5rem;">
            <span style="font-size:2rem; font-weight:800; color:#f5f1eb;">AI TradingAgents</span>
            <div style="font-size:0.85rem; color:#888; margin-top:0.2rem;">
                AI Agent投研系统
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # License status badge under the title
    render_license_sidebar_badge()

    st.markdown("---")
    st.markdown("#### 新建分析")

    ticker = st.text_input(
        "股票代码",
        placeholder="例: 600001",
        key="input_ticker",
        help="输入6位A股代码",
    )

    trade_date = st.date_input(
        "分析日期",
        value=date.today(),
        key="input_date",
    )

    tracker = st.session_state.get("tracker")
    is_busy = tracker is not None and tracker.is_running

    # License enforcement: block new analysis when unlicensed.
    license_status = st.session_state.get("_license_status", {})
    is_licensed = bool(license_status.get("is_licensed"))

    if st.button(
        "开始分析" if not is_busy else "分析进行中...",
        use_container_width=True,
        disabled=is_busy or not ticker or not is_licensed,
        type="primary",
        help=None if is_licensed else "未授权 — 请在「设置 → 软件授权」中导入授权证书",
    ):
        resolved_code, err = _resolve_user_input(ticker)
        if err:
            st.error(f"❌ {err}")
        else:
            if resolved_code != ticker.strip():
                st.success(f"✅ {ticker.strip()} → {resolved_code}")
            st.session_state["start_analysis"] = {
                "ticker": resolved_code,
                "trade_date": trade_date.strftime("%Y-%m-%d"),
            }
            st.session_state["viewing_history"] = None

    st.markdown("---")
    st.markdown("#### 历史记录")

    history = get_history()
    if not history:
        st.caption("暂无历史记录")
        return

    for i, entry in enumerate(history[:20]):
        t, d = entry["ticker"], entry["date"]
        label = f"{t}  ·  {d}"
        col_btn, col_del = st.columns([5, 1])
        with col_btn:
            if st.button(label, key=f"hist_{t}_{d}", use_container_width=True):
                st.session_state["viewing_history"] = entry["path"]
                st.session_state["start_analysis"] = None
        with col_del:
            if st.button("🗑️", key=f"del_{t}_{d}", help="删除此记录"):
                if delete_history(entry["path"]):
                    st.session_state.pop("viewing_history", None)
                    st.rerun()
                else:
                    st.error("删除失败")

    st.markdown("---")
    st.caption("⚠️ 仅供学习研究，不构成投资建议")
