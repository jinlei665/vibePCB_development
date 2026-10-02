"""ESP32 基础电路骨架：最小系统 + 电源 + 状态灯 + 低边驱动执行器。

全部使用 skidl scratch 零件（见 common.py 说明）。
所有 builder 接收共享 nets dict，返回新增零件列表。
"""
from __future__ import annotations

from skidl import Net

from .common import instantiate


def build_power(nets: dict[str, Net]) -> list:
    """5V 输入 + AMS1117 3.3V LDO + 输入/输出去耦 + PWR_FLAG（ERC 惯例）。"""
    parts = []
    # PWR_FLAG：为电源轨/地声明驱动能力，消除 ERC insufficient drive 告警
    for i, rail in enumerate(("GND",), start=1):
        parts.append(instantiate("PWR_FLAG", f"F{i}", "PWR_FLAG"))
        parts[-1][1] += nets[rail]

    parts.append(instantiate("USB_C_Power", "J1", "USB_C 5V"))
    parts[-1][1] += nets["5V"]
    parts[-1][2] += nets["GND"]

    parts.append(instantiate("AMS1117-3.3", "U4", "AMS1117-3.3"))
    u4 = parts[-1]
    u4["VI"] += nets["5V"]
    u4["VO"] += nets["3V3"]
    u4["GND"] += nets["GND"]

    for ref, val, net_a, net_b in (
        ("C1", "10uF", "5V", "GND"), ("C2", "100nF", "5V", "GND"),
        ("C3", "10uF", "3V3", "GND"), ("C4", "100nF", "3V3", "GND"),
    ):
        parts.append(instantiate("C", ref, val))
        parts[-1][1] += nets[net_a]
        parts[-1][2] += nets[net_b]
    return parts


def build_mcu(nets: dict[str, Net], mcu_key: str = "ESP32-WROOM-32E", ref: str = "U1") -> list:
    """ESP32 最小系统：电源 + EN 上拉 + 复位电容 + 状态灯。"""
    parts = [instantiate(mcu_key, ref)]
    mcu = parts[0]
    mcu["3V3"] += nets["3V3"]
    for gnd_pin in mcu.pins:
        if gnd_pin.name.upper() in ("GND", "GND1", "GND2", "GND3"):
            gnd_pin += nets["GND"]

    # EN 上拉 + 复位电容
    parts.append(instantiate("R", "R1", "10k"))
    parts[-1][1] += nets["3V3"]
    parts[-1][2] += mcu["EN"]
    parts.append(instantiate("C", "C5", "1uF"))
    parts[-1][1] += mcu["EN"]
    parts[-1][2] += nets["GND"]

    # 状态灯：IO2 → 1k → LED → GND
    parts.append(instantiate("R", "R2", "1k"))
    parts[-1][1] += mcu["IO2"]
    parts[-1][2] += nets.setdefault("LED_STATUS", Net("LED_STATUS"))
    parts.append(instantiate("LED", "D1", "GREEN"))
    parts[-1]["A"] += nets["LED_STATUS"]
    parts[-1]["K"] += nets["GND"]
    return parts


def build_status_led(nets: dict[str, Net]) -> list:  # 兼容扩展位：外部电源指示灯
    return []


def build_actuator_lowside(nets: dict[str, Net], *, gate_pin: str = "IO25",
                           net_name: str = "HEATER_PWM", heater_ref: str = "J2") -> list:
    """低边 nMOS 功率回路：MCU PWM → 栅极电阻 → AO3400A → 负载连接器。"""
    pwm = nets.setdefault(net_name, Net(net_name))
    parts = []
    parts.append(instantiate("R", "R3", "100R"))
    parts[-1][1] += pwm
    parts[-1][2] += nets["_mcu_gate"] if "_mcu_gate" in nets else pwm

    parts.append(instantiate("AO3400A", "Q1", "AO3400A"))
    q1 = parts[-1]
    q1["G"] += pwm
    q1["S"] += nets["GND"]

    # 栅极下拉
    parts.append(instantiate("R", "R4", "10k"))
    parts[-1][1] += pwm
    parts[-1][2] += nets["GND"]

    # 负载连接器：5V 供电轨 → 负载 → MOS 漏极
    parts.append(instantiate("Conn_01x02", heater_ref, "HEATER_OUT"))
    parts[-1][1] += nets["5V"]
    parts[-1][2] += q1["D"]
    return parts
