#!/usr/bin/env python3

from pathlib import Path
from fontTools.ttLib import TTFont
import shutil
import subprocess
import sys
import tempfile

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

    fontforge_script_content = r'''
import fontforge
import sys

input_font_path = sys.argv[1]
output_font_path = sys.argv[2]

font = fontforge.open(input_font_path)

# 保持原字体内部名称
font.generate(output_font_path)

font.close()
'''

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
            print(f"[INPUT]  {input_font_path.name}")
            print(f"[OUTPUT] {output_font_path.name}")

            if output_font_path.exists():
                output_font_path.unlink()

            # 使用 FontForge 转换 OTF -> TTF
            fontforge_command = [
                fontforge_executable,
                "-script",
                str(fontforge_script_path),
                str(input_font_path),
                str(output_font_path),
            ]

            subprocess.run(fontforge_command, check=True)

            # 修复为更容易识别的等宽标记
            converted_font = TTFont(str(output_font_path))

            if "post" in converted_font:
                converted_font["post"].isFixedPitch = 1

            if "OS/2" in converted_font and hasattr(converted_font["OS/2"], "panose"):
                converted_font["OS/2"].panose.bProportion = 9

            # 不修改字体内部名称 只修改 fixed pitch / PANOSE 元数据
            converted_font.save(str(output_font_path))

            print(f"[OK] {output_font_path.name}")

    finally:
        fontforge_script_path.unlink(missing_ok=True)

    print("=" * 60)
    print(f"[ALL DONE] Converted {len(otf_file_paths)} font files.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
