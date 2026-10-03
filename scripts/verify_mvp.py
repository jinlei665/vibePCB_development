# -*- coding: utf-8 -*-
"""VibePCB MVP 五步验收脚本。

按需求给出的 MVP 优先级逐条做**可执行断言**：

  ① 能输入文字，调用 AI 解析需求
  ② 能根据解析结果生成 KiCad 原理图脚本
  ③ 能生成 ESP32 固件代码
  ④ 能导出 Gerber 文件
  ⑤ 前端界面所依赖的接口契约（实时进度 + 全阶段产物可取回）

运行（仓库根目录）：
    .venv\\Scripts\\python.exe scripts\\verify_mvp.py

退出码 0 = 全部通过；非 0 = 有 FAIL。
前置：已按 requirements.txt 装好后端依赖。本脚本无需事先启动服务（用 TestClient）。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# 用独立数据目录，避免污染真实的 ~/.vibepcb
os.environ.setdefault("VIBEPCB_DATA_DIR", tempfile.mkdtemp(prefix="vibepcb_mvp_"))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

PROMPT = "做一个ESP32温控器：DS18B20测温，MOSFET控制加热片，OLED显示温度，WiFi上报MQTT"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "|", name, ("| " + str(detail) if detail else ""))
    return bool(cond)


def main() -> int:
    c = TestClient(app)

    print(f"data dir  : {settings.projects_dir}")
    print(f"deepseek  : {'configured' if settings.deepseek_configured else 'MISSING (降级路径)'}")
    caps = c.get("/api/capabilities").json()
    print(f"pcb engine: {caps['pcb_engine_selected']} (pcbnew={caps['pcbnew_available']}, "
          f"kicad-cli={caps['kicad_cli_available']})\n")

    # ---------------- 创建项目 ----------------
    r = c.post("/api/projects", json={"name": "mvp", "prompt": PROMPT})
    check("创建项目 201", r.status_code == 201, f"status={r.status_code}")
    proj = r.json()
    pid = proj["project_id"]
    check("① prompt 端到端 UTF-8 无损（中文未被破坏）",
          proj.get("prompt") == PROMPT, json.dumps(proj.get("prompt"), ensure_ascii=True)[:80])

    # ---------------- ⑤ 前端契约：后台流水线 + 实时进度 ----------------
    t0 = time.time()
    r = c.post(f"/api/projects/{pid}/pipeline?background=1", json={"stages": ["all"]})
    dt = time.time() - t0
    check("⑤ pipeline?background=1 立即返回 202（不阻塞）",
          r.status_code == 202 and dt < 1.0, f"status={r.status_code} elapsed={dt:.3f}s")

    seen: list = []
    deadline = time.time() + 300
    while time.time() < deadline:
        st = c.get(f"/api/projects/{pid}").json()
        cur = st.get("overall")
        if not seen or seen[-1] != cur:
            seen.append(cur)
        if cur in ("done", "failed"):
            break
        time.sleep(0.15)
    check("⑤ 轮询能观察到中间态 running（进度实时可见）",
          "running" in seen, f"状态序列={seen}")

    detail = c.get(f"/api/projects/{pid}").json()
    check("⑤ 流水线终止于 done", detail.get("overall") == "done",
          f"overall={detail.get('overall')}")
    stages = detail["stages"]

    # ---------------- ① 需求解析 ----------------
    parse = stages["parse"]
    check("① parse 阶段完成", parse.get("status") == "done",
          f"status={parse.get('status')} error={parse.get('error')}")
    parsed = c.get(f"/api/projects/{pid}/artifacts/parse").json().get("artifacts", [])
    check("① spec.json 已登记为产物", any(a["kind"] == "spec" for a in parsed),
          f"kinds={[a['kind'] for a in parsed]}")
    spec_txt = c.get(f"/api/projects/{pid}/artifacts/parse", params={"path": "in/spec.json"}).text
    spec = json.loads(spec_txt)
    check("① spec.product_name 非空", bool(spec.get("product_name", "").strip()),
          json.dumps(spec.get("product_name"), ensure_ascii=True)[:60])
    check("① 关键词解析命中（DS18B20 温度传感器）",
          any("DS18B20" in (s.get("part") or "") for s in spec.get("sensors", [])),
          json.dumps(spec.get("sensors"), ensure_ascii=True)[:100])
    check("① 关键词解析命中（OLED 显示）",
          any("SSD1306" in (d.get("part") or "") for d in spec.get("displays", [])),
          json.dumps(spec.get("displays"), ensure_ascii=True)[:100])
    check("① 关键词解析命中（MOSFET/加热执行器）",
          any(a.get("type") in ("heater_plate", "fan") or "AO3400" in str(a)
              for a in spec.get("actuators", [])),
          json.dumps(spec.get("actuators"), ensure_ascii=True)[:100])
    if settings.deepseek_configured:
        check("① 已配 Key 时走真实 DeepSeek 链路",
              parse.get("engine") == "deepseek" and parse.get("degraded") is False,
              f"engine={parse.get('engine')} degraded={parse.get('degraded')}")
    else:
        check("① 未配 Key 时明确降级为规则引擎（而非报错/静默）",
              parse.get("engine") == "rule-based" and parse.get("degraded") is True,
              f"engine={parse.get('engine')} degraded={parse.get('degraded')}")

    # ---------------- ② 原理图 / 网表 ----------------
    comp = stages["components"]
    check("② components 阶段完成", comp.get("status") == "done",
          f"status={comp.get('status')} error={comp.get('error')}")
    comp_arts = c.get(f"/api/projects/{pid}/artifacts/components").json().get("artifacts", [])
    check("② bom.json 已登记为产物", any(a["kind"] == "bom" for a in comp_arts),
          f"kinds={[a['kind'] for a in comp_arts]}")

    sch = stages["schematic"]
    check("② schematic 阶段完成且未降级", sch.get("status") == "done" and sch.get("degraded") is False,
          f"status={sch.get('status')} engine={sch.get('engine')} error={sch.get('error')}")
    sch_res = sch.get("result", {})
    check("② ERC 零错误", (sch_res.get("erc", {}) or {}).get("errors", -1) == 0,
          json.dumps(sch_res.get("erc", {}), ensure_ascii=True)[:120])
    net_sum = sch_res.get("netlist_summary", {}) or {}
    check("② 网表含元件与网络", net_sum.get("parts", 0) > 0 and net_sum.get("nets", 0) > 0,
          json.dumps(net_sum))
    sch_arts = c.get(f"/api/projects/{pid}/artifacts/schematic").json().get("artifacts", [])
    kinds = {a["kind"] for a in sch_arts}
    check("② 网表 + .kicad_sch 骨架都已登记", {"netlist", "schematic"} <= kinds, f"kinds={sorted(kinds)}")
    net_txt = c.get(f"/api/projects/{pid}/artifacts/schematic",
                    params={"path": "out/project.net"}).text
    check("② 网表内容非空且格式正确", "(export" in net_txt and "(net " in net_txt.replace("\n", " "),
          f"{len(net_txt)} chars")

    # ---------------- ③ 固件 ----------------
    fw = stages["firmware"]
    check("③ firmware 阶段完成", fw.get("status") == "done",
          f"status={fw.get('status')} error={fw.get('error')}")
    sc = fw.get("result", {}).get("self_check", {}) or {}
    # 实现的返回结构是 {"passed": bool, "checks": [{"name","passed","detail"}]}；
    # models/schemas.py 里原本声明的 balanced_braces/balanced_quotes/includes_resolved
    # 与实际不符（契约漂移），这里以实际实现为准，并兼容两种形状。
    if sc.get("checks"):
        sc_ok = bool(sc.get("passed")) and all(c.get("passed") for c in sc["checks"])
    else:
        sc_ok = bool(sc.get("balanced_braces") and sc.get("balanced_quotes")
                     and sc.get("includes_resolved"))
    check("③ 固件自检全过（括号/引号/结构/include）", sc_ok,
          json.dumps(sc, ensure_ascii=True)[:200])
    ino = c.get(f"/api/projects/{pid}/artifacts/firmware",
                params={"path": "firmware/main/main.ino"})
    check("③ main.ino 可查看", ino.status_code == 200 and "#include" in ino.text,
          f"status={ino.status_code} {len(ino.text)} chars")

    # ---------------- ④ Gerber ----------------
    pcb = stages["pcb"]
    check("④ pcb 阶段完成", pcb.get("status") == "done",
          f"status={pcb.get('status')} error={pcb.get('error')}")
    pcb_res = pcb.get("result", {}) or {}
    check("④ PCB 有走线（不是无布线的裸板）",
          (pcb_res.get("routing", {}) or {}).get("segments", 0) > 0,
          json.dumps(pcb_res.get("routing", {}), ensure_ascii=True)[:140])
    if pcb_res.get("degraded"):
        check("④ 降级时给出可读原因（degraded_reason）",
              bool(pcb_res.get("degraded_reason")), str(pcb_res.get("degraded_reason"))[:100])

    ger = stages["gerber"]
    check("④ gerber 阶段完成", ger.get("status") == "done",
          f"status={ger.get('status')} error={ger.get('error')}")
    ger_files = (ger.get("result", {}) or {}).get("files", [])
    for want in ("project-F_Cu.gbr", "project-B_Cu.gbr", "project-Edge_Cuts.gbr",
                 "project.drl", "gerbers.zip"):
        check(f"④ 产出 {want}", want in ger_files, f"files={ger_files}")
    zip_resp = c.get(f"/api/projects/{pid}/artifacts/gerber",
                     params={"path": "gerber/gerbers.zip", "download": 1})
    check("④ gerbers.zip 可下载", zip_resp.status_code == 200 and len(zip_resp.content) > 0,
          f"{len(zip_resp.content)} bytes")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_resp.content))
        names = zf.namelist()
    except Exception as exc:  # noqa: BLE001
        names = []
        check("④ gerbers.zip 是合法 zip", False, str(exc))
    else:
        check("④ gerbers.zip 是合法 zip 且含 Gerber+钻孔",
              any(n.endswith(".gbr") for n in names) and any(n.endswith(".drl") for n in names),
              f"{names}")
    fcu = c.get(f"/api/projects/{pid}/artifacts/gerber",
                params={"path": "gerber/project-F_Cu.gbr"}).text
    check("④ F.Cu 文件含 RS-274X aperture 定义", "%ADD" in fcu and "M02*" in fcu,
          f"{len(fcu)} chars")

    # ---------------- ⑤ 产物下载契约 ----------------
    all_arts = detail.get("artifacts", [])
    check("⑤ 全流程登记了 6 类产物（spec/bom/netlist/schematic/pcb/firmware/gerber 至少 7 条）",
          len(all_arts) >= 7, f"count={len(all_arts)}")

    failed = [r for r in RESULTS if not r[1]]
    print()
    print(f"===== {len(RESULTS) - len(failed)}/{len(RESULTS)} passed =====")
    if failed:
        print("FAILED:", ", ".join(f[0] for f in failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
