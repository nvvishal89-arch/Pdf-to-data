# SQ Intelligence Engine – Phases 2–4 Roadmap

Phase 1 (PDF → Structured Data) is done. This document outlines the next phases from the [technical spec](erp_sq_intelligence_engine_technical_specification.md).

---

## Phase 2 – Image + Drawing AI

**Goal:** Turn extracted images into production-ready intelligence and optional 2D drawings.

| Deliverable | Spec reference | Status / approach |
|-------------|----------------|--------------------|
| **Image classification** | §7.3 Furniture-Specific Vision Models | Product type (Wardrobe, TV Unit, Kitchen Cabinet, Bed, Sofa, Console) and view (Front, Side, Top, Isometric) from product name/keywords or future vision API. |
| **Image pipeline** | §7.2 | Cleaning, de-skew, edge detection – optional (OpenCV) after classification. |
| **2D drawings** | §8 | Outputs: DXF (CNC), SVG (web), PNG (preview). Pipeline: Image → Edge detection → Vectorization → Dimensioning. Use SQ dimensions as master; optional OpenCV/vector libs. |

**Tech (from spec):** OpenCV, YOLOv8 (optional), SVG/DXF generators, python-pptx for previews.

---

## Phase 3 – PPT + Lifecycle AI

**Goal:** Auto-generate presentations and SOW/lifecycle from parsed SQ data.

| Deliverable | Spec reference | Status / approach |
|-------------|----------------|--------------------|
| **Auto PPT** | §9 | Slides: Project Summary → Product Overview → Product Renders → Technical Drawings → Manufacturing Lifecycle → Delivery Timeline. Tool: python-pptx. |
| **SOW + Lifecycle** | §10 | Stages: Machining → Carpentry → Metal → Assembly → Upholstery → Paint → Final Assembly → Packaging → Dispatch. Per product: duration, dependencies, skill mapping, worker allocation. Rule-based from product category, dimensions, finish; optional LLM. |

**APIs (spec §11):** `POST /api/ppt/generate`, `POST /api/sow/create`.

---

## Phase 4 – ERP Deep Integration

**Goal:** Connect to ERP workflows (BOM, Gantt, resource planning).

| Deliverable | Spec reference | Status / approach |
|-------------|----------------|--------------------|
| **API layer** | §11 | `POST /api/sq/upload`, `GET /api/sq/data`, `POST /api/sq/approve`, `POST /api/sow/create`, `POST /api/ppt/generate` – implement or stub for your ERP. |
| **BOM** | §15 | Bill of materials from products + materials. |
| **Gantt** | §15 | Timeline from SOW stages and dependencies. |
| **Resource planning** | §15 | Worker/skill allocation from SOW. |

**Tech:** PostgreSQL for core data, optional Redis/Kafka for async; integrate with existing ERP APIs.

---

## Implementation order (current codebase)

1. **Phase 3 (PPT + SOW)** – Uses existing `SQStructuredData`; no new infra. Adds `app/ppt_generator.py`, `app/sow_generator.py`, and endpoints.
2. **Phase 2 (Image AI)** – Add `app/image_ai.py` (classification from product name; optional vision API later). Drawing (SVG/DXF) can follow.
3. **Phase 4** – Add API stubs and persistence (e.g. save parse result, approve flow) then BOM/Gantt when ERP schema is fixed.

See `app/` for Phase 2/3 modules and `app/main.py` for new routes.
