"""schematic 阶段：BOM → skidl 电路 → ERC → 网表 + .kicad_sch 骨架（文档 5.3③）。

- 网表（out/project.net）是权威产物：skidl generate_netlist(tool=KICAD9)。
- .kicad_sch 为骨架文件（ADR-03）：符号引用 + 网格摆位 + 网络标签，不做图形化连线。
"""
from __future__ import annotations

import io
import json
import logging
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from ..core.errors import StageError
from ..core.workspace import ProjectWorkspace
from ..templates.schematic import esp32_base, esp32_display, esp32_sensor
from ..templates.schematic.common import PARTS

logger = logging.getLogger("vibepcb.schematic")


def _reset_skidl():
    """清空 skidl 全局电路缓存，保证单项目可重跑。"""
    import skidl

    try:
        skidl.reset()  # skidl 2.x：重置全局 circuit
    except Exception as exc:  # noqa: BLE001
        logger.warning("skidl reset failed: %s", exc)


def _build_circuit(spec: dict[str, Any], bom: dict[str, Any]):
    """按 spec/BOM 组装电路，返回 (mcu_part, nets, parts)。"""
    from skidl import Net

    nets: dict[str, Net] = {n: Net(n) for n in ("3V3", "GND", "5V")}

    parts = []
    parts += esp32_base.build_power(nets)
    parts += esp32_base.build_mcu(nets)
    mcu = parts[[p.ref for p in parts].index("U1")]

    values = {c["value"] for c in bom.get("components", [])}
    specsensors = {(s.get("part") or "").upper() for s in spec.get("sensors", [])}
    specsensors |= {(d.get("part") or "").upper() for d in spec.get("displays", [])}

    if "DS18B20" in values or "DS18B20" in specsensors:
        parts += esp32_sensor.build_ds18b20(nets, mcu=mcu)
    if "DHT22" in values or "DHT22" in specsensors:
        parts += esp32_sensor.build_dht22(nets, mcu=mcu)
    if "SSD1306" in values or "SSD1306" in specsensors:
        parts += esp32_display.build_ssd1306(nets, mcu=mcu)
    if any(a.get("type") in ("heater_plate", "fan", "heater") for a in spec.get("actuators", [])) \
            or "AO3400A" in values:
        parts += esp32_base.build_actuator_lowside(nets)

    # 未使用引脚挂 NC（skidl 将 NC 注入 builtins），消除 ERC unconnected 噪声
    nc = NC  # noqa: F821  (skidl 注入的 NOCONNECT 网络)
    for p in parts:
        for pin in p.pins:
            if not pin.is_connected():
                pin += nc
    return mcu, nets, parts


