"""
FastAPI ASGI app for ERP SQ Intelligence Engine.
Endpoints: parse PDF, PPT, SOW, views/generate-all, drawings/generate, static UI.
"""
import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, Body
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.schema import SQStructuredData, ParseResult
from app.pdf_pipeline import parse_pdf_with_validation
from app.export import export_json
from app.ppt_generator import generate_ppt
from app.sow_generator import generate_sow
from app.drawing_engine import generate_drawings_for_data

# #region agent log
DEBUG_LOG = Path(__file__).resolve().parent.parent / ".cursor" / "debug.log"
def _agent_log(location: str, message: str, data: dict):
    try:
        payload = {"location": location, "message": message, "data": data, "sessionId": "debug-session", "timestamp": __import__("time").time() * 1000}
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass
# #endregion

app = FastAPI(title="ERP SQ Intelligence Engine")

# Mount static files (must be after routes that shadow paths)
STATIC_DIR = Path(__file__).resolve().parent / "static"
static_mounted = STATIC_DIR.exists()
if static_mounted:
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# #region agent log
_agent_log("main.py:startup", "Static mount", {"static_dir": str(STATIC_DIR), "static_dir_exists": STATIC_DIR.exists(), "static_mounted": static_mounted})
# #endregion


@app.get("/")
async def root():
    """Redirect to UI."""
    return RedirectResponse(url="/static/ui.html", status_code=302)


@app.get("/ui")
async def ui_redirect():
    """Redirect /ui to the static UI (common bookmark/link)."""
    return RedirectResponse(url="/static/ui.html", status_code=302)


@app.post("/api/parse")
async def api_parse(file: UploadFile = File(...)):
    """Upload PDF, return structured data and validation errors."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        try:
            data, errors = parse_pdf_with_validation(tmp_path)
            return ParseResult(data=data, validation_errors=errors)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ppt/generate")
async def api_ppt_generate(
    data: SQStructuredData = Body(..., embed=False),
    product_drawings: list[dict] | None = Body(None, embed=False),
):
    """Generate PowerPoint from SQ data. Optional product_drawings: list of {product_index, name, png_base64}."""
    try:
        ppt_bytes = generate_ppt(data, product_drawings=product_drawings)
        return Response(
            content=ppt_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": "attachment; filename=sq_presentation.pptx"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sow/create")
async def api_sow_create(data: SQStructuredData = Body(..., embed=False)):
    """Generate SOW/lifecycle from SQ data."""
    try:
        return generate_sow(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/views/generate-all")
async def api_views_generate_all(
    data: SQStructuredData = Body(..., embed=False),
    openai_api_key: str | None = Body(None, embed=False),
):
    """Generate Front, Side, Top, Isometric view images for each product using OpenAI DALL·E 3."""
    try:
        from app.view_generator import generate_all_views_for_data
        return generate_all_views_for_data(data, openai_api_key=openai_api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/drawings/generate")
async def api_drawings_generate(
    data: SQStructuredData = Body(..., embed=False),
    use_vision_dimensions: bool = Body(False, embed=False),
):
    """Generate 2D drawings (SVG, DXF, PNG) for each product image."""
    try:
        results = generate_drawings_for_data(data, use_vision_dimensions=use_vision_dimensions)
        return {"drawings": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}


# #region agent log
def _route_paths():
    paths = []
    for r in getattr(app, "routes", []):
        path = getattr(r, "path", None)
        if path is None:
            continue
        methods = getattr(r, "methods", None)
        paths.append({"path": path, "methods": list(methods) if methods else "mount"})
    return paths
_agent_log("main.py:startup", "Routes", {"routes": _route_paths()})


class Log404Middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if response.status_code == 404:
            _agent_log("main.py:404", "Not Found", {"method": request.method, "path": request.url.path, "query": str(request.query_params)})
        return response
app.add_middleware(Log404Middleware)
# #endregion
