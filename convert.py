#!/usr/bin/env python3

import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from fontTools.ttLib import TTFont

# 只用于 Xshell / Windows 对亚洲字体双宽的兼容判断
# 1.00 = 不收窄
# 0.92 = 轻微收窄
# 0.88 = 推荐
# 0.85 = 更激进
CJK_COMPAT_WIDTH_RATIO = 0.88

# 用于修复 Comic Code 与亚洲字体混排时的上下基线不齐
VERTICAL_ASCENT_RATIO = 0.92
VERTICAL_DESCENT_RATIO = 0.25
VERTICAL_LINE_GAP = 0


def get_glyph_advance_width(font: TTFont, codepoint: int) -> int | None:
    if "hmtx" not in font:
        return None

    cmap = font.getBestCmap() or {}
    glyph_name = cmap.get(codepoint)

    if glyph_name is None:
        return None

    metrics = font["hmtx"].metrics

    if glyph_name not in metrics:
        return None

    advance_width, _ = metrics[glyph_name]
    return advance_width


def get_base_cell_width(font: TTFont) -> int:
    # 优先用常见等宽字符判断 Comic Code 的基础英文列宽
    preferred_codepoints = [
        ord(" "),
        ord("0"),
        ord("n"),
        ord("x"),
        ord("A"),
    ]

    for codepoint in preferred_codepoints:
        advance_width = get_glyph_advance_width(font, codepoint)

        if advance_width is not None and advance_width > 0:
            return advance_width

    if "hmtx" not in font:
        raise RuntimeError("Font does not have hmtx table")

    cmap = font.getBestCmap() or {}
    metrics = font["hmtx"].metrics

    ascii_widths = []

    for codepoint in range(0x21, 0x7F):
        glyph_name = cmap.get(codepoint)

        if glyph_name is None or glyph_name not in metrics:
            continue

        advance_width, _ = metrics[glyph_name]

        if advance_width > 0:
            ascii_widths.append(advance_width)

    if ascii_widths:
        return Counter(ascii_widths).most_common(1)[0][0]

    raise RuntimeError("Cannot determine base cell width")


def fix_comic_code_xshell_compatibility(font: TTFont) -> None:
    base_cell_width = get_base_cell_width(font)
    cjk_compat_width = max(1, round(base_cell_width * CJK_COMPAT_WIDTH_RATIO))

    # 声明为等宽字体
    if "post" in font:
        font["post"].isFixedPitch = 1

    if "OS/2" in font:
        os2_table = font["OS/2"]

        # 只降低平均字符宽度指标 给 Xshell / Windows 计算亚洲字体双宽时参考
        # 不修改 hmtx 所以 Comic Code 英文真实字宽保持原样
        os2_table.xAvgCharWidth = cjk_compat_width

        if hasattr(os2_table, "panose"):
            # 9 = Monospaced
            os2_table.panose.bProportion = 9

    # 英文字形和真实 advance width 保持原样

    print(f"[METRIC] baseCellWidth={base_cell_width}")
    print(f"[METRIC] cjkCompatWidth={cjk_compat_width}")
    print(f"[METRIC] cjkCompatWidthRatio={CJK_COMPAT_WIDTH_RATIO}")


def fix_comic_code_vertical_metrics(font: TTFont) -> None:
    if "head" not in font:
        raise RuntimeError("Font does not have head table")

    units_per_em = font["head"].unitsPerEm

    ascender = round(units_per_em * VERTICAL_ASCENT_RATIO)
    descender = -round(units_per_em * VERTICAL_DESCENT_RATIO)
    line_gap = VERTICAL_LINE_GAP

    # 修复 Comic Code 与亚洲字体混排时的上下基线不齐
    if "hhea" in font:
        font["hhea"].ascent = ascender
        font["hhea"].descent = descender
        font["hhea"].lineGap = line_gap

    if "OS/2" in font:
        os2_table = font["OS/2"]

        os2_table.sTypoAscender = ascender
        os2_table.sTypoDescender = descender
        os2_table.sTypoLineGap = line_gap

        os2_table.usWinAscent = ascender
        os2_table.usWinDescent = abs(descender)

        # 优先使用 typo metrics
        if hasattr(os2_table, "fsSelection"):
            os2_table.fsSelection |= 1 << 7

    print(f"[METRIC] unitsPerEm={units_per_em}")
    print(f"[METRIC] ascender={ascender}")
    print(f"[METRIC] descender={descender}")
    print(f"[METRIC] lineGap={line_gap}")


def remove_invalid_dsig(font: TTFont) -> None:
    # 修改字体后原签名失效 删除避免 Windows 识别异常
    if "DSIG" in font:
        del font["DSIG"]


def main() -> int:
    source_directory = Path(".")
    otf_file_paths = sorted(source_directory.glob("*.otf"))

    if not otf_file_paths:
        print("[WARN] No .otf files found")
        return 0

    fontforge_executable = shutil.which("fontforge")
    if fontforge_executable is None:
        print("[ERROR] fontforge not found")
        return 1

    fontforge_script_content = r"""
import fontforge
import sys

input_font_path = sys.argv[1]
output_font_path = sys.argv[2]

font = fontforge.open(input_font_path)

# 保持原字体内部名称
font.generate(output_font_path)

font.close()
"""

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
    ) as temporary_script_file:
        temporary_script_file.write(fontforge_script_content)
        fontforge_script_path = Path(temporary_script_file.name)

    try:
        for input_font_path in otf_file_paths:
            output_font_path = input_font_path.with_suffix(".ttf")

            print("=" * 60)
            print(f"[INPUT] {input_font_path.name}")
            print(f"[OUTPUT] {output_font_path.name}")

            if output_font_path.exists():
                output_font_path.unlink()

            fontforge_command = [
                fontforge_executable,
                "-script",
                str(fontforge_script_path),
                str(input_font_path),
                str(output_font_path),
            ]
            subprocess.run(fontforge_command, check=True)

            converted_font = TTFont(str(output_font_path))

            # 修改 Comic Code 对 Xshell 亚洲字体双宽的兼容信息
            fix_comic_code_xshell_compatibility(converted_font)

            # 修改 Comic Code 与亚洲字体混排时的上下基线信息
            fix_comic_code_vertical_metrics(converted_font)

            remove_invalid_dsig(converted_font)

            converted_font.save(str(output_font_path))

            print(f"[OK] {output_font_path.name}")

    finally:
        fontforge_script_path.unlink(missing_ok=True)

    print("=" * 60)
    print(f"[ALL DONE] Converted {len(otf_file_paths)} font files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
