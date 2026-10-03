# -*- coding: utf-8 -*-
"""器件 / 封装库浏览（CAD 化增量 4）。

数据源全部是仓库内置的，没有外部依赖：

* `templates/footprint_map.json` 的 `parts` —— 15 个器件的 symbol / footprint /
  描述 / 引脚定义；
* `templates/footprint_libs/*.pretty` —— 14 个封装快照（真实 .kicad_mod）。

这是"**当前真正可用**的器件清单"：选型阶段（selector.py）只会把结果收敛到
footprint_map 能落地的范围内，所以前端浏览这份清单看到的器件/封装都是能用的，
不会出现"库里选了却生成不出来"的落差。
"""
from __future__ import annotations

from pathlib import Path

from ..templates.schematic.common import FOOTPRINT_MAP, PARTS

LIBS_DIR = Path(__file__).resolve().parent.parent / "templates" / "footprint_libs"


def parts_catalog() -> list:
    out = []
    for key, info in PARTS.items():
        out.append({
            "key": key,
            "symbol": info.get("symbol", ""),
            "footprint": info.get("footprint", ""),
            "description": info.get("description", ""),
            "pin_count": len(info.get("pins", [])),
            "pins": [{"num": p.get("num"), "name": p.get("name"), "func": p.get("func")}
                     for p in info.get("pins", [])],
        })
    return sorted(out, key=lambda x: x["key"])


def footprint_libs() -> list:
    libs = []
    if not LIBS_DIR.is_dir():
        return libs
    for d in sorted(LIBS_DIR.iterdir()):
        if not (d.is_dir() and d.name.endswith(".pretty")):
            continue
        lib = d.name[: -len(".pretty")]
        items = sorted(p.stem for p in d.glob("*.kicad_mod"))
        libs.append({
            "lib": lib,
            "count": len(items),
            "footprints": items,
            "ids": [f"{lib}:{i}" for i in items],
        })
    return libs


def footprint_ids() -> list:
    """拍平的 '库:封装' 列表，供前端下拉直接使用。"""
    return [fid for lib in footprint_libs() for fid in lib["ids"]]


def snapshot() -> dict:
    return {
        "parts": parts_catalog(),
        "libs": footprint_libs(),
        "footprint_ids": footprint_ids(),
        "presets": sorted(FOOTPRINT_MAP.get("presets", {}).keys()),
        "default_footprint_by_class": FOOTPRINT_MAP.get("default_footprint_by_class", {}),
    }
