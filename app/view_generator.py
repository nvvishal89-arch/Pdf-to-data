"""
Phase 2: Generate Front, Side, Top, Isometric view images per product.
Uses OpenAI DALL·E 3 only. API key from request body or OPENAI_API_KEY env.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

from app.schema import SQStructuredData
from app.image_ai import classify_product

logger = logging.getLogger(__name__)

# #region agent log
DEBUG_LOG = Path(__file__).resolve().parent.parent / ".cursor" / "debug.log"
def _log(loc: str, msg: str, data: dict, hypothesis_id: str = ""):
    try:
        payload = {"location": loc, "message": msg, "data": data, "sessionId": "debug-session", "timestamp": __import__("time").time() * 1000}
        if hypothesis_id:
            payload["hypothesisId"] = hypothesis_id
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass
# #endregion

VIEW_LABELS = ["Front View", "Side View", "Top View", "Isometric"]


def _describe_reference_image(ref_b64: str, api_key: str) -> Optional[str]:
    """Use GPT-4 Vision to describe the product in the reference image for use in DALL·E prompts. Returns None on failure."""
    if not ref_b64 or not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        url = f"data:image/png;base64,{ref_b64}"
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Describe this product for an image generation prompt. Be very specific: (1) exact upholstery color and material (e.g. dark green velvet, teal fabric), (2) cushion style (tufted, smooth, ribbed), (3) frame material and color (e.g. dark brown walnut wood, metal), (4) armrest and leg design (e.g. wooden arms with tray, tapered legs). One paragraph, no preamble. The goal is to recreate this exact product in another view.",
                        },
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ],
            max_tokens=250,
        )
        if resp.choices and resp.choices[0].message.content:
            return resp.choices[0].message.content.strip() or None
        return None
    except Exception as e:
        logger.debug("Vision describe failed: %s", e)
        return None


def _build_prompt(
    product_name: str,
    product_type: str,
    view_label: str,
    reference_description: Optional[str] = None,
) -> str:
    """High-quality product photography prompt. If reference_description is set, DALL·E is guided to match that product."""
    ptype = product_type or "furniture"
    name = product_name or "product"
    if reference_description:
        return (
            f"Product photograph, {view_label} only. This exact product: {reference_description}. "
            f"Recreate the same product from this new angle—identical colors, materials, frame, and design. No creative changes. Neutral background, studio lighting."
        )
    return (
        f"A high-quality detailed photograph of a {ptype} piece: {name}. "
        f"View: {view_label}. Professional product photography, neutral background, studio lighting."
    )


def _generate_image_openai(prompt: str, api_key: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Generate one image with OpenAI DALL·E 3. Returns (base64 PNG or None, error_code or None e.g. 'billing_hard_limit_reached')."""
    key = (api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    # #region agent log
    _log("view_generator:_generate_image_openai", "entry", {"has_key": bool(key), "key_len": len(key) if key else 0}, "H2")
    # #endregion
    if not key:
        return None, None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt[:4000],
            size="1024x1024",
            quality="standard",
            n=1,
            response_format="b64_json",
        )
        if resp.data and len(resp.data) > 0:
            b64 = getattr(resp.data[0], "b64_json", None)
            # #region agent log
            _log("view_generator:_generate_image_openai", "after call", {"got_data": True, "b64_len": len(b64) if b64 else 0}, "H4")
            # #endregion
            return b64, None
        # #region agent log
        _log("view_generator:_generate_image_openai", "after call", {"got_data": False, "resp_data_len": len(resp.data) if resp.data else 0}, "H4")
        # #endregion
        return None, None
    except Exception as e:
        # #region agent log
        _log("view_generator:_generate_image_openai", "exception", {"err_type": type(e).__name__, "err_msg": str(e)[:200]}, "H3")
        # #endregion
        logger.debug("OpenAI image gen failed: %s", e)
        err_str = str(e).lower()
        if "billing_hard_limit_reached" in err_str or "billing hard limit" in err_str:
            return None, "billing_hard_limit_reached"
        return None, None


def generate_views_for_product(
    product_name: str,
    product_type: str,
    reference_image_b64: Optional[str] = None,
    openai_api_key: Optional[str] = None,
) -> dict[str, str]:
    """
    Generate 4 view images (Front, Side, Top, Isometric) for one product.
    Returns dict view_label -> base64 PNG. Uses reference_image_b64 as fallback when AI fails.
    """
    out: dict[str, str] = {}
    ref = (reference_image_b64 or "").strip()
    if ref and "," in ref:
        ref = ref.split(",")[-1].strip()
    ref_description: Optional[str] = None
    if ref and openai_api_key:
        ref_description = _describe_reference_image(ref, (openai_api_key or "").strip())
    for view_label in VIEW_LABELS:
        prompt = _build_prompt(product_name, product_type, view_label, reference_description=ref_description)
        b64, _ = _generate_image_openai(prompt, openai_api_key)
        if b64 is None and ref:
            b64 = ref
        out[view_label] = b64 or ""
    return out


def generate_all_views_for_data(
    data: SQStructuredData,
    openai_api_key: Optional[str] = None,
) -> dict:
    """
    Generate Front, Side, Top, Isometric for each product using OpenAI DALL·E 3.
    openai_api_key: optional key from UI; else uses OPENAI_API_KEY env.
    Returns dict: products (list of {product_index, product_name, views: [{view_label, image_base64, source}]}),
    ai_views_generated (bool), hint (str).
    """
    key = (openai_api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    # #region agent log
    _log("view_generator:generate_all_views_for_data", "entry", {"has_key_from_arg": bool((openai_api_key or "").strip()), "key_len": len(key) if key else 0, "num_products": len(data.products)}, "H1")
    # #endregion
    products_out = []
    any_ai = False
    billing_error_seen = False
    for i, product in enumerate(data.products):
        name = getattr(product, "name", None) or ""
        info = classify_product(name, None)
        ptype = info.get("product_type") or "Other"
        images = getattr(product, "images", None) or []
        ref_b64 = images[0] if images else None
        if ref_b64 and "," in ref_b64:
            ref_b64 = ref_b64.split(",")[-1].strip()
        ref_description: Optional[str] = None
        if ref_b64 and key:
            ref_description = _describe_reference_image(ref_b64, key)
        views_list = []
        for view_label in VIEW_LABELS:
            prompt = _build_prompt(name, ptype, view_label, reference_description=ref_description)
            b64, error_code = _generate_image_openai(prompt, key)
            if error_code == "billing_hard_limit_reached":
                billing_error_seen = True
            source = "openai" if b64 else "reference"
            if b64 is None and ref_b64:
                b64 = ref_b64
            if b64 and source == "openai":
                any_ai = True
            # #region agent log
            _log("view_generator:generate_all_views_for_data", "view result", {"product_index": i, "view_label": view_label, "source": source}, "H5")
            # #endregion
            views_list.append({
                "view_label": view_label,
                "image_base64": b64 or "",
                "source": source,
            })
        products_out.append({
            "product_index": i,
            "product_name": name,
            "views": views_list,
        })
    hint = ""
    if not any_ai:
        if not key:
            hint = "Enter your OpenAI API key above to generate view images with DALL·E 3."
        elif billing_error_seen:
            hint = "OpenAI billing limit reached. Add a payment method or increase your usage limit at platform.openai.com."
        else:
            hint = "DALL·E did not return images. Check your API key and billing, and ensure products have reference images."
    return {
        "products": products_out,
        "ai_views_generated": any_ai,
        "hint": hint,
    }
