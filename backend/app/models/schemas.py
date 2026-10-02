"""Pydantic 模型：第 4 章全部 JSON 契约。

阶段响应统一带 engine / degraded 字段（文档 5.3 约定）。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------- 基础 ----------

class HealthResponse(BaseModel):
    status: str
    version: str


class KicadCapability(BaseModel):
    installed: bool = False
    version: Optional[str] = None
    pcbnew_importable: bool = False
    kicad_cli: Optional[str] = None


class DeepSeekCapability(BaseModel):
    configured: bool
    model: str


class CapabilitiesResponse(BaseModel):
    kicad: KicadCapability
    pcb_engine_active: str
    deepseek: DeepSeekCapability


class ErrorBody(BaseModel):
    code: str
    stage: Optional[str] = None
    message: str
    fallback_used: Optional[str] = None
    hint: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------- 项目 ----------

class ProjectCreateRequest(BaseModel):
    name: Optional[str] = None
    prompt: str = Field(min_length=1, max_length=4000)


class StageInfo(BaseModel):
    status: str = "pending"  # pending | running | done | failed
    engine: Optional[str] = None
    degraded: Optional[bool] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class ProjectCreateResponse(BaseModel):
    project_id: str
    name: str
    status: str
    stages: dict[str, str]


class ProjectDetail(BaseModel):
    project_id: str
    name: str
    overall: str  # created | running | done | failed
    current_stage: Optional[str] = None
    prompt: Optional[str] = None
    stages: dict[str, dict[str, Any]]


class ProjectSummary(BaseModel):
    project_id: str
    name: str
    overall: str
    current_stage: Optional[str] = None
    created_at: str


# ---------- parse ----------

class Mcu(BaseModel):
    family: str = "ESP32"
    module: str = "ESP32-WROOM-32E"


class SensorItem(BaseModel):
    type: str
    part: str
    interface: str


class ActuatorItem(BaseModel):
    type: str
    driver: Optional[str] = None
    part: Optional[str] = None
    interface: Optional[str] = None


class DisplayItem(BaseModel):
    part: str
    interface: str


class Power(BaseModel):
    input: str = "5V USB"
    rail_3v3: str = "AMS1117-3.3"


class RequirementSpec(BaseModel):
    product_name: str
    summary: str = ""
    mcu: Mcu = Mcu()
    features: list[str] = []
    sensors: list[SensorItem] = []
    actuators: list[ActuatorItem] = []
    displays: list[DisplayItem] = []
    interfaces: list[str] = []
    power: Power = Power()


class ParseRequest(BaseModel):
    prompt: Optional[str] = None


class ParseResponse(BaseModel):
    stage: str = "parse"
    engine: str
    degraded: bool
    spec: RequirementSpec


# ---------- components ----------

class BomComponent(BaseModel):
    ref: str
    value: str
    qty: int = 1
    symbol: str
    footprint: str
    description: str = ""


class ComponentsResponse(BaseModel):
    stage: str = "components"
    engine: str
    degraded: bool
    components: list[BomComponent]
    nets_expected: list[str] = []
    warnings: list[str] = []


# ---------- schematic ----------

class ArtifactFile(BaseModel):
    path: str
    kind: str
    sha256: str
    size: int


class ErcReport(BaseModel):
    errors: int = 0
    warnings: int = 0
    details: list[str] = []


class SchematicResponse(BaseModel):
    stage: str = "schematic"
    engine: str
    degraded: bool
    files: list[ArtifactFile]
    erc: ErcReport
    netlist_summary: dict[str, int]
    note: str = ""


# ---------- pcb ----------

class PcbResponse(BaseModel):
    stage: str = "pcb"
    engine: str
    degraded: bool
    board_file: str
    layout: dict[str, Any]
    routing: dict[str, Any]
    drc: dict[str, Any]
    note: str = ""


# ---------- firmware ----------

class FirmwareFile(BaseModel):
    path: str
    language: str
    lines: int
    sha256: str


class FirmwareSelfCheck(BaseModel):
    balanced_braces: bool
    balanced_quotes: bool
    includes_resolved: bool


class FirmwareResponse(BaseModel):
    stage: str = "firmware"
    engine: str
    degraded: bool
    framework: str = "arduino"
    entry: str
    files: list[FirmwareFile]
    self_check: FirmwareSelfCheck
    note: str = ""


# ---------- gerber ----------

class GerberResponse(BaseModel):
    stage: str = "gerber"
    engine: str
    degraded: bool
    zip: str
    files: list[str]


# ---------- pipeline ----------

class PipelineRequest(BaseModel):
    stages: list[str] = Field(default_factory=lambda: ["all"])
