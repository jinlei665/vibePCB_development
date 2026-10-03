# -*- coding: utf-8 -*-
"""让 venv 能 `import pcbnew`，并让 `kicad-cli` 可被找到。

背景（KiCad 10.0.6 / Windows 实测）：

* `pcbnew` 是 KiCad 自带的 CPython 扩展，**不在 PyPI 上**。KiCad 10 的布局是
  `<root>\\bin\\Lib\\site-packages\\pcbnew.py` + `_pcbnew.pyd`，而它依赖的 DLL 全在
  `<root>\\bin\\`（msvcp140 / vcruntime140 / ucrtbase 等）。
* 光把 KiCad 的目录加进搜索路径**还不够**。真正反复踩的坑是 MSVC 工具链：本机上系统
  Python 是 Anaconda 的 `MSC v.1916`，KiCad 自带 Python 是 `MSC v.1944`，两者小版本
  都是 3.11，`_pcbnew.pyd` 仍会以
  `ImportError: DLL load failed while importing _pcbnew: 动态链接库(DLL)初始化例程失败`
  告终。**所以 venv 必须用 KiCad 自带的 Python 创建**——“小版本相同”并不足够。
* 用 KiCad 自带 Python 建 venv 还有额外好处：`sys.base_prefix` 就是 KiCad 的 bin，
  于是 `backend/app/core/engines.py` 能自动找到 kicad-cli，用户无需改系统 PATH。

用法：

    # 1)（推荐）先用 KiCad 自带 Python 重建 venv
    Remove-Item -Recurse -Force .venv
    & "<KiCad>\\bin\\python.exe" -m venv .venv
    .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt

    # 2) 再跑本脚本写路径钩子并自检
    .\\.venv\\Scripts\\python.exe scripts\\setup_kicad_path.py

    # 非标准安装位置（本机是 F:\\_kicad_dl\\KiCad\\10.0）可显式指定
    .\\.venv\\Scripts\\python.exe scripts\\setup_kicad_path.py --root "F:\\_kicad_dl\\KiCad\\10.0"
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PTH_NAME = "vibepcb_kicad.pth"

_WIN_ROOTS = [
    Path(r"C:\Program Files\KiCad"),
    Path(r"C:\Program Files (x86)\KiCad"),
    Path(r"D:\KiCad"), Path(r"E:\KiCad"), Path(r"F:\KiCad"),
]
_UNIX_ROOTS = [Path("/usr/share/kicad"), Path("/usr/lib/kicad"),
               Path("/opt/kicad"), Path("/Applications/KiCad"),
               Path("/usr/local/share/kicad")]


def _versioned(root: Path) -> list[Path]:
    """`<root>\\10.0` 这类版本子目录也算可用的安装根。"""
    out: list[Path] = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and child.name[:1].isdigit():
                out.append(child)
    return out


def _roots(explicit: str | None) -> list[Path]:
    if explicit:
        p = Path(explicit)
        return [p] + _versioned(p)
    env = os.environ.get("VIBEPCB_KICAD_ROOT", "").strip()
    if env:
        p = Path(env)
        return [p] + _versioned(p)
    out: list[Path] = []
    for r in (_WIN_ROOTS if os.name == "nt" else _UNIX_ROOTS):
        out.append(r)
        out.extend(_versioned(r))
    return out


def _drive_scan_roots() -> list[Path]:
    """兜底：扫描各固定盘符下一到两层的 KiCad 目录，覆盖自定义安装位置。

    只在常规路径都没找到时才调用（两层遍历在盘符内容多时较慢）。
    """
    if os.name != "nt":
        return []
    out: list[Path] = []
    for drive in "CDEFG":
        base = Path(f"{drive}:\\")
        if not base.exists():
            continue
        for pat in ("KiCad", "*\\KiCad", "*\\*\\KiCad"):
            try:
                for hit in base.glob(pat):
                    if hit.is_dir():
                        out.append(hit)
                        out.extend(_versioned(hit))
            except OSError:
                continue
    return out


def _locate(roots: list[Path]) -> tuple[Path | None, Path | None, Path | None]:
    """返回 (含 pcbnew 的目录, KiCad 的 bin 目录, kicad-cli 路径)。"""
    pats = ("_pcbnew*.pyd",) if os.name == "nt" else ("_pcbnew*.so",)
    exe = "kicad-cli.exe" if os.name == "nt" else "kicad-cli"
    mod_dir: Path | None = None
    bin_dir: Path | None = None
    cli: Path | None = None
    for r in roots:
        if not r.is_dir():
            continue
        if mod_dir is None:
            for cand in (r / "bin" / "Lib" / "site-packages", r / "bin", r):
                if not cand.is_dir():
                    continue
                hits: list[Path] = []
                for pat in pats:
                    hits.extend(sorted(cand.rglob(pat)))
                if hits:
                    mod_dir = hits[0].parent
                    break
        if cli is None:
            for cand in (r / "bin" / exe, r / exe):
                if cand.is_file():
                    cli = cand
                    break
            if cli is None:
                hits = sorted(r.rglob(exe))
                if hits:
                    cli = hits[0]
        if bin_dir is None:
            for cand in (r / "bin", r):
                if cand.is_dir() and (
                    (cand / "python.exe").is_file() or (cand / "kicad.exe").is_file()
                    or (cand / exe).is_file()
                ):
                    bin_dir = cand
                    break
        if mod_dir and cli and bin_dir:
            break
    return mod_dir, bin_dir, cli


def _build_of(exe: Path) -> str:
    try:
        out = subprocess.run([str(exe), "-c", "import sys;print(sys.version)"],
                             capture_output=True, text=True, timeout=30)
        line = out.stdout.strip().splitlines()
        return line[-1] if line else "?"
    except Exception as exc:  # noqa: BLE001
        return f"<无法执行: {exc}>"


def _msc(version_line: str) -> str:
    return version_line.split("(")[1].split(")")[0] if "(" in version_line else ""


def site_packages() -> Path:
    import site

    for p in list(site.getsitepackages()) + [site.getusersitepackages()]:
        if "site-packages" in p and Path(p).is_dir():
            return Path(p)
    return Path(sys.prefix) / "Lib" / "site-packages"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", help="KiCad 安装根目录，例如 F:\\\\_kicad_dl\\\\KiCad\\\\10.0")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写 .pth")
    args = ap.parse_args()

    print(f"interpreter : {sys.executable}")
    print(f"version     : {sys.version}")
    print(f"exec_prefix : {sys.exec_prefix}")
    print(f"base_prefix : {sys.base_prefix}")
    print()

    mod_dir, bin_dir, cli = _locate(_roots(args.root))
    if mod_dir is None:
        # 常规路径没找到 → 再扫各盘符一/两层（覆盖自定义安装位置）
        mod_dir, bin_dir, cli = _locate(_roots(args.root) + _drive_scan_roots())
    if mod_dir is None:
        print("X 没找到 pcbnew 模块。请先安装 KiCad：")
        print("    winget install --id KiCad.KiCad -e")
        print("  或从 https://downloads.kicad.org/kicad/windows/explore/stable 下载；")
        print("  装在非默认位置时用 --root 指定。")
        return 2

    print(f"pcbnew 目录 : {mod_dir}")
    print(f"kicad bin   : {bin_dir}")
    print(f"kicad-cli   : {cli or '(未找到)'}")
    print()

    # 关键前置检查：venv 的基础解释器是否就是 KiCad 的 Python（MSVC 工具链必须一致）
    warn_msvc = False
    if bin_dir:
        kicad_py = bin_dir / ("python.exe" if os.name == "nt" else "python")
        if kicad_py.is_file():
            kbuild = _build_of(kicad_py)
            print(f"venv  python build : {sys.version.split(chr(10))[0]}")
            print(f"kicad python build : {kbuild}")
            try:
                same_base = Path(sys.base_prefix).resolve() == bin_dir.resolve()
            except Exception:  # noqa: BLE001
                same_base = False
            warn_msvc = bool(_msc(kbuild)) and _msc(kbuild) != _msc(sys.version)
            if warn_msvc or not same_base:
                print()
                print("! 当前 venv 不是用 KiCad 自带 Python 创建的。")
                print("  Windows 上 `_pcbnew.pyd` 要求与 KiCad 的 MSVC 工具链一致；")
                print("  仅“Python 小版本相同”并不够，否则会报")
                print("  'DLL load failed while importing _pcbnew: 动态链接库(DLL)初始化例程失败'。")
                print("  请改用 KiCad 的 Python 重建 venv：")
                print("      Remove-Item -Recurse -Force .venv")
                print(f'      & "{kicad_py}" -m venv .venv')
                print("      .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt")
                print("      .\\.venv\\Scripts\\python.exe scripts\\setup_kicad_path.py")
            print()

    # .pth 只在解释器启动时执行，故把 sys.path 与 DLL 目录都写进去：
    # 模块来自 <bin>\Lib\site-packages，而依赖的 DLL 在 <bin>，两者都要声明。
    pth = site_packages() / PTH_NAME
    parts = [f"sys.path.append(r'{mod_dir}')"]
    for d in {str(mod_dir), str(bin_dir or mod_dir)}:
        parts.append(
            f"os.path.isdir(r'{d}') and hasattr(os,'add_dll_directory') "
            f"and os.add_dll_directory(r'{d}')"
        )
    line = "import sys,os;" + ";".join(parts)

    if args.dry_run:
        print(f"[dry-run] 将写入 {pth}")
        print("   " + line)
    else:
        pth.write_text(line + "\n", encoding="ascii")
        print(f"OK 已写入 {pth}")

    if bin_dir:
        print(f"\n如需在裸终端直接用 kicad-cli，把该目录加入 PATH：\n  {bin_dir}")
        print("  提示：后端会自动探测（PATH → venv 基础解释器目录 → 常见安装目录），")
        print("        若 venv 基于 KiCad 的 Python，通常无需手动配置 PATH。")

    print("\n--- import pcbnew 自检 ---")
    probe = subprocess.run(
        [sys.executable, "-c",
         "import pcbnew;print('pcbnew OK ->', pcbnew.GetBuildVersion())"],
        capture_output=True, text=True,
    )
    if probe.returncode == 0:
        print(probe.stdout.strip())
        print("\n真实引擎可用：重启后端后 /api/capabilities 应显示")
        print("  pcb_engine_selected=pcbnew、pcbnew_available=true、kicad_cli_available=true")
        return 1 if warn_msvc else 0

    err = (probe.stderr or "").strip()
    print("X import pcbnew 失败：")
    print("  " + (err.splitlines()[-1] if err else "(无错误输出)"))
    if "DLL" in err.upper():
        print("\n多为 MSVC 工具链不一致：请用 KiCad 自带 Python 重建 venv（见上文）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
