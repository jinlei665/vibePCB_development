"""常见传感器子电路：DS18B20（1-Wire）/ DHT22（单总线）。"""
from __future__ import annotations

from skidl import Net

from .common import instantiate


def build_ds18b20(nets: dict[str, Net], *, mcu, data_pin: str = "IO4",
                  ref: str = "U2", pullup_ref: str = "R5") -> list:
    """DS18B20 温度传感器：VDD=3V3，DQ 上拉 4k7，数据脚默认 IO4。"""
    onewire = nets.setdefault("ONEWIRE", Net("ONEWIRE"))
    parts = [instantiate("DS18B20", ref, "DS18B20")]
    parts[0]["VDD"] += nets["3V3"]
    parts[0]["GND"] += nets["GND"]
    parts[0]["DQ"] += onewire
    parts[0]["DQ"] += mcu[data_pin]

    parts.append(instantiate("R", pullup_ref, "4k7"))
    parts[-1][1] += nets["3V3"]
    parts[-1][2] += onewire
    return parts


def build_dht22(nets: dict[str, Net], *, mcu, data_pin: str = "IO4",
                ref: str = "U2", pullup_ref: str = "R5") -> list:
    """DHT22 温湿度传感器：VCC=3V3，DATA 上拉 10k。"""
    data = nets.setdefault("DHT_DATA", Net("DHT_DATA"))
    parts = [instantiate("DHT22", ref, "DHT22")]
    parts[0]["VCC"] += nets["3V3"]
    parts[0]["GND"] += nets["GND"]
    parts[0]["DATA"] += data
    parts[0]["DATA"] += mcu[data_pin]

    parts.append(instantiate("R", pullup_ref, "10k"))
    parts[-1][1] += nets["3V3"]
    parts[-1][2] += data
    return parts
