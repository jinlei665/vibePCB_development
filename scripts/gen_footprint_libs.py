#!/usr/bin/env python3
"""一次性生成内置封装库快照（提交进仓库的静态资产）。

生成规则与 footprint_map.json 的 pad 编号一一对应。
"""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "backend", "app", "templates", "footprint_libs")

HDR = '(footprint "{name}" (version 20221018) (generator vibepcb)\n  (layer "F.Cu")\n'
REF = '  (fp_text reference "REF**" (at 0 -{ry}) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))\n'
VAL = '  (fp_text value "{name}" (at 0 {vy}) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))\n'


def fp(lib, name, attr, lines, pads, ry=1.5, vy=1.5):
    d = os.path.join(ROOT, lib + ".pretty")
    os.makedirs(d, exist_ok=True)
    body = HDR.format(name=name) + attr + REF.format(ry=ry) + VAL.format(name=name, vy=vy)
    body += lines
    body += pads + ")\n"
    with open(os.path.join(d, name + ".kicad_mod"), "w") as f:
        f.write(body)


SMD = '  (attr smd)\n'
THT = '  (attr through_hole)\n'
VIRTUAL = '  (attr exclude_from_pos_files exclude_from_bom)\n'


def silk(w, x1, y1, x2, y2):
    return f'  (fp_line (start {x1} {y1}) (end {x2} {y2}) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))\n'


def smd_pad(num, x, y, sx, sy):
    return (f'  (pad "{num}" smd rect (at {x} {y}) (size {sx} {sy}) '
            f'(layers "F.Cu" "F.Paste" "F.Mask"))\n')


def tht_pad(num, x, y, d=0.9, sx=1.6, sy=1.6):
    return (f'  (pad "{num}" thru_hole circle (at {x} {y}) (size {sx} {sy}) (drill {d}) '
            f'(layers "*.Cu" "*.Mask"))\n')


# ---- 0805 电阻/电容/LED ----
for lib, name, ry in (
    ("Resistor_SMD", "R_0805_2012Metric", 1.4),
    ("Capacitor_SMD", "C_0805_2012Metric", 1.4),
    ("LED_SMD", "LED_0805_2012Metric", 1.4),
):
    pads = smd_pad(1, -0.95, 0, 1.3, 1.5) + smd_pad(2, 0.95, 0, 1.3, 1.5)
    lines = silk(0.12, -1.5, -0.85, 1.5, -0.85) + silk(0.12, -1.5, 0.85, 1.5, 0.85)
    fp(lib, name, SMD, lines, pads, ry=ry, vy=1.6)

# ---- SOT-23（AO3400A：1=G 2=S 3=D）----
pads = smd_pad(1, -0.95, 1.0, 0.6, 1.0) + smd_pad(2, 0.95, 1.0, 0.6, 1.0) + smd_pad(3, 0, -1.0, 0.6, 1.0)
lines = silk(0.12, -1.4, -0.9, 1.4, -0.9)
fp("Package_TO_SOT_SMD", "SOT-23", SMD, lines, pads, ry=1.9, vy=1.9)

# ---- SOT-223-3_TabPin2（AMS1117：1=GND 2=VO(tab) 3=VI）----
pads = (smd_pad(1, -2.3, 1.7, 1.2, 2.0) + smd_pad(2, 0, -1.9, 3.6, 2.0)
        + smd_pad(3, 2.3, 1.7, 1.2, 2.0))
lines = silk(0.12, -3.5, -0.9, 3.5, -0.9)
fp("Package_TO_SOT_SMD", "SOT-223-3_TabPin2", SMD, lines, pads, ry=3.6, vy=3.6)

# ---- TO-92_Inline（DS18B20/DHT22）----
pads = tht_pad(1, -2.54, 0) + tht_pad(2, 0, 0) + tht_pad(3, 2.54, 0)
lines = silk(0.12, -3.6, -1.2, 3.6, -1.2) + silk(0.12, -3.6, 1.2, 3.6, 1.2)
fp("Package_TO_SOT_THT", "TO-92_Inline", THT, lines, pads, ry=2.0, vy=2.0)

# ---- ESP32-WROOM-32E（快照简化 30 pad：左右各 15，1.27 间距）----
pads = ""
for i in range(15):
    y = -8.89 + i * 1.27
    pads += smd_pad(i + 1, -8.6, y, 1.0, 0.9)          # 左列 1-15
    pads += smd_pad(i + 16, 8.6, y, 1.0, 0.9)          # 右列 16-30
lines = (silk(0.12, -9.0, -10.0, 9.0, -10.0) + silk(0.12, -9.0, 10.0, 9.0, 10.0)
         + silk(0.12, -9.0, -10.0, -9.0, 10.0) + silk(0.12, 9.0, -10.0, 9.0, 10.0))
fp("RF_Module", "ESP32-WROOM-32E", SMD, lines, pads, ry=11.0, vy=11.5)

# ---- PinHeader_1x02_P2.54mm（Conn_01x02）----
pads = tht_pad(1, 0, -1.27) + tht_pad(2, 0, 1.27)
lines = silk(0.12, -1.27, -2.6, 1.27, -2.6) + silk(0.12, -1.27, 2.6, 1.27, 2.6)
fp("Connector_PinHeader_2.54mm", "PinHeader_1x02_P2.54mm_Vertical", THT, lines, pads, ry=3.4, vy=3.4)

# ---- OLED 0.96in 4P（SSD1306 模块排针）----
pads = "".join(tht_pad(i + 1, 0, -3.81 + i * 2.54) for i in range(4))
lines = silk(0.12, -1.27, -5.2, 1.27, -5.2) + silk(0.12, -1.27, 5.2, 1.27, 5.2)
fp("vibepcb", "OLED_0.96in_4P", THT, lines, pads, ry=6.0, vy=6.0)

# ---- USB_C 电源（快照简化 3 pad：1=VBUS 2=GND 3=SHIELD）----
pads = tht_pad(1, -3.0, 0) + tht_pad(2, 0, 0) + tht_pad(3, 3.0, 0)
lines = silk(0.12, -4.5, -2.0, 4.5, -2.0) + silk(0.12, -4.5, 2.0, 4.5, 2.0)
fp("vibepcb", "USB_C_PowerOnly_Snapshot", THT, lines, pads, ry=2.8, vy=2.8)

# ---- 轻触按键 SW_PUSH_6mm ----
pads = tht_pad(1, -3.25, 0, d=1.0, sx=1.8, sy=1.8) + tht_pad(2, 3.25, 0, d=1.0, sx=1.8, sy=1.8)
lines = silk(0.12, -3.0, -3.0, 3.0, -3.0) + silk(0.12, -3.0, 3.0, 3.0, 3.0)
fp("Button_Switch_THT", "SW_PUSH_6mm", THT, lines, pads, ry=3.8, vy=3.8)

# ---- PWR_FLAG（虚拟件，不上板；PCB 阶段会过滤）----
pads = smd_pad(1, 0, 0, 1.0, 1.0)
fp("vibepcb", "PWR_FLAG_Snapshot", VIRTUAL, "", pads, ry=1.0, vy=1.0)

print("generated footprints under", os.path.normpath(ROOT))
for lib in sorted(os.listdir(ROOT)):
    print(" ", lib, "->", len(os.listdir(os.path.join(ROOT, lib))), "footprints")
