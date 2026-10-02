"""parse 阶段：自然语言 → RequirementSpec（文档 5.3①）。

DeepSeek 不可达时 rule-based 兜底：关键词匹配 + 默认 ESP32 模板。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..core.deepseek_client import DeepSeekError, deepseek_client
from ..core.workspace import ProjectWorkspace
from ..models.schemas import RequirementSpec

logger = logging.getLogger("vibepcb.parser")

_SYSTEM_PROMPT = (
    "你是嵌入式硬件需求分析师。把用户的自然语言产品需求解析为结构化 JSON，"
    "严格输出 JSON 对象（不要 markdown 围栏），字段：\n"
    '{"product_name": str, "summary": str, '
    '"mcu": {"family": str, "module": str}, '
    '"features": [str], '
    '"sensors": [{"type": str, "part": str, "interface": str}], '
    '"actuators": [{"type": str, "driver": str, "part": str, "interface": str}], '
    '"displays": [{"part": str, "interface": str}], '
    '"interfaces": [str], '
    '"power": {"input": str, "rail_3v3": str}}\n'
    "约束：mcu.family 固定 ESP32 系；sensors.part/displays.part 用常见具体型号"
    "（如 DS18B20/DHT22/SSD1306）；interface 用 1-Wire/I2C/SPI/PWM/GPIO；"
    "没有的字段给空数组/空对象。"
)

_KW_SENSORS = [
    (re.compile(r"ds18b20|温控|温度|测温|thermo", re.I),
     {"type": "temperature", "part": "DS18B20", "interface": "1-Wire"}),
    (re.compile(r"dht22|sht31|温湿度", re.I),
     {"type": "temperature_humidity", "part": "DHT22", "interface": "GPIO"}),
    (re.compile(r"光照|bh1750|lux", re.I),
     {"type": "light", "part": "BH1750", "interface": "I2C"}),
    (re.compile(r"湿度", re.I),
     {"type": "humidity", "part": "DHT22", "interface": "GPIO"}),
]
_KW_ACTUATORS = [
    (re.compile(r"加热|暖|heat|加热膜|peltier", re.I),
     {"type": "heater_plate", "driver": "nMOS", "part": "AO3400A", "interface": "PWM"}),
    (re.compile(r"风扇|fan|电机|motor|继电器|relay", re.I),
     {"type": "fan", "driver": "nMOS", "part": "AO3400A", "interface": "PWM"}),
]
_KW_DISPLAYS = [
    (re.compile(r"oled|ssd1306|显示", re.I), {"part": "SSD1306", "interface": "I2C"}),
    (re.compile(r"lcd|st7735|tft", re.I), {"part": "ST7735", "interface": "SPI"}),
]


def _rule_based_spec(prompt: str) -> RequirementSpec:
    """关键词解析 + 默认 ESP32 通用模板（文档第 8 章兜底链第三级）。"""
    text = prompt or ""
    sensors = [m for pat, m in _KW_SENSORS if pat.search(text)]
    if not sensors and re.search(r"传感|sensor|监测", text, re.I):
        sensors.append({"type": "temperature", "part": "DS18B20", "interface": "1-Wire"})
    actuators = [m for pat, m in _KW_ACTUATORS if pat.search(text)]
    displays = [m for pat, m in _KW_DISPLAYS if pat.search(text)]

    interfaces = ["WiFi"]
    for s in sensors:
        if s["interface"] not in interfaces:
            interfaces.append(s["interface"])
    for a in actuators:
        if a.get("interface") and a["interface"] not in interfaces:
            interfaces.append(a["interface"])
    for d in displays:
        if d["interface"] not in interfaces:
            interfaces.append(d["interface"])

    features = ["WiFi 联网"]
    if sensors:
        features.append("传感采集")
    if actuators:
        features.append("执行器控制")
    if displays:
        features.append("本地显示")

    product = re.sub(r"[\"'{}]", "", text[:24]) or "ESP32 应用"
    return RequirementSpec(
        product_name=product.strip(),
        summary=f"ESP32 应用：{ '；'.join(features) }（rule-based 解析）",
        features=features, sensors=sensors, actuators=actuators,
        displays=displays, interfaces=interfaces,
    )


def _coerce_spec(obj: dict[str, Any]) -> RequirementSpec:
    """把模型输出整形成契约模型（宽松容错，字段缺失走默认值）。"""
    obj = dict(obj)
    obj.setdefault("mcu", {})
    if isinstance(obj.get("mcu"), dict):
        obj["mcu"].setdefault("family", "ESP32")
        obj["mcu"].setdefault("module", "ESP32-WROOM-32E")
    obj.setdefault("power", {})
    return RequirementSpec(**{
        k: v for k, v in obj.items()
        if k in RequirementSpec.model_fields
    })


def run_parse(ws: ProjectWorkspace, prompt: str) -> dict[str, Any]:
    """执行 parse 阶段，返回响应 dict（engine/degraded/spec）。"""
    from ..config import settings

    if settings.deepseek_configured:
        try:
            obj = deepseek_client.chat_json([
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ])
            spec = _coerce_spec(obj)
            engine, degraded = "deepseek", False
        except DeepSeekError as exc:
            logger.warning("parse deepseek failed, fallback to rule-based: %s", exc)
            spec = _rule_based_spec(prompt)
            engine, degraded = "rule-based", True
    else:
        spec = _rule_based_spec(prompt)
        engine, degraded = "rule-based", True

    # spec 落盘供后续阶段消费
    import json
    (ws.root / "in" / "spec.json").write_text(
        spec.model_dump_json(indent=2), encoding="utf-8"
    )
    return {
        "stage": "parse", "engine": engine, "degraded": degraded,
        "spec": spec.model_dump(),
    }
