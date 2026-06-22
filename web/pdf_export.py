"""Generate PDF reports from analysis results using fpdf2."""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import fpdf as _fpdf_mod
from fpdf import FPDF

logger = logging.getLogger(__name__)

# Project-root bundled font (Noto Sans SC variable TTF — Simplified Chinese).
# Must use TTF (TrueType outline), NOT OTF (CFF outline): fpdf2 embeds TTF
# as CIDFontType2 which renders correctly in all PDF viewers, whereas CFF-based
# OTF is embedded as CIDFontType0 which causes garbled text in many viewers.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BUNDLED_FONT_TTF = _PROJECT_ROOT / "NotoSansSC[wght].ttf"
_BUNDLED_FONT_VF_TTF = _PROJECT_ROOT / "NotoSansCJKsc-VF.ttf"

# Cache directory for pre-instantiated variable fonts.
# Use user-writable location: XDG_CACHE_HOME or ~/.cache, not project root
# (which may be read-only in Docker/installed environments).
def _get_font_cache_dir() -> Path:
    """Return a writable directory for caching instantiated fonts."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".cache"
    cache_dir = base / "tradingagents" / "fonts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# fpdf2 (maintained fork) and the abandoned pyfpdf 1.x BOTH import as `fpdf`, and
# installing both leaves whichever was installed last on disk. pyfpdf 1.x encodes
# every page as latin-1, so any Chinese character raises a cryptic
# `UnicodeEncodeError: 'latin-1' codec can't encode` deep inside the library
# (issue #54). Detect the wrong library up front and tell the user exactly how to
# fix it, instead of letting the PDF blow up mid-render.
_FPDF_VERSION = getattr(_fpdf_mod, "__version__", None) or getattr(_fpdf_mod, "FPDF_VERSION", "0")


def _ensure_fpdf2() -> None:
    try:
        major = int(str(_FPDF_VERSION).split(".")[0])
    except (ValueError, IndexError):
        major = 0
    if major < 2:
        raise RuntimeError(
            f"检测到旧版 fpdf (pyfpdf {_FPDF_VERSION})，它用 latin-1 编码、无法处理中文，"
            "会导致 PDF 导出崩溃（issue #54）。请执行：\n"
            '    pip uninstall -y fpdf && pip install "fpdf2>=2.8.0"\n'
            "（fpdf 与 fpdf2 都以 `fpdf` 名称导入、互相冲突，必须卸载旧的 fpdf），"
            "或改用「下载 Markdown」导出。"
        )


# Per-OS CJK font candidates. The current OS's fonts are tried first so a
# user on Windows/Linux/macOS all get a working PDF without manual config.
_WIN_FONTS = [
    "C:/Windows/Fonts/simhei.ttf",    # 黑体
    "C:/Windows/Fonts/simsun.ttc",    # 宋体
    "C:/Windows/Fonts/simfang.ttf",   # 仿宋
]
_MAC_FONTS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]
_LINUX_FONTS = [
    "/usr/share/fonts/truetype/noto/NotoSansCJKsc-VF.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansSC[wght].ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]

# Substrings that reliably indicate a CJK-capable font during the recursive
# fallback scan (deliberately excludes bare "noto", which also matches the
# Latin-only Noto family).
_CJK_FONT_KEYWORDS = (
    "simhei", "simsun", "simfang", "fangsong",
    "pingfang", "heiti", "stheiti", "stsong", "songti", "kaiti",
    "hiragino sans gb", "arial unicode",
    "notosanscjk", "notoserifcjk", "notosanssc", "notoserifsc",
    "sourcehansans", "sourcehanserif", "wqy", "uming", "ukai",
)


def _font_candidates() -> list[str]:
    """Return CJK font paths ordered with the current OS's fonts first."""
    system = platform.system()
    if system == "Windows":
        return _WIN_FONTS + _MAC_FONTS + _LINUX_FONTS
    if system == "Darwin":
        return _MAC_FONTS + _WIN_FONTS + _LINUX_FONTS
    return _LINUX_FONTS + _MAC_FONTS + _WIN_FONTS


