"""
Minimal API: POST /api/sq/parse (file upload) returning structured data + validation errors.
"""
import html
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.responses import JSONResponse, Response, HTMLResponse, FileResponse

from app.schema import ParseResult, SQStructuredData
from app.pdf_pipeline import parse_pdf_with_validation
from app.export import export_json, export_csv, export_excel
from app.template_extractor import extract_template_to_json
from app.ppt_generator import generate_ppt
from app.sow_generator import generate_sow, SOWOutput

app = FastAPI(
    title="SQ Intelligence Engine API",
    description="Phase 1–3: Parse SQ PDFs, PPT, SOW",
    version="0.2.0",
)


@app.get("/")
def root():
    return {"service": "SQ Intelligence Engine", "phases": [1, 2, 3]}


@app.get("/ui", response_class=HTMLResponse)
def ui():
    """Frontend: upload PDF, then View table, Download PPT, Generate SOW."""
    return FileResponse(Path(__file__).parent / "static" / "ui.html", media_type="text/html")


@app.post("/api/sq/parse", response_model=ParseResult)
async def parse_sq_pdf(file: UploadFile = File(...)):
    """
    Upload an SQ PDF; returns structured data and validation errors.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    contents = await file.read()
    tmp = Path(file.filename)
    tmp.write_bytes(contents)
    try:
        data, validation_errors = parse_pdf_with_validation(tmp)
        return ParseResult(data=data, validation_errors=validation_errors)
    finally:
        if tmp.exists():
            tmp.unlink()


@app.get("/api/sq/template")
def get_template_config():
    """
    Extract template config from Sample format SQ.xlsx (if present in cwd).
    Returns JSON config (anchors + column mapping).
    """
    sample = Path("Sample format SQ.xlsx")
    if not sample.exists():
        raise HTTPException(
            status_code=404,
            detail="Sample format SQ.xlsx not found in working directory",
        )
    try:
        json_str = extract_template_to_json(sample)
        return Response(content=json_str, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sq/export/json")
async def export_sq_json(file: UploadFile = File(...)):
    """Parse PDF and return JSON export only."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    contents = await file.read()
    tmp = Path(file.filename)
    tmp.write_bytes(contents)
    try:
        data, _ = parse_pdf_with_validation(tmp)
        return JSONResponse(content=data.model_dump(), media_type="application/json")
    finally:
        if tmp.exists():
            tmp.unlink()


@app.post("/api/sq/export/csv")
async def export_sq_csv(file: UploadFile = File(...)):
    """Parse PDF and return CSV export (products table)."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    contents = await file.read()
    tmp = Path(file.filename)
    tmp.write_bytes(contents)
    try:
        data, _ = parse_pdf_with_validation(tmp)
        csv_str = export_csv(data)
        return Response(content=csv_str, media_type="text/csv")
    finally:
        if tmp.exists():
            tmp.unlink()


def _table_row_html(product, index: int) -> str:
    """One table row with Reference Image cell showing image visually."""
    def esc(s: str) -> str:
        return html.escape(str(s)) if s else ""
    img_cell = ""
    if product.images:
        for b64 in product.images[:3]:  # up to 3 images per product
            img_cell += f'<img src="data:image/png;base64,{b64}" alt="Ref" style="max-width:120px;max-height:80px;object-fit:contain;display:block;margin:2px;" />'
    if not img_cell:
        img_cell = "<span>—</span>"
    desc = (product.description[:80] + "…") if len(product.description) > 80 else product.description
    return (
        f"<tr>"
        f"<td>{product.sr_no}</td>"
        f"<td>{esc(product.name)}</td>"
        f"<td>{esc(desc)}</td>"
        f"<td>{esc(product.dimensions)}</td>"
        f"<td>{esc(product.area)}</td>"
        f"<td>{esc(product.material)}</td>"
        f"<td>{esc(product.finish)}</td>"
        f"<td>{product.qty}</td>"
        f"<td>{product.unit_price}</td>"
        f"<td>{product.amount}</td>"
        f"<td>{img_cell}</td>"
        f"</tr>"
    )


@app.post("/api/sq/parse/html", response_class=HTMLResponse)
async def parse_sq_pdf_html(file: UploadFile = File(...)):
    """
    Upload an SQ PDF; returns an HTML page with a table showing product details
    and images in the Reference Image column (visual).
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    contents = await file.read()
    tmp = Path(file.filename)
    tmp.write_bytes(contents)
    try:
        data, _ = parse_pdf_with_validation(tmp)
        proj = data.project
        rows_html = "".join(_table_row_html(p, i) for i, p in enumerate(data.products))
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SQ Parse Result</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 1rem; background: #f5f5f5; }}
    h1 {{ font-size: 1.25rem; margin-bottom: 0.5rem; }}
    .meta {{ color: #666; margin-bottom: 1rem; }}
    table {{ border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.1); width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f0f0; font-weight: 600; }}
    td img {{ vertical-align: middle; }}
  </style>
</head>
<body>
  <h1>SQ Parse Result</h1>
  <div class="meta">Project: {html.escape(proj.project_name or '—')} | Client: {html.escape(proj.client_name or '—')} | Date: {html.escape(proj.date or '—')}</div>
  <table>
    <thead>
      <tr>
        <th>S.No</th>
        <th>Name</th>
        <th>Description</th>
        <th>Dimensions</th>
        <th>Area</th>
        <th>Material</th>
        <th>Finish</th>
        <th>Qty</th>
        <th>Rate</th>
        <th>Amount</th>
        <th>Reference Image</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</body>
</html>"""
        return HTMLResponse(content=html_content)
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------- Phase 3: PPT + SOW ----------

@app.post("/api/ppt/generate")
async def api_ppt_generate(data: SQStructuredData = Body(..., embed=False)):
    """
    Generate PowerPoint from parsed SQ data (Phase 3).
    Send JSON body: same shape as POST /api/sq/parse response .data
    """
    try:
        ppt_bytes = generate_ppt(data)
        return Response(
            content=ppt_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": "attachment; filename=sq_presentation.pptx"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sow/create")
async def api_sow_create(data: SQStructuredData = Body(..., embed=False)):
    """
    Generate SOW / lifecycle from parsed SQ data (Phase 3).
    Send JSON body: same shape as POST /api/sq/parse response .data
    """
    try:
        sow = generate_sow(data)
        return JSONResponse(content=sow.model_dump(), media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Phase 2: Classification (optional) ----------

@app.get("/api/classify/product")
def api_classify_product(name: str = ""):
    """Classify product type and view from name (Phase 2, rule-based)."""
    from app.image_ai import classify_product
    return classify_product(name or "")
