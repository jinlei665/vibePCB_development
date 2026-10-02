# -*- coding: utf-8 -*-
"""质检报告回归验证脚本（逐条对应质检 P1/P2/P3 断言建议）。

运行：python scripts/verify_fixes.py（仓库根目录，需 backend 依赖）
退出码 0 = 全部通过；非 0 = 存在失败项（输出 FAIL 行）。
"""
from __future__ import annotations

import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "|", name, ("| " + detail if detail else ""))


# ---------------------------------------------------------------- P1-1 API Token 鉴权
def test_api_token():
    # 用独立数据目录避免污染 ~/.vibepcb
    os.environ["VIBEPCB_DATA_DIR"] = tempfile.mkdtemp(prefix="vibepcb_verify_")
    from app.config import Settings, settings
    from fastapi.testclient import TestClient
    from app.main import app

    c = TestClient(app)

    # 未启用 token：本机模式直通
    settings.api_token = ""
    r = c.post("/api/projects", json={"name": "t", "prompt": "ESP32温控器"})
    check("P1-1a 未启用 token 时 /api/projects 直通(200/201)", r.status_code in (200, 201),
          f"status={r.status_code}")
    pid = r.json()["project_id"]

    # 启用 token：无凭据 401
    settings.api_token = "verify-secret-token"
    r = c.post("/api/projects", json={"name": "t", "prompt": "ESP32温控器"})
    check("P1-1b 无凭据 POST /api/projects → 401", r.status_code == 401, f"status={r.status_code}")
    r = c.get(f"/api/projects/{pid}")
    check("P1-1c 无凭据 GET 项目 → 401", r.status_code == 401, f"status={r.status_code}")

    # /api/health 放行
    r = c.get("/api/health")
    check("P1-1d health 放行", r.status_code == 200, f"status={r.status_code}")

    # X-API-Token 凭据
    r = c.post("/api/projects", json={"name": "t", "prompt": "ESP32温控器"},
               headers={"X-API-Token": "verify-secret-token"})
    check("P1-1e X-API-Token 凭据 → 通过", r.status_code in (200, 201), f"status={r.status_code}")

    # Bearer 凭据
    r = c.get("/api/capabilities", headers={"Authorization": "Bearer verify-secret-token"})
    check("P1-1f Bearer 凭据 → 通过", r.status_code == 200, f"status={r.status_code}")

    # 错误 token
    r = c.get("/api/capabilities", headers={"X-API-Token": "wrong"})
    check("P1-1g 错误 token → 401", r.status_code == 401, f"status={r.status_code}")

    settings.api_token = ""
    return pid


# ---------------------------------------------------------------- P1-2 项目 ID 加长
def test_project_id_length(pid: str):
    check("P1-2 项目 ID ≥ p_+16hex（token_hex(8)）",
          pid.startswith("p_") and len(pid) >= 17, f"id={pid}")


# ---------------------------------------------------------------- P1-3 CORS 收敛
def test_cors():
    from app.config import Settings
    default = Settings().cors_origins
    check("P1-3a 默认 CORS 不含通配 *（本机模式收敛）", "*" not in default, str(default))
    check("P1-3b 默认 CORS 含本机 dev origins",
          "http://localhost:5173" in default and "http://127.0.0.1:5173" in default, str(default))
    os.environ["VIBEPCB_CORS_ORIGINS"] = "https://a.example.com,https://b.example.com"
    custom = Settings().cors_origins
    check("P1-3c VIBEPCB_CORS_ORIGINS 显式配置生效",
          custom == ["https://a.example.com", "https://b.example.com"], str(custom))
    del os.environ["VIBEPCB_CORS_ORIGINS"]


# ---------------------------------------------------------------- P2-1 零长度走线段
def test_router_zero_length():
    from app.services.router import route_net, route_all

    # 质检复现场景：8 焊盘网络（idx%5==2 触发 offset=0）
    pads = [(x * 3.0, y * 2.5) for x, y in
            [(0, 0), (1, 1), (2, 0.5), (3, 1.5), (4, 0.2), (5, 1.8), (6, 0.8), (7, 1.2)]]
    rn = route_net("N", pads)
    zero = [s for s in rn.segments if s.start == s.end]
    check("P2-1a route_net 8 焊盘无零长度段", not zero,
          f"{len(zero)} zero-length segs" if zero else f"{len(rn.segments)} segs ok")

    # 大随机网络批量扫描
    import random
    random.seed(42)
    bad = 0
    for trial in range(200):
        n = random.randint(2, 20)
        pts = [(round(random.uniform(0, 100), 2), round(random.uniform(0, 100), 2))
               for _ in range(n)]
        # 去重坐标
        pts = list(dict.fromkeys(pts))
        if len(pts) < 2:
            continue
        rn2 = route_net("N", pts)
        bad += sum(1 for s in rn2.segments if s.start == s.end)
    check("P2-1b 200 组随机网络无零长度段", bad == 0, f"{bad} zero-length segs")

    # 过孔不落在焊盘中心（offset=0 分支无孔）
    rn3 = route_net("M", [(10.0, 10.0), (20.0, 15.0), (30.0, 12.0),
                          (40.0, 18.0), (50.0, 11.0), (60.0, 16.0)])
    via_on_pad = [v for v in rn3.vias
                  if any(abs(v.x - px) < 1e-6 and abs(v.y - py) < 1e-6 for px, py in
                         [(10.0, 10.0), (20.0, 15.0), (30.0, 12.0), (40.0, 18.0),
                          (50.0, 11.0), (60.0, 16.0)])]
    check("P2-1c 过孔不钻在焊盘中心", not via_on_pad,
          f"{len(via_on_pad)} vias on pads" if via_on_pad else f"{len(rn3.vias)} vias ok")


