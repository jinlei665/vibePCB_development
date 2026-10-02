# -*- coding: utf-8 -*-
"""固件阶段：DeepSeek 生成 + 模板拼装兜底。

- 输入：spec.json（parse 阶段）+ bom.json（components 阶段）；
- 首选 DeepSeek 生成 Arduino main.ino；失败（无 key / 超时 / 降级耗尽）走模板拼装，
  产物标 degraded=true；
- self_check：括号配平、引号配平、关键包含项检查。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..config import settings
from ..core.deepseek_client import DeepSeekClient, DeepSeekError
from ..core.errors import StageError
from ..core.workspace import ProjectWorkspace

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "firmware"


def run_firmware(ws: ProjectWorkspace) -> dict:
    spec_path = ws.root / "in" / "spec.json"
    bom_path = ws.root / "in" / "bom.json"
    for p, stage in ((spec_path, "parse"), (bom_path, "components")):
        if not p.exists():
            raise StageError("STAGE_PREREQ_MISSING", "firmware", f"缺少 {p.name}，请先完成 {stage} 阶段")

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    bom = json.loads(bom_path.read_text(encoding="utf-8"))

    fw_dir = ws.root / "firmware" / "main"
    fw_dir.mkdir(parents=True, exist_ok=True)

    code, engine, degraded = "", "", False
    deepseek_note = ""

    if settings.deepseek_api_key:
        try:
            client = DeepSeekClient(settings)
            code = _generate_with_deepseek(client, spec, bom)
            engine = "deepseek"
        except DeepSeekError as exc:
            deepseek_note = f"DeepSeek 失败（{exc.code}），已降级模板拼装"
            logger.warning("firmware: %s", deepseek_note)
            code, engine, degraded = _build_from_template(spec, bom), "template", True
    else:
        deepseek_note = "未设置 DEEPSEEK_API_KEY，直接使用模板拼装"
        code, engine, degraded = _build_from_template(spec, bom), "template", True

    main_file = fw_dir / "main.ino"
    main_file.write_text(code, encoding="utf-8")
    ws.register_artifact("firmware/main/main.ino", "firmware")

    # 附带配置说明
    readme = fw_dir / "README.md"
    readme.write_text(_firmware_readme(spec, engine), encoding="utf-8")

    checks = self_check(main_file, spec)

    return {
        "stage": "firmware",
        "engine": engine,
        "degraded": degraded,
        "note": deepseek_note,
        "entry": "main.ino",
        "files": sorted(p.name for p in fw_dir.iterdir() if p.is_file()),
        "self_check": checks,
    }


# ---------------------------------------------------------------- DeepSeek 生成
def _generate_with_deepseek(client: DeepSeekClient, spec: dict, bom: dict) -> str:
    comp_lines = "\n".join(
        f"- {c['ref']}: {c['value']} ({c.get('description', '')})"
        for c in bom.get("components", [])
    )
    prompt = (
        "为以下 ESP32 项目生成完整 Arduino 主程序（单一 .ino 文件，不依赖外部私有库；"
        "可用库：OneWire、DallasTemperature、DHT sensor library、Adafruit_SSD1306、Wire、WiFi、PubSubClient）。\n"
        f"产品：{spec.get('product_name', 'ESP32 设备')}\n"
        f"概述：{spec.get('summary', '')}\n"
        f"MCU：{spec.get('mcu', 'ESP32-WROOM-32E')}\n"
        f"功能：{', '.join(_text_list(spec.get('features', [])))}\n"
        f"传感器：{json.dumps(spec.get('sensors', []), ensure_ascii=False)}\n"
        f"执行器：{json.dumps(spec.get('actuators', []), ensure_ascii=False)}\n"
        f"显示：{json.dumps(spec.get('displays', []), ensure_ascii=False)}\n"
        f"接口：{', '.join(_text_list(spec.get('interfaces', [])))}\n"
        f"BOM：\n{comp_lines}\n\n"
        "要求：WiFi 与 MQTT 用占位符常量（用户自行填写），引脚分配写在文件头注释，"
        "包含 setup/loop、温度读取、PID 或滞回温控逻辑（若为温控类）、OLED 显示（若有）、"
        "串口日志。只输出代码本体，不要 markdown 围栏。"
    )
    code = client.chat_json(
        [{"role": "user", "content": prompt}],
        schema_hint={"code": "string (Arduino sketch source)"},
    )
    if isinstance(code, dict) and "code" in code:
        code = code["code"]
    code = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", str(code).strip())
    if len(code) < 200:
        raise DeepSeekError("DEEPSEEK_UNAVAILABLE", "生成代码过短")
    return code


# ---------------------------------------------------------------- 模板拼装（降级）
def _text_list(items: list) -> list:
    """spec 中 sensors/actuators/displays 可能是 dict 列表，归一化为可检索文本。"""
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(" ".join(str(v) for v in it.values()))
        else:
            out.append(str(it))
    return out


def _sensor_block(sensors: list) -> str:
    sensors = _text_list(sensors)
    has_ds = any("ds18b20" in s.lower() for s in sensors)
    has_dht = any("dht" in s.lower() for s in sensors)
    includes, setup, loop = [], [], []
    if has_ds:
        includes += ["#include <OneWire.h>", "#include <DallasTemperature.h>"]
        setup += [
            "  oneWire.begin(PIN_ONEWIRE);",
            "  sensors.begin();",
        ]
        loop += [
            "  sensors.requestTemperatures();",
            "  float temperature = sensors.getTempCByIndex(0);",
        ]
    if has_dht and not has_ds:
        includes += ["#include <DHT.h>"]
        setup += ["  dht.begin();"]
        loop += ["  float temperature = dht.readTemperature();"]
    if not (has_ds or has_dht):
        loop += ["  float temperature = 25.0;  // 占位：无温度传感器"]
    return includes, setup, loop


def _display_block(displays: list) -> tuple:
    displays = _text_list(displays)
    if not any(("oled" in d.lower() or "ssd1306" in d.lower()) for d in displays):
        return [], [], []
    inc = [
        "#include <Wire.h>",
        "#include <Adafruit_GFX.h>",
        "#include <Adafruit_SSD1306.h>",
    ]
    setup = [
        "  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);",
        "  display.clearDisplay();",
        "  display.setTextColor(WHITE);",
        "  display.setTextSize(1);",
    ]
    loop = [
        "  display.setCursor(0, 0);",
        "  display.printf(\"T=%.1fC S=%s\\n\", temperature, heaterOn ? \"ON \" : \"OFF\");",
        "  display.display();",
    ]
    return inc, setup, loop


def _wifi_mqtt_blocks(interfaces: list) -> tuple:
    inc = ["#include <WiFi.h>", "#include <PubSubClient.h>"]
    setup = [
        "  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);",
        "  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print(\".\"); }",
        "  Serial.println(WiFi.localIP());",
        "  mqtt.setServer(MQTT_BROKER, MQTT_PORT);",
    ]
    loop = [
        "  if (!mqtt.connected()) {",
        "    while (!mqtt.connect(CLIENT_ID)) delay(1000);",
        "  }",
        "  mqtt.loop();",
        "  static char payload[32];",
        "  snprintf(payload, sizeof(payload), \"%.2f\", temperature);",
        "  mqtt.publish(TOPIC_TEMP, payload);",
    ]
    return inc, setup, loop


_TPL_MAIN = (TEMPLATES_DIR / "arduino_main.tmpl").read_text(encoding="utf-8")




def _build_from_template(spec: dict, bom: dict) -> str:
    sensors = _text_list(spec.get("sensors", []))
    displays = _text_list(spec.get("displays", []))
    interfaces = _text_list(spec.get("interfaces", []))

    s_inc, s_setup, s_loop = _sensor_block(sensors)
    d_inc, d_setup, d_loop = _display_block(displays)
    w_inc, w_setup, w_loop = _wifi_mqtt_blocks(interfaces)

    # 保持唯一性 + 顺序
    includes = []
    for i in s_inc + d_inc + w_inc:
        if i not in includes:
            includes.append(i)

    objects = []
    if any("DS18B20" in i for i in sensors) or any("ds18b20" in s.lower() for s in sensors):
        objects += [
            "OneWire oneWire(PIN_ONEWIRE);",
            "DallasTemperature sensors(&oneWire);",
        ]
    elif any("dht" in s.lower() for s in sensors):
        objects += ["DHT dht(PIN_ONEWIRE, DHT22);"]
    if d_inc:
        objects += ["Adafruit_SSD1306 display(128, 64, &Wire, -1);"]
    objects += [
        "WiFiClient netClient;",
        "PubSubClient mqtt(netClient);",
    ]

    setup = s_setup + d_setup + w_setup
    loop = s_loop + d_loop + w_loop
    client_id = re.sub(r"[^a-zA-Z0-9_-]", "_", spec.get("product_name", "vibepcb")).lower() or "vibepcb"

    return _TPL_MAIN.format(
        product_name=spec.get("product_name", "ESP32 设备"),
        mcu=spec.get("mcu", "ESP32-WROOM-32E"),
        client_id=client_id,
        includes="\n".join(includes),
        objects="\n".join(objects),
        setup="\n".join("  " + s.strip() for s in setup),
        loop="\n".join("  " + s.strip() for s in loop),
    )


def _firmware_readme(spec: dict, engine: str) -> str:
    return (
        f"# {spec.get('product_name', 'ESP32 设备')} 固件\n\n"
        f"- 生成引擎：{engine}\n"
        "- 开发环境：Arduino IDE / PlatformIO（ESP32 Dev Module）\n"
        "- 依赖库：OneWire、DallasTemperature、DHT sensor library、"
        "Adafruit SSD1306、Adafruit GFX、PubSubClient（按实际用到安装）\n"
        "- 使用前修改 main.ino 顶部的 WiFi/MQTT 常量\n"
        "- 烧录：board 选 ESP32 Dev Module，Flash 4MB，串口 115200\n"
    )


# ---------------------------------------------------------------- 自检
def self_check(main_file: Path, spec: dict) -> dict:
    code = main_file.read_text(encoding="utf-8")
    checks = []
    # 括号配平
    checks.append({
        "name": "brace_balance",
        "passed": code.count("{") == code.count("}"),
        "detail": {"open": code.count("{"), "close": code.count("}")},
    })
    # 引号配平（忽略转义）
    stripped = re.sub(r'\\.', "", code)
    checks.append({
        "name": "quote_balance",
        "passed": stripped.count('"') % 2 == 0,
        "detail": {"quotes": stripped.count('"')},
    })
    # 关键结构
    checks.append({
        "name": "has_setup_loop",
        "passed": "void setup()" in code and "void loop()" in code,
        "detail": {},
    })
    checks.append({
        "name": "has_serial",
        "passed": "Serial.begin" in code,
        "detail": {},
    })
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
    }
