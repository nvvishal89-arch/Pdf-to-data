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
from app.drawing_engine import generate_drawings_for_data, generate_drawings_from_product_views
from app.gencad_client import generate_drawings_via_gencad, get_gencad_service_status

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

# Mount GenCAD service at /gencad so one server serves both (no separate port needed)
try:
    import sys
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from gencad_service.main import app as gencad_app
    app.mount("/gencad", gencad_app)
except Exception:
    gencad_app = None  # gencad_service not available

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


@app.get("/api/gencad/status")
async def api_gencad_status(url: str | None = None):
    """Return GenCAD service status for given URL (or GENCAD_SERVICE_URL env). Query: ?url=http://localhost:8001"""
    gencad_url = (url or "").strip() or _resolve_gencad_url(None, use_gencad=False)
    if not gencad_url:
        return {"available": False, "error": "No GenCAD URL (set query param or GENCAD_SERVICE_URL)"}
    return get_gencad_service_status(gencad_url)


def _resolve_gencad_url(gencad_service_url: str | None, use_gencad: bool = False) -> str | None:
    import os
    url = (gencad_service_url or "").strip() or os.environ.get("GENCAD_SERVICE_URL", "").strip()
    if url:
        return url
    # When URL is empty, do not default to a separate port. The UI must send the built-in
    # URL (e.g. http://127.0.0.1:8000/gencad) when "Use GenCAD" is checked and field is empty.
    return None


# #region agent log
def _debug_log(location: str, message: str, data: dict, hypothesis_id: str = ""):
    try:
        import json, os, time
        log_path = Path(__file__).resolve().parent.parent / ".cursor" / "debug.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"location": location, "message": message, "data": data, "timestamp": int(time.time() * 1000), "sessionId": "debug-session", "hypothesisId": hypothesis_id}) + "\n")
    except Exception:
        pass
# #endregion


@app.post("/api/drawings/generate")
async def api_drawings_generate(
    data: SQStructuredData = Body(..., embed=False),
    use_vision_dimensions: bool = Body(False, embed=False),
    product_views: list[dict] | None = Body(None, embed=False),
    use_gencad: bool = Body(False, embed=False),
    gencad_service_url: str | None = Body(None, embed=False),
):
    """Generate 2D drawings (PNG, DXF, SVG) via GenCAD when use_gencad=True (uses parsed dimensions); else image vectorization. product_views: optional AI-generated view images."""
    gencad_url = _resolve_gencad_url(gencad_service_url, use_gencad=use_gencad)
    _debug_log("main.py:drawings", "gencad URL resolution", {"use_gencad": use_gencad, "gencad_service_url_in": gencad_service_url, "gencad_url_resolved": gencad_url}, "H3a")
    gencad_status = get_gencad_service_status(gencad_url) if gencad_url else {"available": False, "error": "No GenCAD URL"}
    results = None
    gencad_used = False

    if use_gencad and gencad_url:
        primary_b64 = None
        product_name = (data.products[0].name if data.products else "") or "Product 1"
        dimensions_str = getattr(data.products[0], "dimensions", "") if data.products else ""
        if product_views and product_views[0].get("views"):
            primary_b64 = product_views[0]["views"][0].get("image_base64")
            product_name = (product_views[0].get("product_name") or "").strip() or product_name
        elif data.products and getattr(data.products[0], "images", None) and data.products[0].images:
            primary_b64 = data.products[0].images[0]
            product_name = getattr(data.products[0], "name", None) or product_name
        if primary_b64:
            try:
                gencad_views = generate_drawings_via_gencad(
                    primary_b64,
                    view_labels=["Front View", "Side View", "Top View", "Isometric"],
                    gencad_service_url=gencad_url,
                    dimensions=dimensions_str,
                    product_name=product_name,
                )
                if gencad_views and any(v.get("dxf_base64") or v.get("svg_base64") or v.get("png_base64") for v in gencad_views):
                    gencad_used = True
                    results = [
                        {
                            "product_index": 0,
                            "product_name": product_name,
                            "name": product_name or v.get("view_label", ""),
                            "image_index": -1,
                            "view_label": v.get("view_label", ""),
                            "dimensions": dimensions_str,
                            "svg_base64": v.get("svg_base64"),
                            "dxf_base64": v.get("dxf_base64"),
                            "png_base64": v.get("png_base64"),
                        }
                        for v in gencad_views
                    ]
            except Exception as e:
                _agent_log("main.py:gencad", "GenCAD fallback", {"error": str(e)})

    if results is None:
        if product_views:
            results = generate_drawings_from_product_views(
                product_views, data=data, use_vision_dimensions=use_vision_dimensions
            )
        else:
            results = generate_drawings_for_data(data, use_vision_dimensions=use_vision_dimensions)

    return {
        "drawings": results,
        "gencad_used": gencad_used,
        "gencad_status": gencad_status,
    }


@app.post("/api/bom/generate")
async def api_bom_generate(
    data: SQStructuredData = Body(..., embed=False),
    line_overrides: list[dict] | None = Body(None, embed=False),
):
    """Generate BOM from SQ data, match to inventory API. Optional line_overrides: [{line_index, inventory_item_id, inventory_code}]."""
    try:
        from app.bom import generate_bom
        return generate_bom(data, line_overrides=line_overrides)
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
