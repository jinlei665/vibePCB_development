# -*- coding: utf-8 -*-
"""PCB 板模型读取与编辑写回（CAD 化增量 3）。

前端画布叠加层需要两件事，都在这里：

* `board_model()` —— 把 .kicad_pcb 读成**画布友好的 JSON**（器件/焊盘/走线/过孔/板框）；
* `apply_edits()`  —— 应用一批编辑（移动器件、增删走线与过孔…）并**写回 KiCad 原生
  .kicad_pcb**（用 pcbnew.SaveBoard），然后返回新模型。

设计约束（与路线图一致）：不引入私有格式，所有编辑最终落在 KiCad 原生文件上，
因此"在 KiCad 中打开继续精修"这条轨始终成立。

pcbnew 里 GUID 的取法与本机实测一致：**没有 GetUuid()**，只有 `item.m_Uuid`（KIID），
`str(item.m_Uuid.AsString())` 即为稳定 id。
"""
from __future__ import annotations

import logging
import shutil
from typing import Any

from ..core.errors import StageError
from ..core.workspace import ProjectWorkspace

logger = logging.getLogger("vibepcb.board")

BOARD_REL = "out/project.kicad_pcb"
BACKUP_REL = "out/.board_backup.kicad_pcb"

# 编辑允许的图层（MVP：双面板）
ALLOWED_LAYERS = ("F.Cu", "B.Cu")
WIDTH_RANGE = (0.05, 5.0)
COORD_LIMIT = 2000.0     # mm，防止误传像素值把板子甩到天边


def _pcbnew():
    try:
        import pcbnew

        return pcbnew
    except Exception as exc:  # noqa: BLE001
        raise StageError("RENDER_UNAVAILABLE", "board",
                         f"pcbnew 不可用，无法读写板文件：{exc}") from exc


def _mm(v) -> float:
    return round(float(v), 4)


def _xy(pcbnew, pt) -> list:
    return [_mm(pcbnew.ToMM(pt.x)), _mm(pcbnew.ToMM(pt.y))]


def _pt(pcbnew, x: float, y: float):
    return pcbnew.VECTOR2I(pcbnew.FromMM(float(x)), pcbnew.FromMM(float(y)))


def _uid(item) -> str:
    try:
        return str(item.m_Uuid.AsString())
    except Exception:  # noqa: BLE001
        return ""


def _board_path(ws: ProjectWorkspace):
    p = ws.abs(BOARD_REL)
    if not p.exists():
        raise StageError("STAGE_PREREQ_MISSING", "board",
                         "缺少 project.kicad_pcb，请先完成 pcb 阶段")
    return p


def _pad_side(pcbnew, pad) -> str:
    try:
        return "B" if pad.IsOnLayer(pcbnew.B_Cu) else "F"
    except Exception:  # noqa: BLE001
        return "F"


