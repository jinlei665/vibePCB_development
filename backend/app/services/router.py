# -*- coding: utf-8 -*-
"""确定性正交（曼哈顿）布线器 —— 算法层，与引擎层解耦。

输入抽象焊盘坐标，输出抽象线段 / 过孔（不依赖任何 PCB 引擎对象），
供 pcbnew 真实引擎与 kiutils 模拟引擎共用。

策略（MVP，架构文档 ADR-05）：
- F.Cu 走横向线段，B.Cu 走纵向线段，拐弯处打过孔；
- 每个网络按最近邻链式连接；
- 电源类网络加宽线宽。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

POWER_NET_KEYWORDS = ("GND", "+3V3", "+5V", "+BATT", "VBUS", "VIN", "+12V", "+24V")
WIDTH_POWER = 0.6     # mm
WIDTH_SIGNAL = 0.25   # mm
VIA_SIZE = 0.6
VIA_DRILL = 0.3
GRID = 0.05           # 坐标量化到 0.05mm，避免浮点毛刺


@dataclass
class RouteSegment:
    start: Tuple[float, float]
    end: Tuple[float, float]
    layer: str          # "F.Cu" / "B.Cu"
    width: float
    net: str

    @property
    def length_mm(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])


@dataclass
class RouteVia:
    position: Tuple[float, float]
    size: float
    drill: float

    @property
    def x(self) -> float:
        return self.position[0]

    @property
    def y(self) -> float:
        return self.position[1]


@dataclass
class RoutedNet:
    name: str
    segments: List[RouteSegment] = field(default_factory=list)
    vias: List[RouteVia] = field(default_factory=list)

    @property
    def total_length_mm(self) -> float:
        return sum(s.length_mm for s in self.segments)


def _q(v: float) -> float:
    return round(round(v / GRID) * GRID, 3)


def _width_for(net: str) -> float:
    return WIDTH_POWER if any(k in net for k in POWER_NET_KEYWORDS) else WIDTH_SIGNAL


def _nearest_chain(pads: List[Tuple[float, float]]) -> List[Tuple[int, int]]:
    """最近邻链：返回 (i, j) 连接对列表，覆盖所有焊盘。"""
    if len(pads) < 2:
        return []
    remaining = set(range(1, len(pads)))
    current = 0
    pairs: List[Tuple[int, int]] = []
    while remaining:
        best = min(
            remaining,
            key=lambda k: math.hypot(pads[k][0] - pads[current][0], pads[k][1] - pads[current][1]),
        )
        pairs.append((current, best))
        remaining.discard(best)
        current = best
    return pairs


def route_net(net_name: str, pads: List[Tuple[float, float]]) -> RoutedNet:
    """对单个网络做曼哈顿布线。

    每条连接为 L 形：起点横向（F.Cu）→ 过孔 → 纵向（B.Cu）→ 过孔回到焊盘层。
    水平/垂直坐标做 0.1mm 偏移错层，减少不同连接间的重叠。
    """
    rn = RoutedNet(name=net_name)
    if len(pads) < 2:
        return rn
    w = _width_for(net_name)
    for idx, (ia, ib) in enumerate(_nearest_chain(pads)):
        a, b = pads[ia], pads[ib]
        ax, ay = _q(a[0]), _q(a[1])
        bx, by = _q(b[0]), _q(b[1])
        if ax == bx and ay == by:
            continue
        # 少量错位，降低同层重叠
        offset = (idx % 5 - 2) * 0.1
        if ax == bx:  # 纯垂直
            rn.segments.append(RouteSegment((ax, ay), (ax, by), "B.Cu", w, net_name))
        elif ay == by:  # 纯水平
            rn.segments.append(RouteSegment((ax, ay), (bx, ay), "F.Cu", w, net_name))
        else:
            mid_x = _q(bx + offset)
            if mid_x == bx:
                # 错层偏移归零（idx%5==2）：单层 L 形。避免零长度末段
                # (bx,by)→(bx,by) 与钻在焊盘 b 中心的过孔（质检 P2 实跑复现）
                if (ax, ay) != (bx, ay):
                    rn.segments.append(RouteSegment((ax, ay), (bx, ay), "F.Cu", w, net_name))
                if (bx, ay) != (bx, by):
                    rn.segments.append(RouteSegment((bx, ay), (bx, by), "F.Cu", w, net_name))
            else:
                # 两层三段：横 F.Cu → 孔1 → 纵 B.Cu → 孔2 → 横 F.Cu
                if (ax, ay) != (mid_x, ay):
                    rn.segments.append(RouteSegment((ax, ay), (mid_x, ay), "F.Cu", w, net_name))
                rn.vias.append(RouteVia((mid_x, ay), VIA_SIZE, VIA_DRILL))
                rn.segments.append(RouteSegment((mid_x, ay), (mid_x, by), "B.Cu", w, net_name))
                rn.vias.append(RouteVia((mid_x, by), VIA_SIZE, VIA_DRILL))
                # mid_x != bx 保证此段非零长，且孔2 不落在焊盘 b 中心
                rn.segments.append(RouteSegment((mid_x, by), (bx, by), "F.Cu", w, net_name))
    return rn


def route_all(net_pads: dict) -> dict:
    """输入 {net_name: [(x,y), ...]}，返回 {net_name: RoutedNet}。"""
    return {name: route_net(name, pads) for name, pads in net_pads.items() if len(pads) >= 2}
