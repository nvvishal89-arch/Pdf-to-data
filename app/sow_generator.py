"""
Phase 3: SOW + Lifecycle Auto Generator (spec §10).
Stages: Machining → Carpentry → Metal → Assembly → Upholstery → Paint → Final Assembly → Packaging → Dispatch.
"""
from pydantic import BaseModel, Field

from app.schema import SQStructuredData

# Spec §10: Auto Lifecycle Flow
STAGE_ORDER = [
    "Machining",
    "Carpentry",
    "Metal",
    "Assembly",
    "Upholstery",
    "Paint",
    "Final Assembly",
    "Packaging",
    "Dispatch",
]


class StageStep(BaseModel):
    stage: str
    duration_days: float = 1.0
    dependencies: list[str] = Field(default_factory=list)
    skill: str = ""
    worker_count: int = 1


class ProductSOW(BaseModel):
    sr_no: int
    name: str
    stages: list[StageStep] = Field(default_factory=list)
    total_days: float = 0.0


class SOWOutput(BaseModel):
    project_name: str = ""
    products: list[ProductSOW] = Field(default_factory=list)
    stage_order: list[str] = Field(default_factory=lambda: STAGE_ORDER)


def _estimate_days_for_product(product) -> float:
    """Rough duration from product size/type (rule-based)."""
    days = 2.0
    if product.dimensions:
        # Very crude: more text/dimensions => more complex
        days += min(5, len(product.dimensions) / 20)
    days += (product.qty or 1) * 0.5
    return round(days, 1)


def _skill_for_stage(stage: str) -> str:
    m = {
        "Machining": "CNC / Wood machining",
        "Carpentry": "Carpenter",
        "Metal": "Metal work",
        "Assembly": "Assembly",
        "Upholstery": "Upholstery",
        "Paint": "Painting / PU",
        "Final Assembly": "Assembly",
        "Packaging": "Packaging",
        "Dispatch": "Logistics",
    }
    return m.get(stage, "General")


def generate_sow(data: SQStructuredData) -> SOWOutput:
    """Generate SOW/lifecycle from SQ data. One sequence of stages per product."""
    product_sows: list[ProductSOW] = []
    for p in data.products:
        total_days = _estimate_days_for_product(p)
        per_stage = max(0.5, total_days / len(STAGE_ORDER))
        stages = []
        for i, stage in enumerate(STAGE_ORDER):
            prev = STAGE_ORDER[i - 1] if i > 0 else None
            dep = [prev] if prev else []
            stages.append(
                StageStep(
                    stage=stage,
                    duration_days=round(per_stage, 1),
                    dependencies=dep,
                    skill=_skill_for_stage(stage),
                    worker_count=1,
                )
            )
        product_sows.append(
            ProductSOW(sr_no=p.sr_no, name=p.name or f"Product {p.sr_no}", stages=stages, total_days=round(total_days, 1))
        )
    return SOWOutput(
        project_name=data.project.project_name or "",
        products=product_sows,
        stage_order=STAGE_ORDER,
    )
