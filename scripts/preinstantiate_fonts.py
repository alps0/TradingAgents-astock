#!/usr/bin/env python3
"""Pre-instantiate variable fonts at weights 400 (Regular) and 700 (Bold).

This script is run during Docker build to avoid a ~15s delay on the first
PDF export in the runtime container. The instantiated static fonts are
copied into the runtime image's font cache
(~/.cache/tradingagents/fonts/), so web/pdf_export.py can load them
directly without calling fontTools at runtime.

Usage:
    python preinstantiate_fonts.py <fonts_dir> <output_dir>
"""

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <fonts_dir> <output_dir>", file=sys.stderr)
        return 1

    fonts_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = sorted(fonts_dir.glob("*.ttf"))
    if not candidates:
        print(f"No .ttf fonts found in {fonts_dir}, skipping pre-instantiation")
        return 0

    # Prefer variable fonts ([wght] or -VF in filename)
    vf = [p for p in candidates if "[wght]" in p.name or "-VF" in p.name or "VF" in p.name]
    src = str(vf[0]) if vf else str(candidates[0])

    print(f"Pre-instantiating from: {src}")
    for w in (400, 700):
        f = TTFont(src)
        # inplace=True is critical — without it the original variable font
        # is saved unchanged (see web/pdf_export.py:_instantiate_variable_font).
        instantiateVariableFont(f, axisLimits={"wght": w}, overlap=True, inplace=True)
        out = output_dir / f"{Path(src).stem}_wght{w}_v2.ttf"
        f.save(str(out))
        f.close()
        print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
