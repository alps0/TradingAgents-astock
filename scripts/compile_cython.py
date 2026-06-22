#!/usr/bin/env python3
"""Compile Python source files to .so extensions using Cython.

Usage:
    python compile_cython.py [SITE_PACKAGES_DIR]

If SITE_PACKAGES_DIR is not provided, it is auto-detected from the
current Python's site-packages.

Files listed in KEEP_AS_PY are preserved as .py (entry points, Streamlit app).
All other .py files in PACKAGES are compiled to platform-specific .so extensions,
and the original .py source files are removed from site-packages.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────

# Modules that MUST remain as .py:
#   - Entry points referenced by [project.scripts] in pyproject.toml
#   - Streamlit app.py (Streamlit requires .py source to execute)
#   - All files that call st.* APIs (Cython cannot resolve Streamlit's
#     dynamic attribute dispatch and silently drops those calls at compile
#     time, resulting in missing UI elements like buttons and progress bars).
KEEP_AS_PY: set[Path] = {
    Path("cli") / "main.py",
    Path("web") / "launch.py",
    Path("web") / "app.py",
    #Path("web") / "components" / "sidebar.py",
    #Path("web") / "components" / "progress_panel.py",
    #Path("web") / "components" / "report_viewer.py",
}

# Top-level packages to compile
PACKAGES: tuple[str, ...] = ("tradingagents", "cli", "web")


# ── Helpers ────────────────────────────────────────────────────────────

def _find_site_packages() -> Path:
    """Auto-detect the site-packages directory of the current Python."""
    import site

    for sp in site.getsitepackages():
        if Path(sp).is_dir():
            return Path(sp)
    raise RuntimeError("Cannot find site-packages directory")


def _collect_py_files(site_pkg: Path) -> list[Path]:
    """Collect .py files to compile, excluding entry points."""
    files: list[Path] = []
    for pkg in PACKAGES:
        pkg_dir = site_pkg / pkg
        if not pkg_dir.is_dir():
            print(f"  [warn] package directory not found: {pkg_dir}")
            continue
        for py_file in sorted(pkg_dir.rglob("*.py")):
            rel = py_file.relative_to(site_pkg)
            if rel in KEEP_AS_PY:
                print(f"  [keep] {rel}")
                continue
            files.append(py_file)
    return files


def _generate_setup_py(site_pkg: Path, py_files: list[Path]) -> str:
    """Generate a setup.py that cythonizes all collected modules."""
    ext_lines: list[str] = []
    for py_file in py_files:
        rel = py_file.relative_to(site_pkg)
        module = str(rel.with_suffix("")).replace(os.sep, ".")
        src = str(py_file)
        ext_lines.append(f'    Extension("{module}", ["{src}"]),')

    return (
        "from setuptools import setup, Extension\n"
        "from Cython.Build import cythonize\n\n"
        "setup(\n"
        '    name="_cython_compile",\n'
        "    ext_modules=cythonize(\n"
        "        [\n"
        + "\n".join(ext_lines)
        + "\n        ],\n"
        '        compiler_directives={"language_level": "3"},\n'
        "    ),\n"
        ")\n"
    )


def _compile(site_pkg: Path, py_files: list[Path]) -> None:
    """Generate a temporary setup.py and run cythonize build_ext --inplace."""
    setup_content = _generate_setup_py(site_pkg, py_files)
    setup_path = site_pkg / "_cython_setup.py"
    setup_path.write_text(setup_content, encoding="utf-8")

    try:
        subprocess.run(
            [sys.executable, str(setup_path), "build_ext", "--inplace"],
            cwd=str(site_pkg),
            check=True,
        )
    finally:
        setup_path.unlink(missing_ok=True)
        shutil.rmtree(site_pkg / "build", ignore_errors=True)


def _cleanup(site_pkg: Path, py_files: list[Path]) -> None:
    """Remove compiled .py and .c files; purge __pycache__ directories."""
    removed = 0
    for py_file in py_files:
        py_file.unlink(missing_ok=True)
        c_file = py_file.with_suffix(".c")
        c_file.unlink(missing_ok=True)
        removed += 1

    for pkg in PACKAGES:
        pkg_dir = site_pkg / pkg
        if pkg_dir.is_dir():
            for pycache in pkg_dir.rglob("__pycache__"):
                shutil.rmtree(pycache, ignore_errors=True)

    print(f"  Removed {removed} .py source files")


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    site_pkg = Path(sys.argv[1]) if len(sys.argv) > 1 else _find_site_packages()
    print(f"Site-packages: {site_pkg}")

    py_files = _collect_py_files(site_pkg)
    if not py_files:
        print("No files to compile.")
        return

    print(f"\nCompiling {len(py_files)} files to .so ...")
    _compile(site_pkg, py_files)
    _cleanup(site_pkg, py_files)
    print(f"\nDone — {len(py_files)} modules compiled to .so.")


if __name__ == "__main__":
    main()
