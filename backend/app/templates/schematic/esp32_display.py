"""I2C/SPI 显示子电路：SSD1306 OLED（I2C 模块，4Pin 排针）。"""
from __future__ import annotations

from skidl import Net

from .common import instantiate


def build_ssd1306(nets: dict[str, Net], *, mcu, sda_pin: str = "IO21",
                  scl_pin: str = "IO22", ref: str = "U3") -> list:
    """SSD1306 OLED：模块自带上拉，板上再加 10k 双上拉冗余。"""
    sda = nets.setdefault("I2C_SDA", Net("I2C_SDA"))
    scl = nets.setdefault("I2C_SCL", Net("I2C_SCL"))
    parts = [instantiate("SSD1306", ref, "SSD1306")]
    parts[0]["VCC"] += nets["3V3"]
    parts[0]["GND"] += nets["GND"]
    parts[0]["SCL"] += scl
    parts[0]["SDA"] += sda
    parts[0]["SCL"] += mcu[scl_pin]
    parts[0]["SDA"] += mcu[sda_pin]

    parts.append(instantiate("R", "R6", "10k"))
    parts[-1][1] += nets["3V3"]
    parts[-1][2] += scl
    parts.append(instantiate("R", "R7", "10k"))
    parts[-1][1] += nets["3V3"]
    parts[-1][2] += sda
    return parts