def board_model(ws: ProjectWorkspace) -> dict[str, Any]:
    """读板 → 画布模型。坐标单位统一 mm，原点为图纸左上（KiCad 页面坐标）。"""
    pcbnew = _pcbnew()
    board = pcbnew.LoadBoard(str(_board_path(ws)))

    footprints = []
    for fp in board.GetFootprints():
        bb = fp.GetBoundingBox()
        pads = []
        for pad in fp.Pads():
            pos = pad.GetPosition()
            size = pad.GetSize()
            pads.append({
                "num": str(pad.GetNumber()),
                "x": _mm(pcbnew.ToMM(pos.x)),
                "y": _mm(pcbnew.ToMM(pos.y)),
                "w": _mm(pcbnew.ToMM(size.x)),
                "h": _mm(pcbnew.ToMM(size.y)),
                "shape": int(pad.GetShape()),
                "side": _pad_side(pcbnew, pad),
                "net": str(pad.GetNetname() or ""),
            })
        footprints.append({
            "ref": str(fp.GetReference()),
            "value": str(fp.GetValue()),
            "x": _mm(pcbnew.ToMM(fp.GetPosition().x)),
            "y": _mm(pcbnew.ToMM(fp.GetPosition().y)),
            "rot": round(float(fp.GetOrientationDegrees()), 3),
            "bbox": [_mm(pcbnew.ToMM(bb.GetLeft())), _mm(pcbnew.ToMM(bb.GetTop())),
                     _mm(pcbnew.ToMM(bb.GetRight())), _mm(pcbnew.ToMM(bb.GetBottom()))],
            "pads": pads,
        })

    tracks, vias = [], []
    for t in board.GetTracks():
        net = str(t.GetNetname() or "")
        if isinstance(t, pcbnew.PCB_VIA):
            pos = t.GetPosition()
            # KiCad 10 的坑：PCB_VIA::GetWidth() **不带图层参数会触发 C++ assert 并直接
            # abort 整个进程**（pcb_track.cpp:387 "GetWidth called without a layer
            # argument"，本机实测把后端进程打挂）。必须用 GetFrontWidth()。
            vias.append({
                "id": _uid(t), "net": net,
                "x": _mm(pcbnew.ToMM(pos.x)), "y": _mm(pcbnew.ToMM(pos.y)),
                "size": _mm(pcbnew.ToMM(t.GetFrontWidth())),
                "drill": _mm(pcbnew.ToMM(t.GetDrillValue())),
            })
        else:
            tracks.append({
                "id": _uid(t), "net": net,
                "layer": board.GetLayerName(t.GetLayer()),
                "start": _xy(pcbnew, t.GetStart()),
                "end": _xy(pcbnew, t.GetEnd()),
                "width": _mm(pcbnew.ToMM(t.GetWidth())),
            })

    outline = []
    for d in board.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts:
            continue
        # 只取直线段；圆弧等图元语义不同，先不混进画布（避免画成错误的直线）
        if getattr(d, "GetShape", None) and d.GetShape() != pcbnew.SHAPE_T_SEGMENT:
            continue
        try:
            outline.append({"start": _xy(pcbnew, d.GetStart()),
                            "end": _xy(pcbnew, d.GetEnd())})
        except Exception:  # noqa: BLE001
            continue

    bb = board.GetBoardEdgesBoundingBox()
    bbox = [_mm(pcbnew.ToMM(bb.GetLeft())), _mm(pcbnew.ToMM(bb.GetTop())),
            _mm(pcbnew.ToMM(bb.GetRight())), _mm(pcbnew.ToMM(bb.GetBottom()))]
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        bbox = [0.0, 0.0, 100.0, 100.0]

    return {
        "units": "mm",
        "bbox": bbox,
        "outline": outline,
        "nets": sorted(str(n) for n in board.GetNetsByName().keys() if str(n)),
        "footprints": footprints,
        "tracks": tracks,
        "vias": vias,
        "counts": {
            "footprints": len(footprints),
            "tracks": len(tracks),
            "vias": len(vias),
        },
    }


# ---------------------------------------------------------------- 编辑


def _check_coord(x, y) -> tuple:
    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        raise StageError("INVALID_INPUT", "board", f"坐标非法: {x!r}, {y!r}")
    if abs(fx) > COORD_LIMIT or abs(fy) > COORD_LIMIT:
        raise StageError("INVALID_INPUT", "board", f"坐标超出合理范围: {fx}, {fy}")
    return fx, fy


def _check_width(w) -> float:
    try:
        fw = float(w)
    except (TypeError, ValueError):
        raise StageError("INVALID_INPUT", "board", f"线宽非法: {w!r}")
    if not (WIDTH_RANGE[0] <= fw <= WIDTH_RANGE[1]):
        raise StageError("INVALID_INPUT", "board", f"线宽需在 {WIDTH_RANGE} mm 内: {fw}")
    return fw


def _check_layer(board, layer) -> int:
    if layer not in ALLOWED_LAYERS:
        raise StageError("INVALID_INPUT", "board", f"仅支持图层 {ALLOWED_LAYERS}: {layer!r}")
    lid = board.GetLayerID(layer)
    if lid < 0:
        raise StageError("INVALID_INPUT", "board", f"未知图层: {layer!r}")
    return lid


def _netcode(board, net: str) -> int:
    if not net:
        return 0
    info = board.FindNet(str(net))
    if info is None:
        raise StageError("INVALID_INPUT", "board", f"网络上不存在: {net!r}")
    return info.GetNetCode()


def _find_track(board, uid: str):
    for t in board.GetTracks():
        if _uid(t) == uid:
            return t
    return None


def _find_footprint(board, ref: str):
    for fp in board.GetFootprints():
        if str(fp.GetReference()) == str(ref):
            return fp
    return None


