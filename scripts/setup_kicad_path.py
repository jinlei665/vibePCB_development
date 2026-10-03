# -*- coding: utf-8 -*-
"""让当前 venv 能 `import pcbnew`，并让 `kicad-cli` 可被找到。

背景：`pcbnew` 是 KiCad 自带的 CPython 扩展，**不在 PyPI 上**，venv 默认看不见它。
本脚本定位本机 KiCad 安装，然后：

1. 在 venv 的 site-packages 下写一个 `vibepcb_kicad.pth`，把 KiCad 的 Python 目录
   加入 `sys.path`，同时对其调用 `os.add_dll_directory()`（Windows 上 `_pcbnew.pyd`
   依赖同目录的 KiCad DLL，必须显式声明搜索目录，否则报 DLL load failed）；
2. 打印应加入 PATH 的目录（`kicad-cli` 所在 bin）；
3. 实地尝试 `import pcbnew` 并给出诊断——尤其是 **Python 小版本不匹配** 这种情况
   （`_pcbnew.pyd` 的 ABI 与 CPython 小版本绑定，是这条链路最常见的坑）。

用法：
    .venv\\Scripts\\python.exe scripts\\setup_kicad_path.py
    .venv\\Scripts\\python.exe scripts\\setup_kicad_path.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PTH_NAME = "vibepcb_kicad.pth"

# 常见安装根目录（Windows / macOS / Linux）
_WIN_ROOTS = [
    Path(r"C:\Program Files\KiCad"),
    Path(r"C:\Program Files (x86)\KiCad"),
    Path(r"D:\KiCad"),
    Path(r"E:\KiCad"),
]
_UNIX_ROOTS = [Path("/usr/share/kicad"), Path("/usr/lib/kicad"), Path("/opt/kicad"),
               Path("/Applications/KiCad"), Path("/usr/local/share/kicad")]


def candidate_roots() -> list[Path]:
    roots = _WIN_ROOTS if os.name == "nt" else _UNIX_ROOTS
    out = [r for r in roots if r.is_dir()]
    # 版本化子目录（如 C:\Program Files\KiCad\10.0）也算根
    for r in list(out):
        for child in sorted(r.iterdir()):
            if child.is_dir() and child.name[:1].isdigit():
                out.append(child)
    if os.name == "nt":
        for drive in "CDEFG":
            p = Path(f"{drive}:\\Program Files\\KiCad")
            if p.is_dir() and p not in out:
                out.append(p)
    return out


def find_pcbnew_dirs() -> tuple[list[Path], Path | None]:
    """返回 (含 pcbnew 模块的目录列表, kicad-cli 所在目录)。"""
    mod_dirs: list[Path] = []
    cli_dir: Path | None = None
    patterns = ("_pcbnew*.pyd", "_pcbnew*.so") if os.name == "nt" else ("_pcbnew*.so", "pcbnew.py")
    for root in candidate_roots():
        for pat in patterns:
            for hit in root.rglob(pat):
                d = hit.parent
                if d not in mod_dirs:
                    mod_dirs.append(d)
            if mod_dirs:
                break
        cli = root / "bin" / ("kicad-cli.exe" if os.name == "nt" else "kicad-cli")
        if cli.exists():
            cli_dir = cli.parent
        else:
            for hit in root.rglob("kicad-cli*"):
                if hit.is_file():
                    cli_dir = hit.parent
                    break
    return mod_dirs, cli_dir


def site_packages() -> Path:
    import site

    for p in site.getsitepackages() + [site.getusersitepackages()]:
        if "site-packages" in p and Path(p).is_dir():
            return Path(p)
    return Path(sys.prefix) / "Lib" / "site-packages"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写 .pth")
    args = ap.parse_args()

    print(f"interpreter : {sys.executable}")
    print(f"version     : {sys.version.split()[0]}")
    print(f"exec_prefix : {sys.exec_prefix}")
    print(f"base_prefix : {sys.base_prefix}")
    print()

    mod_dirs, cli_dir = find_pcbnew_dirs()
    if not mod_dirs:
        print("X 没找到 pcbnew 模块。请先安装 KiCad：")
        print('    winget install --id KiCad.KiCad -e')
        print("  或从 https://downloads.kicad.org/kicad/windows/explore/stable 下载安装包。")
        return 2

    print("找到 pcbnew 目录：")
    for d in mod_dirs:
        print(f"  - {d}")
    print(f"kicad-cli 目录：{cli_dir if cli_dir else '(未找到 kicad-cli)'}")
    print()

    sp = site_packages()
    pth = sp / PTH_NAME
    lines = []
    for d in mod_dirs:
        lines.append(f"import sys,os;sys.path.append(r'{d}');"
                     f"os.path.isdir(r'{d}') and hasattr(os,'add_dll_directory') and "
                     f"os.add_dll_directory(r'{d}')")
    if args.dry_run:
        print(f"[dry-run] 将写入 {pth}")
        for line in lines:
            print("   " + line)
    else:
        pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"OK 已写入 {pth}")

    if cli_dir:
        print(f"\n请把下面目录加入 PATH，之后 kicad-cli 才可用：\n  {cli_dir}")

    # 实地验证（.pth 只在解释器启动时生效，所以用子进程验）
    print("\n--- import pcbnew 自检 ---")
    probe = subprocess.run(
        [sys.executable, "-c", "import pcbnew; print('pcbnew OK ->', getattr(pcbnew,'GetBuildVersion',lambda:'?')())"],
        capture_output=True, text=True,
    )
    if probe.returncode == 0:
        print(probe.stdout.strip())
        print("\n真实引擎可用：重启后端后 /api/capabilities 的 pcb_engine_selected 应为 pcbnew。")
        return 0

    err = (probe.stderr or "").strip()
    print("X import pcbnew 失败：")
    print("  " + err.splitlines()[-1] if err else "  (无错误输出)")
    if "DLL load failed" in err or "not a valid Win32" in err or "ModuleNotFoundError" in err:
        print(
            "\n常见原因：Kicad 自带解释器与当前 venv 的 Python 小版本不一致。\n"
            "pcbnew 的 .pyd 是按 CPython 小版本编译的 ABI，必须一致。\n"
            "用 KiCad 自带的 Python 重建 venv：\n"
            '    Remove-Item -Recurse -Force .venv\n'
            '    & "<KiCad>\\bin\\python.exe" -m venv .venv\n'
            "    .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