def _search_dirs() -> list[str]:
    home = Path.home()
    system = platform.system()
    if system == "Windows":
        return ["C:/Windows/Fonts"]
    if system == "Darwin":
        return ["/System/Library/Fonts", "/Library/Fonts", str(home / "Library/Fonts")]
    return ["/usr/share/fonts", "/usr/local/share/fonts", str(home / ".fonts")]


def _find_cjk_font() -> str | None:
    """Locate a CJK-capable TTF font, cross-platform.

    Priority:
    1. Project-bundled TTF variable font (best compatibility with fpdf2).
    2. System variable fonts (containing [wght] or -VF in filename).
    3. System TTF fonts (TrueType outline, renders in all PDF viewers).
    4. System TTC fonts (last resort, may cause garbled text in browsers).

    IMPORTANT: TTF (TrueType outline) fonts are strongly preferred because fpdf2
    embeds them as CIDFontType2 which renders correctly in ALL PDF viewers
    (Chrome, Firefox, Acrobat, etc.). TTC/OTF (CFF outline) fonts are embedded
    as CIDFontType0 which causes garbled text in many browser-based viewers.
    """
    # Bundled TTF variable fonts — best option for fpdf2 (CIDFontType2 embedding).
    for bundled in (_BUNDLED_FONT_TTF, _BUNDLED_FONT_VF_TTF):
        if bundled.exists():
            return str(bundled)

    # System font candidates - prioritize variable fonts, then TTF, avoid TTC
    # Pass 1: Variable fonts only ([wght] or -VF in filename)
    for path in _font_candidates():
        if Path(path).exists():
            if "[wght]" in path or "-VF" in path or "VF" in path:
                return path

    # Pass 2: TTF fonts (TrueType outline — CIDFontType2 embedding, works everywhere)
    for path in _font_candidates():
        if Path(path).exists() and path.lower().endswith(".ttf"):
            return path

    # Pass 3: TTC fonts (may be CFF-based — CIDFontType0, garbled in browsers)
    for path in _font_candidates():
        if Path(path).exists():
            logger.warning(
                "No TrueType (.ttf) CJK font found. Falling back to %s which may "
                "cause garbled text in browser PDF viewers. Install a TTF variable "
                "font (NotoSansSC[wght].ttf or NotoSansCJKsc-VF.ttf) for best compatibility.",
                path,
            )
            return path

    # Recursive scan - same priority: variable TTF > plain TTF > TTC
    for directory in _search_dirs():
        dpath = Path(directory)
        if not dpath.exists():
            continue
        # First, look for variable TTF fonts
        try:
            for font_path in sorted(dpath.rglob("*.ttf")):
                name_lower = font_path.name.lower()
                if any(k in name_lower for k in _CJK_FONT_KEYWORDS):
                    if "[wght]" in font_path.name or "-vf" in name_lower or "vf" in name_lower:
                        return str(font_path)
        except OSError:
            pass
        # Then, look for any TTF font
        try:
            for font_path in sorted(dpath.rglob("*.ttf")):
                if any(k in font_path.name.lower() for k in _CJK_FONT_KEYWORDS):
                    return str(font_path)
        except OSError:
            pass
        # Last resort: TTC fonts
        try:
            for font_path in sorted(dpath.rglob("*.ttc")):
                if any(k in font_path.name.lower() for k in _CJK_FONT_KEYWORDS):
                    logger.warning(
                        "Falling back to TTC font %s which may cause garbled text "
                        "in browser PDF viewers.", font_path,
                    )
                    return str(font_path)
        except OSError:
            pass
    return None


