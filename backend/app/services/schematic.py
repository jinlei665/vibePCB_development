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
        lines = [
            f'    (symbol "{lib_id}" (pin_names (offset 1.016)) (in_bom yes) (on_board yes)',
            f'      (property "Reference" "{prefix}" (at 0 0 0) (effects (font (size 1.27 1.27))))',
            f'      (property "Value" "{name}" (at 0 0 0) (effects (font (size 1.27 1.27))))',
            '      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
            '      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
            f'      (symbol "{name}_0_1"',
            '        (rectangle (start -7.62 10.16) (end 7.62 -10.16) (stroke (width 0.254) (type default)) (fill (type background)))',
            "      )",
            f'      (symbol "{name}_1_1"',
        ]
        n = len(info["pins"])
        for i, pin in enumerate(info["pins"]):
            y = 7.62 - (i % max(1, (n // 2 + 1))) * 2.54
            x = -10.16 if i < (n + 1) // 2 else 10.16
            rot = 0 if i < (n + 1) // 2 else 180
            # 注意：lib_symbols 里的 pin **不能**带 (uuid ...)。KiCad 的 .kicad_sch
            # 解析器只允许符号实例里的 (pin "1" (uuid ...))，库定义里多一个 uuid 会
            # 直接 "加载原理图失败"（exit 3）—— 本机用二分法定位到此处（质检 D14）。
            lines.append(
                f'        (pin {pin["func"]} line (at {x} {y} {rot}) (length 2.54) '
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
    for idx, p in enumerate(parts):
        col = idx % 4
        row = idx // 4
        x = 60.96 + col * 40.64
        y = 60.96 + row * 30.48
        info_lib = next(
            (PARTS[k]["symbol"] for k in PARTS if PARTS[k]["symbol"].endswith(p.name)),
            p.name,
        )
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


def _sch_labels(net_names: list[str]) -> str:
    """网络标签列（右侧一列）。"""
    blocks = []
    for i, name in enumerate(net_names):
        x, y = 210.82, 40.64 + i * 10.16
        blocks.append(
            f'  (global_label "{name}" (shape input) (at {x} {y} 0) (fields_autoplaced yes)\n'
            f'    (effects (font (size 1.27 1.27)) (justify left))\n'
            f'    (uuid "{uuid.uuid4()}")\n'
            f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n'
            f'  )'
        )
    return "\n".join(blocks)


def _gen_kicad_sch(out_dir: Path, parts: list, net_names: list[str]) -> None:
    # key → reference 前缀（取该库首个实例的 ref 首字母）
    used: dict[str, str] = {}
    for p in parts:
        for k, info in PARTS.items():
            if info["symbol"].endswith(p.name) or p.name == k:
                used.setdefault(k, (p.ref or "U")[0])
                break
    root_uuid = str(uuid.uuid4())
    content = (
        '(kicad_sch (version 20231120) (generator "eeschema") (generator_version "8.0")\n'
        f'  (uuid "{root_uuid}")\n'
        '  (paper "A4")\n'
        '  (title_block (title "VibePCB generated schematic") (company "VibePCB"))\n'
        + _lib_symbols_xml(used) + "\n"
        + _sch_symbol_instances(parts, root_uuid) + "\n"
        + _sch_labels(net_names) + "\n"
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
    _gen_kicad_sch(ws.out_dir, parts, net_names)

    files = [
        ws.register_artifact("out/project.net", "netlist"),
        ws.register_artifact("out/project.kicad_sch", "schematic"),
    ]
    return {
        "stage": "schematic", "engine": "skidl+kiutils", "degraded": False,
        "files": files, "erc": erc, "netlist_summary": netlist_summary,
        "note": "网表是权威产物；.kicad_sch 为骨架文件（符号位置+网络标签），可在 KiCad 中打开后微调",
    }
