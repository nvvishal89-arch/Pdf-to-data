"""
Client for GenCAD Docker service (Option A).
Calls POST /generate-drawings and GET /health.
When URL is built-in (same server), uses in-process call to avoid self-request deadlock.
"""
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_VIEW_LABELS = ["Front View", "Side View", "Top View", "Isometric"]


def _is_builtin_gencad_url(gencad_service_url: str | None) -> bool:
    """True if URL points to the built-in /gencad mount (same server)."""
    if not gencad_service_url or not gencad_service_url.strip():
        return False
    u = gencad_service_url.strip().rstrip("/").lower()
    return u.endswith("/gencad")


def get_gencad_service_status_builtin() -> dict:
    """Status when GenCAD is mounted in-process (no HTTP)."""
    return {"available": True, "error": None}


def get_gencad_service_status(gencad_service_url: str, timeout: int = 10) -> dict:
    """
    GET {url}/health. Returns {"available": bool, "error": str | None}.
    When URL is built-in (/gencad), returns available without HTTP to avoid deadlock.
    """
    if not gencad_service_url or not gencad_service_url.strip():
        return {"available": False, "error": "No GenCAD service URL"}
    if _is_builtin_gencad_url(gencad_service_url):
        return get_gencad_service_status_builtin()
    url = gencad_service_url.rstrip("/") + "/health"
    try:
        r = requests.get(url, timeout=timeout)
        if r.ok:
            return {"available": True, "error": None}
        return {"available": False, "error": f"HTTP {r.status_code}"}
    except requests.exceptions.RequestException as e:
        logger.debug("GenCAD health check failed: %s", e)
        return {"available": False, "error": str(e)}


def generate_drawings_via_gencad_builtin(
    image_b64: str,
    view_labels: Optional[list[str]] = None,
    dimensions: Optional[str] = None,
    product_name: Optional[str] = None,
) -> list[dict]:
    """
    Call GenCAD in-process (no HTTP). Use when URL is built-in to avoid self-request deadlock.
    Returns list of { "view_label", "dxf_base64", "svg_base64", "png_base64" }.
    """
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from gencad_service.main import generate_drawings_impl
    labels = view_labels or DEFAULT_VIEW_LABELS
    data = generate_drawings_impl(image_b64, labels, dimensions, product_name)
    views = data.get("views") or []
    return [
        {
            "view_label": v.get("view_label", ""),
            "dxf_base64": v.get("dxf_base64"),
            "svg_base64": v.get("svg_base64"),
            "png_base64": v.get("png_base64"),
        }
        for v in views
    ]


def generate_drawings_via_gencad(
    image_b64: str,
    view_labels: Optional[list[str]] = None,
    gencad_service_url: Optional[str] = None,
    dimensions: Optional[str] = None,
    product_name: Optional[str] = None,
    timeout: int = 120,
) -> list[dict]:
    """
    POST {url}/generate-drawings with image_base64, view_labels, and parsed data (dimensions, product_name).
    When URL is built-in (/gencad), calls GenCAD in-process to avoid self-request deadlock.
    Returns list of { "view_label", "dxf_base64", "svg_base64", "png_base64" }.
    Raises on network error or non-2xx response.
    """
    if not gencad_service_url or not gencad_service_url.strip():
        raise ValueError("GenCAD service URL required")
    if _is_builtin_gencad_url(gencad_service_url):
        return generate_drawings_via_gencad_builtin(
            image_b64, view_labels=view_labels, dimensions=dimensions, product_name=product_name
        )
    url = gencad_service_url.rstrip("/") + "/generate-drawings"
    labels = view_labels or DEFAULT_VIEW_LABELS
    payload = {"image_base64": image_b64, "view_labels": labels}
    if dimensions is not None:
        payload["dimensions"] = dimensions
    if product_name is not None:
        payload["product_name"] = product_name
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    views = data.get("views") or []
    return [
        {
            "view_label": v.get("view_label", ""),
            "dxf_base64": v.get("dxf_base64"),
            "svg_base64": v.get("svg_base64"),
            "png_base64": v.get("png_base64"),
        }
        for v in views
    ]