def apply_edits(ws: ProjectWorkspace, edits: list) -> dict[str, Any]:
    """应用一批编辑并写回 .kicad_pcb。返回 {"applied": n, "board": 新模型}。

    编辑是"整批原子"的：任何一条非法都会抛错且**不会落盘**（先校验后保存），
    避免把板子改坏到一半。写盘前会留一份 .board_backup.kicad_pcb 供 revert。
    """
    if not isinstance(edits, list) or not edits:
        raise StageError("INVALID_INPUT", "board", "edits 必须是非空数组")

    pcbnew = _pcbnew()
    path = _board_path(ws)
    board = pcbnew.LoadBoard(str(path))
    applied = 0

    for e in edits:
        if not isinstance(e, dict):
            raise StageError("INVALID_INPUT", "board", f"编辑项必须是对象: {e!r}")
        op = str(e.get("op") or "")

        if op == "move_footprint":
            fp = _find_footprint(board, e.get("ref"))
            if fp is None:
                raise StageError("INVALID_INPUT", "board", f"器件不存在: {e.get('ref')!r}")
            x, y = _check_coord(e.get("x"), e.get("y"))
            fp.SetPosition(_pt(pcbnew, x, y))
            if e.get("rot") is not None:
                fp.SetOrientationDegrees(float(e["rot"]))

        elif op == "add_track":
            lid = _check_layer(board, e.get("layer"))
            x1, y1 = _check_coord(*e.get("start") or (None, None))
            x2, y2 = _check_coord(*e.get("end") or (None, None))
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(_pt(pcbnew, x1, y1))
            t.SetEnd(_pt(pcbnew, x2, y2))
            t.SetWidth(pcbnew.FromMM(_check_width(e.get("width", 0.25))))
            t.SetLayer(lid)
            t.SetNetCode(_netcode(board, e.get("net", "")))
            board.Add(t)

        elif op == "add_via":
            x, y = _check_coord(e.get("x"), e.get("y"))
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(_pt(pcbnew, x, y))
            v.SetWidth(pcbnew.FromMM(_check_width(e.get("size", 0.6))))
            v.SetDrill(pcbnew.FromMM(_check_width(e.get("drill", 0.3))))
            v.SetNetCode(_netcode(board, e.get("net", "")))
            if hasattr(v, "SetViaType"):
                try:
                    v.SetViaType(pcbnew.VIATYPE_THROUGH)
                    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                except Exception:  # noqa: BLE001  不同版本枚举名可能不同
                    pass
            board.Add(v)

        elif op == "move_track":
            t = _find_track(board, e.get("id"))
            if t is None:
                raise StageError("INVALID_INPUT", "board", f"对象不存在: {e.get('id')!r}")
            is_via = isinstance(t, pcbnew.PCB_VIA)
            if "start" in e and "end" in e:
                if is_via:
                    raise StageError("INVALID_INPUT", "board",
                                     "过孔只能平移（用 dx/dy），不能设起终点")
                x1, y1 = _check_coord(*e["start"])
                x2, y2 = _check_coord(*e["end"])
                t.SetStart(_pt(pcbnew, x1, y1))
                t.SetEnd(_pt(pcbnew, x2, y2))
            else:
                dx, dy = _check_coord(e.get("dx", 0), e.get("dy", 0))
                if is_via:
                    # 过孔没有 Start/End，只有 Position
                    p = t.GetPosition()
                    t.SetPosition(_pt(pcbnew, pcbnew.ToMM(p.x) + dx, pcbnew.ToMM(p.y) + dy))
                else:
                    s, en = t.GetStart(), t.GetEnd()
                    t.SetStart(_pt(pcbnew, pcbnew.ToMM(s.x) + dx, pcbnew.ToMM(s.y) + dy))
                    t.SetEnd(_pt(pcbnew, pcbnew.ToMM(en.x) + dx, pcbnew.ToMM(en.y) + dy))

        elif op == "delete_item":
            t = _find_track(board, e.get("id"))
            if t is None:
                raise StageError("INVALID_INPUT", "board", f"对象不存在: {e.get('id')!r}")
            board.Remove(t)

        elif op == "set_track_width":
            t = _find_track(board, e.get("id"))
            if t is None:
                raise StageError("INVALID_INPUT", "board", f"对象不存在: {e.get('id')!r}")
            if isinstance(t, pcbnew.PCB_VIA):
                # 过孔宽度在 KiCad 10 里按图层处理，直接改有触发 assert 的风险；
                # 让它走「删除 + 重新新增」这条明确路径，避免把服务进程打挂。
                raise StageError("INVALID_INPUT", "board",
                                 "过孔尺寸不支持直接修改，请删除后重新新增")
            t.SetWidth(pcbnew.FromMM(_check_width(e.get("width"))))

        else:
            raise StageError("INVALID_INPUT", "board", f"未知编辑操作: {op!r}")

        applied += 1

    # 校验全部通过后才落盘：先备份，再保存
    backup = ws.abs(BACKUP_REL)
    try:
        shutil.copyfile(path, backup)
    except Exception as exc:  # noqa: BLE001
        logger.warning("board backup failed: %s", exc)
    pcbnew.SaveBoard(str(path), board)

    logger.info("board edits applied: %d", applied)
    return {"applied": applied, "board": board_model(ws)}


def revert_board(ws: ProjectWorkspace) -> dict[str, Any]:
    """从上一次编辑前的备份恢复板文件。"""
    path = _board_path(ws)
    backup = ws.abs(BACKUP_REL)
    if not backup.exists():
        raise StageError("INVALID_INPUT", "board", "没有可恢复的备份（尚未进行过编辑）")
    shutil.copyfile(backup, path)
    logger.info("board reverted from backup")
    return {"reverted": True, "board": board_model(ws)}
