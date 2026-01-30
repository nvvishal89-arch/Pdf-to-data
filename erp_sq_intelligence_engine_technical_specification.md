# ERP SQ Intelligence Engine – Technical Architecture & Product Specification (Excel + PDF Format Driven)

**Author:** Vishal Nagda  
**Purpose:** Developer-ready system design document for building an AI-powered web extension of ERP to convert SQ PDFs into structured data, images, drawings, PPT, and production lifecycle (SOW).

---

# 1. Vision & Product Objective

This system is **strictly driven by your actual SQ Excel structure**, and PDFs are guaranteed to follow the **same layout (±20% variation)**.  

**Primary Goal:**

> Convert your *standard SQ Excel / PDF format* into **100% structured ERP-ready data, drawings, images, PPT, and SOW lifecycle** with near‑zero manual effort.

This is NOT generic PDF parsing — it is a **template-trained extraction engine**.


Build a **next‑generation AI-powered SQ processing engine** that converts **standardized SQ PDFs** into:

- Structured data (CSV, JSON, Excel)
- Extracted & classified images
- AI-converted drawings (2D production-ready)
- Auto-generated PPT presentations
- Automatic SOW & lifecycle breakdown for ERP execution

This system should:
- Reduce manual SQ processing time by **90%**
- Enable **zero-data-loss extraction**
- Provide **production-ready intelligence**
- Seamlessly integrate into existing ERP

---

# 2. High-Level Functional Scope

## Core Functional Modules

1. SQ PDF → Structured Data Engine
2. SQ PDF → Image & Drawing Extractor
3. Image → Product Intelligence AI
4. Drawing Generator (2D CAD / Vector)
5. PPT Auto-Generator
6. SOW & Lifecycle Generator
7. ERP Sync Engine
8. UI / UX Layer

---

# 3. Input → Output Flow Architecture

```text
PDF (SQ)
   ↓
PDF Parser + OCR + Vision AI
   ↓
Unified AI Extraction Layer
   ↓
--------------------------------------------------
| Structured Data Engine | Image Engine | Drawing |
--------------------------------------------------
   ↓                 ↓                ↓
 CSV / JSON     Image Library     CAD / DXF / SVG
   ↓
ERP → SOW → Lifecycle → BOM → Gantt
   ↓
Auto PPT Generator
```

---

# 4. System Architecture (Microservices)

```text
Frontend (Web UI)
       ↓
API Gateway
       ↓
-------------------------------------------------
| PDF Engine | Vision AI | LLM AI | PPT Engine |
-------------------------------------------------
       ↓
Data Processing Layer
       ↓
PostgreSQL + Object Storage (S3)
       ↓
ERP Core Database
```

---

# 5. Core Technology Stack

## Frontend

- Next.js (React + SSR)
- Tailwind CSS + Shadcn UI
- Framer Motion (micro animations)
- Zustand (state)

UI Goal → **Apple-like minimal, frictionless, ultra-fast**

---

## Backend

- Node.js (Fastify) OR Python (FastAPI)
- Microservices Architecture
- Redis (Queue + cache)
- Kafka / RabbitMQ (Async pipelines)

---

## AI / ML Stack

- OpenAI GPT-4.1 / GPT-5 API (LLM reasoning)
- Claude 3.5 Sonnet (vision reasoning)
- Azure Document Intelligence / Google DocAI
- PaddleOCR + Tesseract
- OpenCV + YOLOv8
- Stable Diffusion XL (image cleanup)

---

## Drawing Generation

- OpenCV Vector Tracing
- SVG Path Generators
- DXF CAD Generator
- OpenCascade / FreeCAD Engine

---

## Storage

- PostgreSQL (Core structured data)
- S3 / Cloudflare R2 (Images + PDFs + drawings)
- Vector DB (Qdrant / Pinecone) for document memory

---

# 6. SQ Excel + PDF → Structured Data Pipeline (Template Driven)

This pipeline is **trained specifically on your SQ Excel layout**, so accuracy is extremely high.

---

## 6.1 SQ Template Structure (Derived from your Excel)

### Header Block

| Field | Source |
|--------|---------|
| Company Name | Fixed Cell |
| Project Name | Fixed Cell |
| Client Name | Fixed Cell |
| Quotation No | Fixed Cell |
| Date | Fixed Cell |
| Prepared By | Fixed Cell |

---

### Product Table Structure

| Column | Meaning |
|----------|---------|
| S.No | Serial Number |
| Product Description | Product Name + Details |
| Size / Dimensions | W × D × H |
| Area | SqFt / SqM |
| Material | Board + Veneer + Finish |
| Finish | PU / Laminate / Polish |
| Qty | Quantity |
| Rate | Unit Price |
| Amount | Total Price |
| Reference Image | Embedded / Linked |

---

## 6.2 Excel → Data Mapping Schema

```json
{
  "project": {
    "project_name": "",
    "client_name": "",
    "quotation_no": "",
    "date": "",
    "prepared_by": ""
  },
  "products": [
    {
      "sr_no": 1,
      "name": "",
      "description": "",
      "dimensions": "",
      "area": "",
      "material": "",
      "finish": "",
      "qty": 1,
      "unit_price": 0,
      "amount": 0,
      "images": []
    }
  ],
  "summary": {
    "subtotal": 0,
    "tax": 0,
    "grand_total": 0
  }
}
```

---

## 6.3 PDF Extraction Strategy (Near 100% Accuracy)