def _erc_report() -> dict[str, Any]:
    """运行 skidl ERC；skidl 经自有 logger + 控制台输出，双通道捕获。"""
    import logging as _logging

    import skidl

    records: list[str] = []

    class _Capture(_logging.Handler):
        def emit(self, record: _logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _Capture(level=_logging.WARNING)
    targets = [_logging.getLogger(), _logging.getLogger("skidl")]
    for lg in targets:
        lg.addHandler(handler)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            skidl.ERC()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ERC raised: %s", exc)
    finally:
        for lg in targets:
            lg.removeHandler(handler)

    lines = records + [l for l in buf.getvalue().splitlines() if l.strip()]
    errors = [m for m in lines if "ERC ERROR" in m or m.upper().startswith("ERROR")]
    warnings = [m for m in lines if "ERC WARNING" in m]
    return {
        "errors": len(errors), "warnings": len(warnings),
        "details": (errors + warnings)[:10],
    }


def _gen_netlist(out_dir: Path) -> dict[str, int]:
    """生成 KiCad 9 网表；返回 parts/nets 统计。

    必须显式传 track_abs_path=True（质检 D8）。skidl 的 Circuit 默认
    track_abs_path=False，此时它用 os.path.relpath(源文件, script_dir) 生成网表里的
    "SKiDL Line" 字段。而在多盘符 Windows 上（本机 venv 在 F:，基础解释器 stdlib 在
    D:\\Anaconda），skidl/scriptinfo.py 的 scriptinfo() 因为循环里没有 break
    （scriptinfo.py:53-59）会把 script_dir 解析成**最外层**未被跳过的帧——即 D: 盘的
    threading.py / concurrent\\futures\\thread.py，于是 relpath 抛
        ValueError: path is on mount 'F:', start on mount 'D:'
    导致 schematic 阶段 500。track_abs_path=True 会让 skidl 在
    tools/kicad9/gen_netlist.py:116、:200、:309 三处都走**绝对路径**分支，彻底绕开
    这个 relpath 调用；该字段只是网表里的源码溯源注释，不影响电气内容。
    """
    import skidl

    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        skidl.generate_netlist(
            tool=skidl.KICAD9,
            file_=str(out_dir / "project.net"),
            track_abs_path=True,
        )
    text = (out_dir / "project.net").read_text(encoding="utf-8")
    return {
        "parts": text.count("(comp\n") + text.count("(comp "),
        "nets": text.count("(net\n") + text.count("(net "),
    }


# ---------- .kicad_sch 骨架（s-表达式直接组装，ADR-03） ----------

def _lib_symbols_xml(used: dict[str, str]) -> str:
    """从快照库 pin 定义生成 lib_symbols 段；used = {part_key: reference 前缀}。"""
    blocks = []
    for key in sorted(used):
        info = PARTS[key]
        lib_id = info["symbol"]
        name = lib_id.split(":")[-1]
        prefix = used[key] if used[key].isalpha() else "U"
        hh = _body_half_h(info["pins"])
        lines = [
            f'    (symbol "{lib_id}" (pin_names (offset 1.016)) (in_bom yes) (on_board yes)',
            f'      (property "Reference" "{prefix}" (at 0 0 0) (effects (font (size 1.27 1.27))))',
            f'      (property "Value" "{name}" (at 0 0 0) (effects (font (size 1.27 1.27))))',
            '      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
            '      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
            f'      (symbol "{name}_0_1"',
            f'        (rectangle (start -7.62 {_n(hh)}) (end 7.62 -{_n(hh)}) '
            f'(stroke (width 0.254) (type default)) (fill (type background)))',
            "      )",
            f'      (symbol "{name}_1_1"',
        ]
        layout = _pin_layout(info["pins"])
        for i, pin in enumerate(info["pins"]):
            x, y, rot = layout[i]
            # 注意：lib_symbols 里的 pin **不能**带 (uuid ...)。KiCad 的 .kicad_sch
            # 解析器只允许符号实例里的 (pin "1" (uuid ...))，库定义里多一个 uuid 会
            # 直接 "加载原理图失败"（exit 3）—— 本机用二分法定位到此处（质检 D14）。
            lines.append(
                f'        (pin {pin["func"]} line (at {_n(x)} {_n(y)} {rot}) (length 2.54) '
                f'(name "{pin["name"]}" (effects (font (size 1.27 1.27)))) '
                f'(number "{pin["num"]}" (effects (font (size 1.27 1.27)))))'
            )
        lines.append("      )")
        lines.append("    )")
        blocks.append("\n".join(lines))
    return "  (lib_symbols\n" + "\n".join(blocks) + "\n  )"


def _sch_symbol_instances(parts: list, root_uuid: str) -> str:
    """符号实例网格摆位：MCU 居中，其余按序环绕。

    instances 的 path 必须是**根图纸的 uuid**：KiCad 靠它把实例引用解析回图纸层级。
    此前每个符号各生成一个随机 uuid，语义是错的（质检 D14 附带修正）。
    """
    blocks = []
    row_h = _row_height(parts)
    for idx, p in enumerate(parts):
        x, y = _symbol_at(idx, row_h)
        _k = _part_key(p)
        info_lib = PARTS[_k]["symbol"] if _k else p.name
        pin_lines = "\n".join(
            f'      (pin "{pin.num}" (uuid "{uuid.uuid4()}"))' for pin in p.pins
        )
        blocks.append(
            f'  (symbol (lib_id "{info_lib}") (at {x} {y} 0) (unit 1)\n'
            f'    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)\n'
            f'    (uuid "{uuid.uuid4()}")\n'
            f'    (property "Reference" "{p.ref}" (at {x} {y - 12.7} 0) (effects (font (size 1.27 1.27))))\n'
            f'    (property "Value" "{p.value}" (at {x} {y + 12.7} 0) (effects (font (size 1.27 1.27))))\n'
            f'    (property "Footprint" "{getattr(p, "footprint", "") or ""}" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))\n'
            f'    (property "Datasheet" "~" (at {x} {y} 0) (effects (font (size 1.27 1.27)) hide))\n'
            f'{pin_lines}\n'
            f'    (instances\n'
            f'      (project "vibepcb"\n'
            f'        (path "/{root_uuid}" (reference "{p.ref}") (unit 1))\n'
            f'      )\n'
            f'    )\n'
            f'  )'
        )
    return "\n".join(blocks)


# ---------- 引脚几何与连线（CAD 化增量 2） ----------
# 原先 _gen_kicad_sch 只摆符号 + 贴一排**悬空**的 global_label，符号之间一根 wire 都没有，
# 于是"原理图"在 KiCad 里只是一堆散着的方块。这里把几何抽成唯一真源，据此真正连线。
_PIN_PITCH = 2.54
_PIN_X = 10.16          # 引脚电气连接点距符号中心的 x（lib 坐标）
_SYM_COL = 40.64        # 实例网格：列间距
_SYM_ROW = 30.48        # 实例网格：行间距
_SYM_X0, _SYM_Y0 = 60.96, 60.96


def _n(v: float) -> str:
    """紧凑数值格式，避免 60.959999999999994 这类浮点噪声写进网表。"""
    return f"{round(float(v), 4):g}"


def _pin_layout(pins: list) -> list:
    """符号内部引脚布局 → [(lib_x, lib_y, rot)]。前半在左（朝外 -x），后半在右。

    这是**唯一真源**：lib_symbols 的绘制与连线坐标都调用它，避免两处公式漂移。
    """
    n = len(pins)
    out = []
    for i in range(n):
        y = 7.62 - (i % max(1, (n // 2 + 1))) * _PIN_PITCH
        left = i < (n + 1) // 2
        out.append((-_PIN_X if left else _PIN_X, y, 0 if left else 180))
    return out


def _pin_span(pins: list) -> float:
    """引脚布局的竖直跨度。"""
    ys = [y for (_x, y, _r) in _pin_layout(pins)]
    return (max(ys) - min(ys)) if ys else 0.0


def _body_half_h(pins: list) -> float:
    """符号体外框半高：必须**包住**引脚，否则画出来引脚挂在框外。"""
    return max(10.16, _pin_span(pins) / 2 + 2.54)


def _row_height(parts: list) -> float:
    """行距：必须容得下最高的符号。

    原先是固定 30.48，但 ESP32-WROOM-32E 有 30 个引脚，按 2.54 间距摊开后竖直跨度
    达 38.1mm —— 于是 U1 的最后一个引脚正好落在下一行 D1 的引脚坐标上，
    两个网络的引脚重合（质检 D16）。行距改为按实际最高符号动态计算。
    """
    tallest = 0.0
    for p in parts:
        k = _part_key(p)
        if k:
            tallest = max(tallest, _body_half_h(PARTS[k]["pins"]) * 2)
    return round(max(_SYM_ROW, tallest + 12.7), 4)


def _symbol_at(idx: int, row_h: float = _SYM_ROW) -> tuple:
    """实例网格摆位 → (x, y)。列距固定，行距按最高符号传入。"""
    return (_SYM_X0 + (idx % 4) * _SYM_COL, _SYM_Y0 + (idx // 4) * row_h)


def _part_key(p) -> str | None:
    """由 skidl 实例反查快照库中的器件 key —— 必须**精确**匹配符号名。

    原先用 `info["symbol"].endswith(p.name)` 做后缀匹配，结果所有电容（name="C"）
    都命中了 "Display:SSD1306_I2C"（以 "C" 结尾），于是电容被画成了 SSD1306，
    引脚也跟着错位（质检 D15）。改为比较符号名最后一段是否与实例名全等。
    """
    name = (getattr(p, "name", "") or "").split(":")[-1]
    if not name:
        return None
    if name in PARTS:
        return name
    for k, info in PARTS.items():
        if info["symbol"].split(":")[-1] == name:
            return k
    return None


def _collect_net_pins(parts: list) -> dict:
    """{net_name: [(x, y, rot), ...]}：每个网络全部引脚的**图纸绝对坐标**与朝向。"""
    result: dict = {}
    row_h = _row_height(parts)
    for idx, p in enumerate(parts):
        key = _part_key(p)
        if key is None:
            continue
        pins_def = PARTS[key]["pins"]
        layout = _pin_layout(pins_def)
        sx, sy = _symbol_at(idx, row_h)
        # 按**位置**对应引脚：common.py 就是按 info["pins"] 的顺序逐个 Pin(...) 建模板的。
        # 不能用 pin.num 查表 —— 快照库里同一器件可能存在重复的 pin 编号（例如多个 GND），
        # 字典会把它们折叠到同一坐标（质检 D15 连带修正）。
        for i, pin in enumerate(p.pins):
            net = getattr(pin, "net", None)
            if net is None or i >= len(layout):
                continue
            lx, ly, rot = layout[i]
            # 坐标变换：符号库 +Y 向上，.kicad_sch 图纸 +Y **向下**，
            # 故绝对坐标 = (sym_x + lib_x, sym_y - lib_y)。rot 只做左右镜像，y 不变。
            result.setdefault(net.name, []).append(
                (round(sx + lx, 4), round(sy - ly, 4), rot)
            )
    return result


_EPS = 1e-6


def _pt_on_seg(p, a, b) -> bool:
    """点 p 是否落在段 ab 的**内部**（不含端点）。

    KiCad 把"导线端点落在另一根导线上"当作**连通**（等同打了 junction），
    所以这正是会把两个网络短接的情形，必须显式避开。
    """
    (px, py), (ax, ay), (bx, by) = p, a, b
    if abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) > 1e-6:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    sq = (bx - ax) ** 2 + (by - ay) ** 2
    return _EPS < dot < sq - _EPS


def _segs_conflict(s1, s2) -> bool:
    """两段是否构成"会短接"的关系（任一端点落在对方内部）。"""
    (a, b), (c, d) = s1, s2
    return bool(_pt_on_seg(a, c, d) or _pt_on_seg(b, c, d)
                or _pt_on_seg(c, a, b) or _pt_on_seg(d, a, b))


def _is_nc(name: str) -> bool:
    """是否是"未连接引脚"的汇总网络。

    skidl 把这些引脚挂在一个叫 `__NOCONNECT` 的网络上（而不是 N/C 或 NC），
    必须识别出来 —— 否则它们会被当成一个真实网络、用导线全部串在一起，
    导出一个凭空多出来的大网络（质检 D17）。
    """
    n = (name or "").strip().upper().replace("_", "").replace("/", "").replace("-", "")
    return n in ("NC", "NOCONNECT")


def _route_nets(net_pins: dict) -> list:
    """经典「梳形总线」布线，返回 [(net_name, segments, junction_points, label_anchor)]。

    拓扑（每个引脚三步）：朝外短桩 → 竖直下到本网络的通道 y → 水平汇到本网络总线末端。

    为什么这个拓扑能**保证不串网**：

    * 不同网络的通道 y 互不相同（每条网络一个 lane），不同网络之间只会有**交叉**——
      KiCad 对单纯交叉不加 junction 就不连通；
    * 竖线的 x 逐引脚唯一且**离开 2.54 网格**（桩长带唯一偏移），所以竖线不会穿过别人的
      引脚、也不会与别人的竖线共线；
    * 总线末端 trunk_x 校验过不与任何竖线 x 相同，因此水平段的端点只落在本网络线上；
    * 同一网络的水平段都在同一 y 上并共享总线端点，天然连通。

    对比：先试过「相邻引脚 L 形串联」，实测把 11 个网络**短接成 1 个**；再试「质心星形」，
    仍把 D1.2 串进了 GND。根因都是引脚全在 2.54 网格上，几何上极易共线/端点相撞，
    而 KiCad 把「端点落在导线上」按连通处理。
    """
    names = [n for n in sorted(net_pins) if not _is_nc(n)]
    pin_xs = {round(p[0], 4) for name in names for p in net_pins[name]}
    max_pin_y = max((p[1] for name in names for p in net_pins[name]), default=0.0)
    lane0 = round(max_pin_y + 25.4, 4)          # 所有通道线落在全部符号下方
    used_vx: set = set()

    # 1) 先统一分配每个引脚的竖线 x：唯一、且不等于任何引脚的 x
    vx_of: dict = {}
    for name in names:
        for i, (px, _py, rot) in enumerate(net_pins[name]):
            d = -1.0 if rot == 0 else 1.0
            length = 2.54
            vx = round(px + d * length, 4)
            guard = 0
            while (vx in used_vx or vx in pin_xs) and guard < 400:
                guard += 1
                length = round(length + 0.1, 4)
                vx = round(px + d * length, 4)
            used_vx.add(vx)
            vx_of[(name, i)] = vx

    # 2) 逐网络生成梳形：桩 + 竖 + 横(汇入总线)
    out: list = []
    for k, name in enumerate(names):
        pts = net_pins[name]
        if len(pts) < 2:
            continue
        lane_y = round(lane0 + k * 2.54, 4)
        vxs = [vx_of[(name, i)] for i in range(len(pts))]
        trunk_x = round(max(vxs) + 5.08, 4)
        guard = 0
        while trunk_x in used_vx and guard < 400:
            guard += 1
            trunk_x = round(trunk_x + 0.1, 4)

        segs: list = []
        junc: list = []
        for i, (px, py, _rot) in enumerate(pts):
            vx = vx_of[(name, i)]
            segs.append(((px, py), (vx, py)))                  # 朝外短桩
            segs.append(((vx, py), (vx, lane_y)))              # 竖直下到通道
            segs.append(((vx, lane_y), (trunk_x, lane_y)))     # 水平汇入总线
            junc.append((vx, lane_y))
        junc.append((trunk_x, lane_y))
        out.append((name, segs, junc, (trunk_x, lane_y)))

    # 3) 自检：任何端点都不允许落在**别的网络**的线段内部（否则会被短接）
    flat = [(nm, s) for nm, segs, _j, _a in out for s in segs]
    for i, (n1, s1) in enumerate(flat):
        for n2, s2 in flat[i + 1:]:
            if n1 != n2 and _segs_conflict(s1, s2):
                raise StageError(
                    "SCHEMATIC_ROUTE_CONFLICT", "schematic",
                    f"原理图布线自检失败：{n1} {s1} 与 {n2} {s2} 会短接",
                )
    return out


def _wires_xml(net_pins: dict) -> str:
    """输出 (wire ...) + (junction ...) + 每条网络一个 global_label。

    未连接引脚（skidl 里挂在 NC 网络上的）用 KiCad 的 (no_connect ...) 标记，
    而不是拿导线把几十个无关引脚串成一个假网络。
    """
    blocks: list = []
    for name in sorted(net_pins):
        if _is_nc(name):
            for (x, y, _rot) in net_pins[name]:
                blocks.append(
                    f'  (no_connect (at {_n(x)} {_n(y)}) (uuid "{uuid.uuid4()}"))'
                )

    for (name, segs, junc, anchor) in _route_nets(net_pins):
        for (a, b) in segs:
            blocks.append(
                f'  (wire (pts (xy {_n(a[0])} {_n(a[1])}) (xy {_n(b[0])} {_n(b[1])}))\n'
                f'    (stroke (width 0) (type default))\n'
                f'    (uuid "{uuid.uuid4()}")\n'
                f'  )'
            )
        for (jx, jy) in junc:
            blocks.append(
                f'  (junction (at {_n(jx)} {_n(jy)}) (diameter 0) (color 0 0 0 0)\n'
                f'    (uuid "{uuid.uuid4()}")\n'
                f'  )'
            )
        # 标签落在总线末端（本网络多条导线的共享端点），既命名网络又不会悬空
        ax, ay = anchor
        blocks.append(
            f'  (global_label "{name}" (shape input) (at {_n(ax)} {_n(ay)} 0) (fields_autoplaced yes)\n'
            f'    (effects (font (size 1.27 1.27)) (justify left))\n'
            f'    (uuid "{uuid.uuid4()}")\n'
            f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at 0 0 0) '
            f'(effects (font (size 1.27 1.27)) hide))\n'
            f'  )'
        )
    return "\n".join(blocks)


def _gen_kicad_sch(out_dir: Path, parts: list) -> None:
    # key → reference 前缀（取该库首个实例的 ref 首字母）
    used: dict[str, str] = {}
    for p in parts:
        _k = _part_key(p)
        if _k:
            used.setdefault(_k, (p.ref or "U")[0])
    root_uuid = str(uuid.uuid4())
    content = (
        '(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")\n'
        f'  (uuid "{root_uuid}")\n'
        '  (paper "A4")\n'
        '  (title_block (title "VibePCB generated schematic") (company "VibePCB"))\n'
        + _lib_symbols_xml(used) + "\n"
        + _sch_symbol_instances(parts, root_uuid) + "\n"
        + _wires_xml(_collect_net_pins(parts)) + "\n"
        '  (sheet_instances (path "/" (page "1")))\n'
        ")\n"
    )
    (out_dir / "project.kicad_sch").write_text(content, encoding="utf-8")


def run_schematic(ws: ProjectWorkspace) -> dict[str, Any]:
    """执行 schematic 阶段，返回响应 dict。"""
    spec = json.loads((ws.root / "in" / "spec.json").read_text(encoding="utf-8"))
    bom = json.loads((ws.root / "in" / "bom.json").read_text(encoding="utf-8"))

    _reset_skidl()
    _, nets, parts = _build_circuit(spec, bom)
    erc = _erc_report()
    netlist_summary = _gen_netlist(ws.out_dir)
    net_names = sorted({n.name for n in nets.values()})
    _gen_kicad_sch(ws.out_dir, parts)

    files = [
        ws.register_artifact("out/project.net", "netlist"),
        ws.register_artifact("out/project.kicad_sch", "schematic"),
    ]
    return {
        "stage": "schematic", "engine": "skidl+kiutils", "degraded": False,
        "files": files, "erc": erc, "netlist_summary": netlist_summary,
        "note": "网表是权威产物；.kicad_sch 为骨架文件（符号位置+网络标签），可在 KiCad 中打开后微调",
    }
