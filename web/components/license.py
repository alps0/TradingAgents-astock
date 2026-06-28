"""License UI helpers for the Streamlit web app.

Provides:
- ``render_license_banner()`` — top-of-page alert when license is invalid / expiring
- ``render_license_sidebar_badge()`` — compact status indicator for the sidebar
- ``render_license_settings_section()`` — full management UI (status table,
  fingerprint display/export, certificate upload) for use inside the settings
  dialog
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from tradingagents.license_service import license_service


_STATUS_LABEL: dict[str, str] = {
    "valid": "已授权",
    "expiring_soon": "即将到期",
    "expired": "已过期",
    "unlicensed": "未授权",
    "grace_period": "宽限期",
    "invalid_signature": "签名无效",
    "fingerprint_mismatch": "指纹不匹配",
}


def _get_status() -> dict[str, Any]:
    """Load license status into ``st.session_state`` if not already cached.

    Uses a flag to avoid re-querying on every rerun within the same session.
    A refresh can be forced via ``st.session_state.pop("_license_status", None)``.
    """
    if "_license_status" not in st.session_state:
        license_service.ensure_loaded()
        st.session_state["_license_status"] = license_service.get_license_status()
    return st.session_state["_license_status"]


def _refresh_status() -> None:
    st.session_state.pop("_license_status", None)


def render_license_banner() -> None:
    """Render an alert banner at the top of the page when license is not OK."""
    status = _get_status()
    current = status.get("status", "unlicensed")

    if status.get("is_licensed") and current == "valid":
        return

    if current == "expired":
        st.error(
            "🚫 **授权已过期** — 系统授权已过期，请导入新的授权证书以恢复使用。"
        )
    elif current == "expiring_soon":
        days = status.get("days_remaining", 0)
        st.warning(
            f"⚠️ **授权即将到期** — 剩余 {days} 天，请及时联系供应商续期。"
        )
    elif current == "unlicensed":
        st.warning(
            "🔒 **系统未授权** — 请在「设置 → 软件授权」中导入授权证书以解锁分析功能。"
        )
    elif current == "grace_period":
        st.warning(
            "⏳ **硬件变更宽限期** — 检测到硬件变更，请在宽限期内重新导入有效授权证书。"
        )
    elif current == "invalid_signature":
        st.error(
            "🚫 **授权签名无效** — 证书可能被篡改，请重新导入有效的授权证书。"
        )
    elif current == "fingerprint_mismatch":
        st.error(
            "🚫 **硬件指纹不匹配** — 证书与当前硬件不匹配，请重新申请授权。"
        )


def render_license_sidebar_badge() -> None:
    """Render a compact license status badge in the sidebar."""
    status = _get_status()
    current = status.get("status", "unlicensed")

    color = {
        "valid": "#22c55e",
        "expiring_soon": "#f59e0b",
        "expired": "#ef4444",
        "unlicensed": "#ef4444",
        "grace_period": "#f59e0b",
        "invalid_signature": "#ef4444",
        "fingerprint_mismatch": "#ef4444",
    }.get(current, "#888888")

    label = _STATUS_LABEL.get(current, current)
    license_type = status.get("license_type") or "-"

    st.markdown(
        f"""
        <div style="
            margin-top: 0.5rem;
            padding: 0.4rem 0.6rem;
            border: 1px solid {color}33;
            border-radius: 6px;
            background: {color}11;
            font-size: 0.75rem;
            color: #aaa;
        ">
            <span style="color:{color}; font-weight:700;">● {label}</span>
            <span style="float:right; color:#666;">{license_type}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_license_settings_section() -> None:
    """Render the license management section.

    Designed to be embedded inside the existing ``_settings_dialog`` modal:
    shows the current status, hardware fingerprint (with export), and a file
    uploader for importing a new license certificate.
    """
    status = _get_status()

    st.markdown("### 🔐 软件授权")

    current = status.get("status", "unlicensed")
    label = _STATUS_LABEL.get(current, current)

    # ── Status table ────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.metric("授权状态", label)
        st.caption(f"类型: {status.get('license_type') or '-'}")
    with col2:
        days = status.get("days_remaining")
        if days is not None:
            st.metric("剩余天数", f"{days} 天")
        else:
            st.metric("剩余天数", "-")
        expires_at = status.get("expires_at")
        if expires_at:
            try:
                dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                st.caption(f"到期: {dt.strftime('%Y-%m-%d')}")
            except Exception:
                st.caption(f"到期: {expires_at}")
        else:
            st.caption("到期: -")

    if status.get("customer_name"):
        st.caption(f"客户: {status['customer_name']}")
    if status.get("issuer"):
        st.caption(f"签发方: {status['issuer']}")

    # ── Hardware fingerprint ─────────────────────────────────────────────
    st.markdown("#### 硬件指纹")
    fp = status.get("fingerprint", "")
    st.code(fp, language="text")

    fp_data = {
        "fingerprint": fp,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hostname": license_service.get_hardware_info().get("hostname", ""),
    }

    col_export, col_copy = st.columns([3, 1])
    with col_export:
        st.download_button(
            label="📥 导出指纹文件",
            data=json.dumps(fp_data, indent=2, ensure_ascii=False),
            file_name="fingerprint.json",
            mime="application/json",
            use_container_width=True,
            help="将此指纹文件发送给供应商以申请授权证书",
        )
    with col_copy:
        # Streamlit doesn't have a native copy button; use a tooltip-only fallback.
        st.caption("（复制上方文本）")

    st.markdown("#### 导入授权证书")
    uploaded = st.file_uploader(
        "选择授权证书文件 (.json)",
        type=["json"],
        key="license_uploader",
        help="请选择供应商签发的 .json 授权证书文件",
    )
    if uploaded is not None:
        try:
            content = uploaded.read()
            saved_path = license_service.import_license_bytes(
                content, filename=uploaded.name or "license.json"
            )
            _refresh_status()
            st.success(
                f"✅ 授权证书导入成功\n\n已保存到：`{saved_path}`"
            )
            st.rerun()
        except ValueError as exc:
            st.error(f"❌ 导入失败：{exc}")
        except Exception as exc:
            st.error(f"❌ 导入失败：{exc}")
