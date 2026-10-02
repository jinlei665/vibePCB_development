"""components 阶段：RequirementSpec → BOM（文档 5.3②）。

DeepSeek 提议器件 → footprint_map.json 校正（symbol/footprint 必须存在于快照库，
否则同类默认项替换并写 warnings）→ 仍缺失则该器件标 DNP 不进网表。
DeepSeek 不可达时直接查映射表预置套件。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..core.deepseek_client import DeepSeekError, deepseek_client
from ..core.workspace import ProjectWorkspace
from ..templates.schematic.common import FOOTPRINT_MAP, PARTS

logger = logging.getLogger("vibepcb.selector")

_SYSTEM_PROMPT = (
    "你是电子元器件选型工程师。基于需求规格给出 ESP32 项目 BOM，"
    "严格输出 JSON 对象：{\"components\": [{\"ref\": str, \"value\": str, \"qty\": int, "
    "\"symbol\": str, \"footprint\": str, \"description\": str}]}\n"
    "ref 用 U1/Q1/R*/C* 风格；symbol/footprint 用 KiCad 官方库命名"
    "（如 RF_Module:ESP32-WROOM-32E）；阻容件可合并 qty。"
)


def _match_preset(spec: dict[str, Any], prompt: str) -> dict[str, Any]:
    """按 spec/prompt 关键词选预置套件（文档第 8 章兜底）。"""
    text = json.dumps(spec, ensure_ascii=False) + " " + (prompt or "")
    presets = FOOTPRINT_MAP["presets"]
    for key in ("esp32_thermo", "esp32_sensor_node"):
        p = presets[key]
        if any(kw in text for kw in p["match_keywords"]):
            return p
    return presets["esp32_generic"]


def _preset_bom(preset: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in preset["components"]:
        info = PARTS.get(c["value"])
        if info is None:
            continue
        out.append({
            "ref": c["ref"], "value": c["value"], "qty": c["qty"],
            "symbol": info["symbol"], "footprint": info["footprint"],
            "description": info["description"],
        })
    return out


def _validate_components(comps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """逐器件校正：symbol/footprint 必须能落到快照库；映射不到的用同类默认项替换。"""
    valid, warnings = [], []
    defaults = FOOTPRINT_MAP["default_footprint_by_class"]
    for c in comps:
        value = str(c.get("value", "")).strip()
        key = None
        for k, info in PARTS.items():
            if k.lower() in value.lower():
                key = k
                break
        if key is None:
            # 尝试按 symbol 名反查
            sym = str(c.get("symbol", ""))
            for k, info in PARTS.items():
                if info["symbol"].lower() == sym.lower():
                    key = k
                    break
        if key is None:
            warnings.append(f"未识别器件 {c.get('ref','?')} ({value})，标 DNP 不进网表")
            continue
        info = PARTS[key]
        fixed = dict(c)
        fixed["value"] = value or key
        fixed["qty"] = int(c.get("qty") or 1)
        fixed["symbol"] = info["symbol"]
        fixed["footprint"] = info["footprint"]
        fixed["description"] = c.get("description") or info["description"]
        if str(c.get("footprint", "")) and str(c["footprint"]) != info["footprint"]:
            warnings.append(
                f"{fixed.get('ref','?')}: footprint {c['footprint']} 不在快照库，"
                f"已替换为 {info['footprint']}"
            )
        valid.append(fixed)
    # 去重合并（同 symbol+footprint 的通器件）
    merged: list[dict[str, Any]] = []
    for v in valid:
        if v["ref"].endswith("*"):
            same = next(
                (m for m in merged if m["symbol"] == v["symbol"] and m["ref"].endswith("*")),
                None,
            )
            if same:
                same["qty"] += v["qty"]
                continue
        merged.append(v)
    return merged, warnings


def _nets_for(bom: list[dict[str, Any]]) -> list[str]:
    nets = ["3V3", "GND", "5V"]
    values = " ".join(c["value"] for c in bom)
    if "DS18B20" in values:
        nets += ["ONEWIRE"]
    if "DHT22" in values:
        nets += ["DHT_DATA"]
    if "SSD1306" in values or "ST7735" in values:
        nets += ["I2C_SDA", "I2C_SCL"]
    if any(c["value"] == "AO3400A" for c in bom):
        nets += ["HEATER_PWM"]
    if any(c["value"] == "LED" for c in bom):
        nets += ["LED_STATUS"]
    return nets


def run_components(ws: ProjectWorkspace, spec: dict[str, Any], prompt: str) -> dict[str, Any]:
    """执行 components 阶段，返回响应 dict。"""
    from ..config import settings

    warnings: list[str] = []
    if settings.deepseek_configured:
        try:
            obj = deepseek_client.chat_json([
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(spec, ensure_ascii=False)},
            ])
            comps = obj.get("components") or []
            engine, degraded = "deepseek+footprint_map", False
        except DeepSeekError as exc:
            logger.warning("components deepseek failed, fallback to preset: %s", exc)
            comps = _preset_bom(_match_preset(spec, prompt))
            engine, degraded = "footprint_map(preset)", True
            warnings.append(f"DeepSeek 不可达（{exc}），使用映射表预置套件")
    else:
        comps = _preset_bom(_match_preset(spec, prompt))
        engine, degraded = "footprint_map(preset)", True

    comps, w2 = _validate_components(comps)
    warnings.extend(w2)

    result = {
        "stage": "components", "engine": engine, "degraded": degraded,
        "components": comps, "nets_expected": _nets_for(comps),
        "warnings": warnings,
    }
    (ws.root / "in" / "bom.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