Since PDF layout ≈ Excel layout:

### Step 1 – Template Anchor Detection

- Detect fixed anchor labels:
  - "Sales Quotation"
  - "Project Name"
  - "S.No"

### Step 2 – Coordinate-based Column Detection

- Dynamic column region mapping
- Smart row segmentation

### Step 3 – Hybrid OCR + Table AI

- Azure Form Recognizer / Google DocAI
- GPT-5 table verification

### Step 4 – Auto Data Validation

- Total = Qty × Rate
- Dimension format validator
- Area logic checker

---


## Step 1: PDF Classification

- Detect format version
- Identify sections: header, product blocks, totals

## Step 2: OCR + Layout Parsing

- Hybrid OCR (vision + layout)
- Preserve tables

## Step 3: AI Schema Mapping

Output Schema:

```json
{
  "project": {},
  "client": {},
  "products": [
    {
      "name": "",
      "category": "",
      "dimensions": "",
      "area": "",
      "material": "",
      "finish": "",
      "price": 0,
      "qty": 0,
      "images": []
    }
  ],
  "totals": {}
}
```

## Step 4: Validation Layer

- Rule Engine
- AI verification
- Manual override UI

---

# 7. Image Extraction & Vision AI (Furniture & Interior Optimized)

Images are **critical production assets** in your workflow.

---

## 7.1 Image Sources in SQ PDF

1. Embedded product reference images
2. Screenshot drawings
3. Linked preview images

---

## 7.2 Image AI Pipeline

```text
Image → Cleaning → Perspective Correction → Edge Detection → View Classification
```

---

## 7.3 Furniture-Specific Vision Models

- Product Type Classification
  - Wardrobe
  - TV Unit
  - Kitchen Cabinet
  - Bed
  - Sofa
  - Console

- View Detection
  - Front View
  - Side View
  - Top View
  - Isometric

- Component Segmentation
  - Panels
  - Shutters
  - Drawers
  - Shelves

---


## Image Processing

- Extract embedded images
- Extract raster snapshots
- De-skew
- Noise removal
- Edge enhancement

## AI Understanding

- Object detection
- Furniture classification
- View detection (front, side, top, isometric)
- Part segmentation

---

# 8. Image → 2D Production Drawings (Manufacturing Grade)

This module generates **actual production drawings**, not presentation sketches.

---

## Drawing Output Standards

- DXF (for CNC)
- SVG (for web + preview)
- PNG (for ERP preview)

---

## Drawing Intelligence Flow

```text
Image → Object Segmentation → Panel Detection → Dimension AI → CAD Generator
```

---

## Auto Dimension Rules

- Use SQ dimension as master
- Vision AI refines proportions
- CNC tolerance added automatically

---


## Pipeline

```text
Image → Edge detection → Vectorization → CAD → Dimensioning → DXF/SVG
```

Outputs:
- DXF
- SVG
- PNG (preview)

---

# 9. Auto PPT Generator

## Slide Flow

1. Project Summary
2. Product Overview
3. Product Render Slides
4. Technical Drawings
5. Manufacturing Lifecycle
6. Delivery Timeline

## Tools

- python-pptx
- PPT Template Engine

---

# 10. SOW + Lifecycle Auto Generator (Your ERP Workflow Based)

This module is **directly aligned with your real factory workflow**.

---

## Auto Lifecycle Flow

Machining → Carpentry → Metal → Assembly → Upholstery → Paint → Final Assembly → Packaging → Dispatch

---

## AI SOW Generation Logic

Based on:
- Product category
- Dimensions
- Panel count
- Finish type

AI generates:

- Department time
- Worker count
- Skill mapping
- Material estimation

---


## AI Generated Stages

For each product:

Machining → Carpentry → Metal → Assembly → Upholstery → Paint → Final Assembly → Packaging → Dispatch

Auto generate:
- Duration
- Dependencies
- Skill mapping
- Worker allocation

---

# 11. ERP Integration Layer

## APIs

```text
POST /api/sq/upload
POST /api/sq/parse
GET  /api/sq/data
POST /api/sq/approve
POST /api/sow/create
POST /api/ppt/generate
```

---

# 12. UI / UX Principles

## Core Design Philosophy

- Zero clutter
- White-space heavy
- Minimal colors
- Glass-morphism
- Apple-level polish

## UX Flow

Upload → Review → Approve → Export → ERP Sync → PPT

---

# 13. Security Architecture

- JWT + OAuth
- Role-based permissions
- Audit logs
- Encryption at rest + transit

---

# 14. Scalability Design

- Horizontal scaling
- Async workers
- Queue based processing
- GPU acceleration

---

# 15. Development Roadmap

## Phase 1 – PDF → Structured Data
- OCR
- AI extraction
- CSV/JSON export

## Phase 2 – Image + Drawing AI
- Vision model
- CAD generation

## Phase 3 – PPT + Lifecycle AI
- Presentation
- SOW generation

## Phase 4 – ERP Deep Integration
- BOM
- Gantt
- Resource planning

---

# 16. Competitive Edge

This system becomes:

- **AI Manufacturing Brain**
- **Zero-touch SQ processing engine**
- **Production automation platform**

---

# 17. Future Expansion

- Cost prediction AI
- Profit optimization
- Material optimization
- CNC auto toolpath generation

---

# 18. Final Vision

This system will:

> Convert **static PDFs into living manufacturing intelligence**

---

# END OF DOCUMENT

