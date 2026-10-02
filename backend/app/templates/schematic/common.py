"""skidl 零件工厂：从 footprint_map.json 的 pin 定义创建 scratch 零件。

说明（ADR-01 的无 KiCad 兜底实现）：skidl 常规用法依赖 KICAD_SYMBOL_DIR 指向
KiCad 官方符号库；本仓库按架构文档第 8 章风险表内置"最小符号库快照"——
即 footprint_map.json 中每个器件的 pin 定义（编号与内置封装库 pad 一一对应），
用 skidl 的 SKIDL scratch 零件机制建模，网表输出与官方库零件结构一致。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skidl import Part, Pin, SKIDL

_MAP_PATH = Path(__file__).resolve().parent.parent / "footprint_map.json"
FOOTPRINT_MAP: dict[str, Any] = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
PARTS: dict[str, Any] = FOOTPRINT_MAP["parts"]

_PIN_FUNC = {
    "input": Pin.types.INPUT,
    "output": Pin.types.OUTPUT,
    "bidirectional": Pin.types.BIDIR,
    "passive": Pin.types.PASSIVE,
    "power_in": Pin.types.PWRIN,
    "power_out": Pin.types.PWROUT,
    "no_connect": Pin.types.NOCONNECT,
}

_part_cache: dict[str, Part] = {}


def part_template(key: str) -> Part:
    """按器件名创建 skidl scratch 模板零件。"""
    if key in _part_cache:
        return _part_cache[key]
    info = PARTS.get(key)
    if info is None:
        raise KeyError(f"part not in footprint_map snapshot: {key}")
    sym_name = info["symbol"].split(":")[-1]
    tmpl = Part(name=sym_name, tool=SKIDL, dest="TEMPLATE")
    for pin in info["pins"]:
        tmpl += Pin(num=pin["num"], name=pin["name"], func=_PIN_FUNC[pin["func"]])
    _part_cache[key] = tmpl
    return tmpl


def instantiate(key: str, ref: str, value: str | None = None) -> Part:
    """实例化器件：footprint 字段同步写入，供网表与 PCB 使用。"""
    info = PARTS[key]
    inst = part_template(key)(ref=ref, value=value or key)
    inst.footprint = info["footprint"]
    inst.ref_prefix = ref[0] if ref and ref[0].isalpha() else "U"
    return inst


def lookup(value: str) -> str | None:
    """按 BOM value 模糊查器件 key（如 '10k/100R…' → R，'ESP32-WROOM-32E' 命中模组）。"""
    v = (value or "").strip()
    if not v:
        return None
    if v in PARTS:
        return v
    low = v.lower()
    for key, info in PARTS.items():
        if key.lower() in low or low in key.lower():
            return key
    # 电阻/电容通配
    if low.startswith("r") and any(ch.isdigit() for ch in low):
        return "R"
    if low.startswith("c") and any(ch.isdigit() for ch in low):
        return "C"
    return None