# ---------------------------------------------------------------- P2-2 schema 形状错误降级
def test_schema_degradation():
    from app.core.deepseek_client import deepseek_client, DeepSeekError
    from app.services import parser as parser_svc
    from app.services import selector as selector_svc
    from app.config import settings
    from app.core.workspace import create_project

    ws = create_project("schema 验证", "ESP32温控器 DS18B20 OLED")
    orig = deepseek_client.chat_json
    orig_key = settings.deepseek_api_key
    try:
        settings.deepseek_api_key = "fake-key-for-shape-test"

        # parse：sensors 为字符串（形状错误）→ 应降级 rule-based 而非 500
        deepseek_client.chat_json = (
            lambda *a, **kw: {"product_name": "x", "sensors": "DS18B20"}
        )
        res = parser_svc.run_parse(ws, "ESP32温控器")
        check("P2-2a parse 形状错误 → rule-based 降级",
              res["engine"] == "rule-based" and res["degraded"] is True,
              f"engine={res['engine']}")

        # parse：components 顶层非 dict
        deepseek_client.chat_json = lambda *a, **kw: [1, 2, 3]
        res = parser_svc.run_parse(ws, "ESP32温控器")
        check("P2-2b parse 顶层非对象 → rule-based 降级",
              res["engine"] == "rule-based" and res["degraded"] is True,
              f"engine={res['engine']}")

        # selector：components 为字符串 → 应降级 preset 而非 500
        deepseek_client.chat_json = lambda *a, **kw: {"components": "DS18B20"}
        spec = {"product_name": "t", "sensors": [{"part": "DS18B20"}]}
        res = selector_svc.run_components(ws, spec, "ESP32温控器")
        check("P2-2c components 形状错误 → preset 降级",
              res["engine"] == "footprint_map(preset)" and res["degraded"] is True,
              f"engine={res['engine']}")

        # selector：components 元素非 dict
        deepseek_client.chat_json = lambda *a, **kw: {"components": ["R1", 42]}
        res = selector_svc.run_components(ws, spec, "ESP32温控器")
        check("P2-2d components 元素非 dict → preset 降级",
              res["engine"] == "footprint_map(preset)" and res["degraded"] is True,
              f"engine={res['engine']}")
    finally:
        deepseek_client.chat_json = orig
        settings.deepseek_api_key = orig_key


# ---------------------------------------------------------------- P2-3 单阶段 prereq + 锁
def test_stage_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import pipeline as pipeline_svc

    c = TestClient(app)
    r = c.post("/api/projects", json={"name": "prereq验证", "prompt": "ESP32温控器"})
    pid = r.json()["project_id"]

    # 缺前置：parse 未跑直接 POST schematic → 404 STAGE_PREREQ_MISSING
    r = c.post(f"/api/projects/{pid}/schematic")
    body = r.json()
    check("P2-3a 缺前置 POST schematic → 404",
          r.status_code == 404 and body["detail"]["error"]["code"] == "STAGE_PREREQ_MISSING",
          f"status={r.status_code} code={body.get('detail',{}).get('error',{}).get('code')}")

    # 锁占用：手动持锁后单阶段请求 → 409 PROJECT_BUSY
    lock = pipeline_svc.try_acquire(pid)
    assert lock is not None
    try:
        r = c.post(f"/api/projects/{pid}/parse")
        body = r.json()
        check("P2-3b 项目锁占用时单阶段 → 409 PROJECT_BUSY",
              r.status_code == 409 and body["detail"]["error"]["code"] == "PROJECT_BUSY",
              f"status={r.status_code}")
    finally:
        lock.release()

    # 锁释放后单阶段正常执行
    r = c.post(f"/api/projects/{pid}/parse")
    check("P2-3c 锁释放后单阶段 parse 正常执行", r.status_code == 200, f"status={r.status_code}")
    return pid