def _install_bundled_fonts_to_system() -> bool:
    """Try to install bundled TTF font to the system so other apps can use it too.

    Returns True if installation succeeded (or was not needed).
    """
    if not _BUNDLED_FONT_TTF.exists():
        return False

    system = platform.system()
    if system == "Linux":
        target_dir = Path.home() / ".fonts"
    elif system == "Darwin":
        target_dir = Path.home() / "Library" / "Fonts"
    else:
        # Windows: fonts are usually already available; skip auto-install.
        return False

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        dst = target_dir / _BUNDLED_FONT_TTF.name
        if not dst.exists():
            shutil.copy2(_BUNDLED_FONT_TTF, dst)
        # Rebuild font cache (Linux only)
        if system == "Linux":
            try:
                subprocess.run(
                    ["fc-cache", "-f", str(target_dir)],
                    capture_output=True,
                    timeout=30,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
        logger.info("已安装思源字体到 %s", target_dir)
        return True
    except OSError:
        return False


def _instantiate_variable_font(font_path: str, weight: int) -> str:
    """Pre-instantiate a variable font at a specific weight and cache the result.

    This avoids the slow fontTools instantiation on every PDF generation.
    Returns the path to the cached instantiated font file.
    """
    cache_dir = _get_font_cache_dir()

    # Generate a unique cache filename based on source font and weight.
    # The "_v2" suffix invalidates caches produced by the buggy version of
    # this function (which called instantiateVariableFont without inplace=True,
    # saving the original variable font instead of the instantiated static font).
    source = Path(font_path)
    cache_name = f"{source.stem}_wght{weight}_v2.ttf"
    cache_path = cache_dir / cache_name

    # Check if already cached and source hasn't changed
    if cache_path.exists():
        source_mtime = source.stat().st_mtime
        cache_mtime = cache_path.stat().st_mtime
        if cache_mtime > source_mtime:
            return str(cache_path)

    # Instantiate the variable font using fontTools.
    # inplace=True is REQUIRED: without it, instantiateVariableFont returns a
    # new font but leaves `varfont` unchanged, so varfont.save() would write
    # the original variable font (with fvar/gvar tables and default weight 100)
    # instead of the instantiated static font at the requested weight.
    logger.info("Pre-instantiating variable font %s at weight %d (this may take a moment)...", font_path, weight)
    try:
        from fontTools.varLib.instancer import instantiateVariableFont
        from fontTools.ttLib import TTFont
        varfont = TTFont(font_path)
        instantiateVariableFont(varfont, axisLimits={"wght": weight}, overlap=True, inplace=True)
        varfont.save(str(cache_path))
        varfont.close()
        logger.info("Cached instantiated font at %s", cache_path)
        return str(cache_path)
    except Exception as e:
        logger.warning("Failed to pre-instantiate variable font: %s. Falling back to runtime instantiation.", e)
        return font_path


def _get_font_paths() -> tuple[str, str | None, bool]:
    """Get font paths for Regular and Bold weights.

    For variable fonts, returns pre-instantiated cached paths.
    For non-variable fonts, returns the same path for both.

    Returns:
        Tuple of (regular_font_path, bold_font_path, is_variable_font).
        bold_font_path is None if only one font file is available.
        is_variable_font indicates whether the source font is a variable font.
    """
    font_path = _find_cjk_font()
    if not font_path:
        return ("", None, False)

    is_variable_font = "[wght]" in font_path or "-VF" in font_path or "VF" in font_path

    if is_variable_font:
        try:
            regular_path = _instantiate_variable_font(font_path, 400)
            bold_path = _instantiate_variable_font(font_path, 700)
            # Verify that pre-instantiation actually produced different files
            if regular_path != bold_path:
                return (regular_path, bold_path, True)
            # Pre-instantiation failed — return same path, caller will use variations param
            logger.info("Variable font pre-instantiation produced identical paths; "
                       "will use variations parameter instead")
        except Exception as e:
            logger.info("Variable font pre-instantiation failed: %s; "
                       "will use variations parameter instead", e)
        # Return original variable font path — caller must use variations parameter
        return (font_path, font_path, True)
    else:
        return (font_path, font_path, False)


def is_pdf_available() -> bool:
    """Check if PDF generation is available (CJK font found, fpdf2 installed).

    This is a quick check that does NOT instantiate fonts or generate PDFs.
    """
    try:
        _ensure_fpdf2()
    except RuntimeError:
        return False
    return _find_cjk_font() is not None


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _strip_md_inline(text: str) -> str:
    """Remove inline markdown formatting: **bold**, *italic*, `code`, [link](url)."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    return text


def _signal_color(signal: str) -> tuple[int, int, int]:
    s = signal.upper()
    if "BUY" in s:
        return (34, 197, 94)
    if "SELL" in s:
        return (239, 68, 68)
    return (251, 191, 36)


_REPORT_SECTIONS = [
    ("market_report", "技术分析报告"),
    ("sentiment_report", "市场情绪报告"),
    ("news_report", "新闻舆情报告"),
    ("fundamentals_report", "基本面报告"),
    ("policy_report", "政策分析报告"),
    ("hot_money_report", "游资追踪报告"),
    ("lockup_report", "解禁/减持报告"),
]


class _ReportPDF(FPDF):
    def __init__(self, ticker: str, trade_date: str, signal: str) -> None:
        super().__init__()
        self.ticker = ticker
        self.trade_date = trade_date
        self.signal = signal
        regular_path, bold_path, is_variable = _get_font_paths()
        if not regular_path:
            # Last resort: try to install bundled fonts to system and retry
            _install_bundled_fonts_to_system()
            regular_path, bold_path, is_variable = _get_font_paths()
        if not regular_path:
            raise RuntimeError(
                "未找到可用的中文字体，无法生成 PDF。请安装一款中文字体后重试"
                "（Windows 自带黑体，macOS 自带苹方，Linux 可 "
                "`apt install fonts-noto-cjk`），或改用「下载 Markdown」导出。"
            )
        
        if is_variable and regular_path != bold_path:
            # Pre-instantiated variable font: each weight is a separate file
            self.add_font("CJK", "", regular_path)
            self.add_font("CJK", "B", bold_path)
        elif is_variable:
            # Variable font but pre-instantiation failed: use variations parameter
            # This is slower but produces correct bold text
            logger.info("Using variable font with variations parameter (slower but correct)")
            self.add_font("CJK", "", regular_path, variations={"wght": 400})
            self.add_font("CJK", "B", regular_path, variations={"wght": 700})
        else:
            # Non-variable font: add without variations
            self.add_font("CJK", "", regular_path)
            self.add_font("CJK", "B", bold_path or regular_path)

    def _use_font(self, style: str = "", size: int = 10) -> None:
        """Set font with specified style and size.
        
        Args:
            style: Font style - "" for Regular (400), "B" for Bold (700)
            size: Font size in points
        """
        self.set_font("CJK", style, size)

    def header(self) -> None:
        self._use_font("B", 8)
        self.set_text_color(90, 90, 90)
        self.cell(0, 6, f"A股多Agent投研分析  |  {self.ticker}  |  {self.trade_date}", align="C")
        self.ln(8)
        self.set_draw_color(40, 40, 40)
        self.line(10, self.get_y(), self.w - 10, self.get_y())
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-15)
        self._use_font("B", 8)
        self.set_text_color(50, 50, 50)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="C")
        self.ln(4)
        self._use_font("B", 6)
        self.set_text_color(70, 70, 70)
        self.cell(0, 4, "仅供学习研究，不构成投资建议", align="C")

    def add_cover(self) -> None:
        self.add_page()
        self.ln(60)

        self._use_font("B", 24)
        self.set_text_color(255, 90, 31)
        self.cell(0, 12, "AI股票分析报告", align="C", ln=1)
        self.ln(20)

        self._use_font("B", 36)
        self.set_text_color(20, 20, 20)
        self.cell(0, 18, self.ticker, align="C", ln=1)
        self.ln(16)

        self._use_font("B", 14)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, f"分析日期: {self.trade_date}", align="C")
        self.ln(8)
        self.cell(0, 10, f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C")
        self.ln(20)

        r, g, b = _signal_color(self.signal)
        self._use_font("B", 40)
        self.set_text_color(r, g, b)
        self.cell(0, 20, self.signal.upper(), align="C", ln=1)
        self.ln(20)

        self._use_font("B", 9)
        self.set_text_color(40, 40, 40)
        self.multi_cell(
            0, 5,
            "免责声明: 本报告由 AI 自动生成, 仅供学习研究与技术演示, "
            "不构成任何投资建议。投资决策请咨询持牌专业机构。"
            "使用本报告所产生的任何损失由使用者自行承担。",
            align="C",
        )

    def add_section(self, title: str, content: str) -> None:
        self.add_page()
        self._use_font("B", 16)
        self.set_text_color(255, 90, 31)
        self.cell(0, 10, title, ln=1)
        self.ln(12)

        cleaned = _strip_think(content)
        self._render_markdown(cleaned)

    def _render_markdown(self, text: str) -> None:
        """Render markdown-formatted text with basic styling."""
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Empty line → small vertical gap
            if not stripped:
                self.ln(3)
                i += 1
                continue

            # Headings: ### → 11pt, ## → 13pt, # → 14pt
            if stripped.startswith("###"):
                self._use_font("B", 11)
                self.set_text_color(10, 10, 10)
                self.cell(0, 7, stripped.lstrip("#").strip(), ln=1)
                self.ln(8)
                i += 1
                continue
            if stripped.startswith("##"):
                self._use_font("B", 13)
                self.set_text_color(10, 10, 10)
                self.cell(0, 8, stripped.lstrip("#").strip(), ln=1)
                self.ln(9)
                i += 1
                continue
            if stripped.startswith("#"):
                self._use_font("B", 14)
                self.set_text_color(255, 90, 31)
                self.cell(0, 9, stripped.lstrip("#").strip(), ln=1)
                self.ln(10)
                i += 1
                continue

            # Horizontal rule
            if stripped in ("---", "***", "___"):
                self.set_draw_color(100, 100, 100)
                y = self.get_y() + 2
                self.line(10, y, self.w - 10, y)
                self.ln(6)
                i += 1
                continue

            # Bullet points (-, *, numbered)
            if re.match(r"^[-*]\s", stripped) or re.match(r"^\d+[.)]\s", stripped):
                self._use_font("", 10)  # Regular weight for body text
                self.set_text_color(10, 10, 10)
                if re.match(r"^[-*]\s", stripped):
                    bullet = "  •  "
                    body = stripped[2:].strip()
                else:
                    m = re.match(r"^(\d+[.)])\s*(.*)", stripped)
                    bullet = f"  {m.group(1)} "
                    body = m.group(2)
                body = _strip_md_inline(body)
                self.set_x(self.l_margin)
                self.multi_cell(0, 5.5, bullet + body, wrapmode="CHAR")
                i += 1
                continue

            # Table rows (|col|col|) → render as plain text with spacing
            if stripped.startswith("|") and stripped.endswith("|"):
                # Skip separator rows like |---|---|
                if re.match(r"^\|[-:\s|]+\|$", stripped):
                    i += 1
                    continue
                self._use_font("", 9)  # Regular weight for table text
                self.set_text_color(10, 10, 10)
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                row_text = "    ".join(_strip_md_inline(c) for c in cells)
                self.set_x(self.l_margin)
                self.multi_cell(0, 5, row_text, wrapmode="CHAR")
                i += 1
                continue

            # Regular paragraph — collect consecutive non-special lines
            para_lines = []
            while i < len(lines):
                ln = lines[i].strip()
                if not ln or ln.startswith("#") or ln.startswith("|") or re.match(r"^[-*]\s", ln) or re.match(r"^\d+[.)]\s", ln) or ln in ("---", "***", "___"):
                    break
                para_lines.append(ln)
                i += 1

            if para_lines:
                self._use_font("", 10)  # Regular weight for body text
                self.set_text_color(10, 10, 10)
                para = " ".join(para_lines)
                para = _strip_md_inline(para)
                self.set_x(self.l_margin)
                self.multi_cell(0, 5.5, para, wrapmode="CHAR")
                self.ln(2)
                continue

            i += 1


def _collect_sections(final_state: dict[str, Any]) -> list[tuple[str, str]]:
    """Assemble the (title, content) report sections shared by PDF & Markdown.

    Keeps both export formats in sync from a single source of truth.
    """
    sections: list[tuple[str, str]] = []

    for key, title in _REPORT_SECTIONS:
        content = final_state.get(key, "")
        if content:
            sections.append((title, _strip_think(str(content))))

    debate = final_state.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        parts = []
        if debate.get("bull_history"):
            parts.append(f"=== 多方论点 ===\n{debate['bull_history']}")
        if debate.get("bear_history"):
            parts.append(f"\n=== 空方论点 ===\n{debate['bear_history']}")
        if debate.get("judge_decision"):
            parts.append(f"\n=== 研究经理决策 ===\n{debate['judge_decision']}")
        if parts:
            sections.append(("多空辩论", _strip_think("\n".join(parts))))

    trader_decision = final_state.get("trader_investment_decision", "")
    if trader_decision:
        sections.append(("交易员决策", _strip_think(str(trader_decision))))

    inv_plan = final_state.get("investment_plan", "")
    if inv_plan:
        sections.append(("最终投资建议", _strip_think(str(inv_plan))))

    risk = final_state.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        parts = []
        for key_name, label in [("aggressive_history", "激进观点"),
                                 ("conservative_history", "保守观点"),
                                 ("neutral_history", "中性观点")]:
            if risk.get(key_name):
                parts.append(f"=== {label} ===\n{risk[key_name]}")
        if risk.get("judge_decision"):
            parts.append(f"\n=== 风控决策 ===\n{risk['judge_decision']}")
        if parts:
            sections.append(("风控评估", _strip_think("\n".join(parts))))

    final_decision = final_state.get("final_trade_decision", "")
    if final_decision:
        sections.append(("最终决策", _strip_think(str(final_decision))))

    return sections


def generate_pdf(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> bytes:
    """Generate a PDF report and return it as bytes.

    Raises RuntimeError if the wrong fpdf library is installed (issue #54) or no
    CJK font is available on the system — callers should catch this and fall back
    to Markdown export.
    """
    _ensure_fpdf2()
    pdf = _ReportPDF(ticker, trade_date, signal)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    pdf.add_cover()
    for title, content in _collect_sections(final_state):
        pdf.add_section(title, content)

    return bytes(pdf.output())


def generate_markdown(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> str:
    """Generate a Markdown report. Font-free and always works — the safe export.

    This is the bulletproof alternative to PDF when the system lacks a CJK
    font (common on minimal Linux/Windows installs).
    """
    out = [
        "# A股多Agent投研分析报告",
        "",
        f"- **股票代码**：{ticker}",
        f"- **分析日期**：{trade_date}",
        f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **交易信号**：**{signal.upper()}**",
        "",
        "> ⚠️ 本报告由 AI 多 Agent 系统自动生成，仅供学习研究与技术演示，"
        "不构成任何投资建议。投资决策请咨询持牌专业机构，使用本报告所产生的"
        "任何损失由使用者自行承担。",
        "",
        "---",
        "",
    ]
    for title, content in _collect_sections(final_state):
        out.append(f"## {title}")
        out.append("")
        out.append(content)
        out.append("")

    return "\n".join(out)