# ---------------------------------------------------------------- P2-4 parse 重跑级联重置
def test_parse_cascade_reset(pid: str):
    from fastapi.testclient import TestClient
    from app.main import app

    c = TestClient(app)
    # 先跑完 components（parse 已在 P2-3c 完成）
    r = c.post(f"/api/projects/{pid}/components")
    check("P2-4a components 首跑正常", r.status_code == 200, f"status={r.status_code}")

    # 换新 prompt 重跑 pipeline all → parse 重跑 + spec 变化 → 下游应重置（非 skipped）
    r = c.post(f"/api/projects/{pid}/pipeline",
               json={"stages": ["all"], "prompt": "做一个ESP32气象站：DHT22测温湿度，OLED显示，WiFi上报MQTT"})
    d = r.json()
    pr = d.get("pipeline_results", {})
    comp = pr.get("components", {})
    skipped = comp.get("skipped") or comp.get("engine") == "cached"
    check("P2-4b 新 prompt 重跑后 components 非 skipped",
          r.status_code == 200 and not skipped,
          f"status={r.status_code} components.engine={comp.get('engine')}")

    # spec 确实变了（新需求已生效）
    st = c.get(f"/api/projects/{pid}").json()
    pname = (((st.get("stages", {}).get("parse", {}) or {}).get("result", {}) or {})
             .get("spec", {}) or {}).get("product_name", "")
    check("P2-4c 新 prompt 的 spec 生效", pname != "", f"product_name={pname!r}")


# ---------------------------------------------------------------- P2-5 路径前缀绕过
def test_path_escape():
    from app.core.workspace import create_project, WorkspaceError

    ws = create_project("路径验证", "ESP32温控器")
    # 兄弟目录前缀绕过（质检实锤用例）
    try:
        p = ws.abs("../p_abcsecret/out/secret.txt")
        check("P2-5 abs('../p_xxx/…') 拒绝", False, f"returned {p}")
    except WorkspaceError:
        check("P2-5 abs('../p_xxx/…') 拒绝（WorkspaceError）", True)
    # 正常路径仍可用
    p = ws.abs("out/project.kicad_pcb")
    check("P2-5b 合法路径正常返回", p == ws.root.resolve() / "out" / "project.kicad_pcb", str(p))
    # 根目录本身（边界）
    try:
        p = ws.abs(".")
        check("P2-5c 项目根目录放行", p == ws.root.resolve(), str(p))
    except WorkspaceError as e:
        check("P2-5c 项目根目录放行", False, str(e))


# ---------------------------------------------------------------- P3 RoundRect 矩形近似
def test_roundrect_gerber():
    # 单元级验证：roundrect 分支产生 R, 定义（通过源码行为测试）
    import inspect
    from app.services import gerber as gerber_svc
    src = inspect.getsource(gerber_svc)
    has_branch = 'pad.shape == "roundrect"' in src and src.index('pad.shape == "roundrect"') < src.index("circle 近似为圆")
    check("P3 roundrect 分支存在且走矩形定义", has_branch, "")

    # 端到端：跑一个真实项目 gerber，检查 .gbr 中 aperture 定义
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.post("/api/projects", json={"name": "rr验证", "prompt": "ESP32温控器 DS18B20 OLED"})
    pid = r.json()["project_id"]
    c.post(f"/api/projects/{pid}/pipeline", json={"stages": ["all"]})
    st = c.get(f"/api/projects/{pid}").json()
    root = Path(st.get("data_dir", "")) if st.get("data_dir") else None
    # 从项目目录找 gerber
    from app.config import settings as _s
    gdir = _s.projects_dir / pid / "gerber"
    gbr = (gdir / "project-F_Cu.gbr").read_text(encoding="utf-8") if (gdir / "project-F_Cu.gbr").exists() else ""
    # ESP32 模块焊盘是 rect/roundrect；SMD R/C 焊盘在 KiCad 快照中多为 rect
    check("P3b gerber 含矩形 aperture 定义（R,sxXsy）", "R," in gbr,
          f"R-defs={'R,' in gbr}, len={len(gbr)}")


def main():
    pid1 = test_api_token()
    test_project_id_length(pid1)
    test_cors()
    test_router_zero_length()
    test_schema_degradation()
    pid2 = test_stage_endpoint()
    test_parse_cascade_reset(pid2)
    test_path_escape()
    test_roundrect_gerber()

    failed = [r for r in RESULTS if not r[1]]
    print()
    print(f"===== {len(RESULTS) - len(failed)}/{len(RESULTS)} passed =====")
    if failed:
        print("FAILED:", ", ".join(f[0] for f in failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
