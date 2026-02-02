"""
Phase 2: Generate Front, Side, Top, Isometric view images per product.
Uses image-to-image (OpenAI Image Edit / GPT Image) when reference is available for better fidelity;
falls back to DALL·E 3 text-to-image with Vision-generated prompts.
"""
import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List

from app.schema import SQStructuredData
from app.image_ai import classify_product

logger = logging.getLogger(__name__)

# Image-to-image: short edit prompt per view (reference image is passed to API)
IMAGE_EDIT_PROMPTS = {
    "Front View": "Same product from the front. Keep every detail identical: colors, materials, shapes. Neutral background, studio lighting.",
    "Side View": "Same product from the side. Keep every detail identical: colors, materials, shapes. Neutral background, studio lighting.",
    "Top View": "Same product from above. Keep every detail identical: colors, materials, shapes. Neutral background, studio lighting.",
    "Isometric": "Same product in isometric 3D view. Keep every detail identical: colors, materials, shapes. Neutral background, studio lighting.",
}

VIEW_LABELS = ["Front View", "Side View", "Top View", "Isometric"]

# Vision sees reference image(s) and outputs the exact DALL·E prompt for that view (so "parsed images" inform generation).
VISION_DALLE_PROMPT_FROM_REF = """You are looking at reference image(s) of the same product (from a PDF). Your task is to write the EXACT prompt that will be sent to DALL·E 3 to generate this EXACT product from a different camera angle.

Target view to generate: {view_label}.

In your prompt you MUST:
- Describe every visible detail from the reference(s): exact upholstery color and material, cushion styles (which are tufted vs smooth/plain—be explicit), frame material and color (wood vs metal), arm and leg style, any distinctive details.
- Specify that the image should show this SAME product from the {view_label} angle only—no creative changes.
- Use a neutral background and studio lighting.

Output ONLY the image-generation prompt (one paragraph). No preamble, no "Prompt:", no quotes. The prompt will be sent directly to DALL·E."""

VISION_DESCRIBE_PROMPT = """Describe this furniture/product image so another AI can draw the EXACT SAME product from another angle. Answer each line precisely.

- Upholstery: exact color and material (e.g. dark green velvet, navy fabric). One clear phrase.
- Back cushions: write EXACTLY one of "square button-tufted" or "channel/ribbed tufting" or "smooth, no tufting". Then number of back cushions.
- Seat cushions: write EXACTLY one of "smooth, plain, no tufting" or "tufted" or "ribbed". Then number of seat cushions. IMPORTANT: If the seat has a flat smooth surface with NO dimples or buttons, you MUST write "smooth, plain, no tufting".
- Frame: write "all wood" or "metal" or "wood with metal legs". If wood: color (e.g. dark walnut, light oak). If metal: color.
- Arms: write "wide flat curved wooden armrests" if the arms are broad and table-like, OR "thin wooden trim" if narrow, OR "metal arms" or "no arms". Include shape (e.g. "curved", "sculpted loop under arm").
- Legs: e.g. "tapered wooden legs" or "metal legs" or "hidden".
- One distinctive detail that must not change: e.g. "sculpted wooden loop under arm", "wide armrest like a side table".

Use only the bullet lines above. No preamble. Be specific so the product can be replicated exactly."""

VISION_CRITICAL_TRAITS_PROMPT = """List exactly 6 short phrases that MUST appear in a drawing of this product. Include: (1) frame type and color, (2) "plain seat cushions" OR "tufted seat" depending on the image, (3) "square-tufted back" OR "smooth back" depending on the image, (4) arm style (e.g. "wide curved wooden armrests"), (5) one negative if critical (e.g. "no metal", "no tufting on seat"). One phrase per line. No other text."""


def _normalize_image_b64(img: str) -> str:
    """Return raw base64 string from data URL or raw b64."""
    s = (img or "").strip()
    if "," in s:
        return s.split(",")[-1].strip()
    return s


def _get_dalle_prompt_from_reference_images(
    ref_images_b64: List[str],
    view_label: str,
    product_name: str,
    api_key: str,
) -> Optional[str]:
    """
    Vision sees all parsed reference images and outputs the exact DALL·E prompt for this view.
    So the reference images directly inform what we send to DALL·E (which is text-only).
    """
    refs = [_normalize_image_b64(x) for x in ref_images_b64 if _normalize_image_b64(x)]
    if not refs or not api_key:
        return None
    # Limit to 4 images to avoid token limits
    refs = refs[:4]
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        content: list = [
            {"type": "text", "text": VISION_DALLE_PROMPT_FROM_REF.format(view_label=view_label)},
        ]
        for b64 in refs:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=600,
        )
        prompt = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        if not prompt:
            return None
        # Strip common wrappers
        for prefix in ("Prompt:", "prompt:", "The prompt:"):
            if prompt.lower().startswith(prefix):
                prompt = prompt[len(prefix):].strip()
        if prompt.startswith('"') and prompt.endswith('"'):
            prompt = prompt[1:-1]
        return prompt[:4000]
    except Exception as e:
        logger.debug("Vision DALL·E prompt from ref failed: %s", e)
        return None


def _describe_reference_image(ref_b64: str, api_key: str) -> Optional[str]:
    """Use GPT-4 Vision to describe the product for DALL·E. Returns None on failure."""
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
                        {"type": "text", "text": VISION_DESCRIBE_PROMPT},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ],
            max_tokens=500,
        )
        desc = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        if not desc:
            return None
        resp2 = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_CRITICAL_TRAITS_PROMPT},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }
            ],
            max_tokens=200,
        )
        traits = (resp2.choices[0].message.content or "").strip() if resp2 and resp2.choices else ""
        if traits:
            desc = f"{desc}\nCritical traits (must match): {traits}"
        return desc
    except Exception as e:
        logger.debug("Vision describe failed: %s", e)
        return None


def _build_prompt(
    product_name: str,
    product_type: str,
    view_label: str,
    reference_description: Optional[str] = None,
) -> str:
    """Product photography prompt. With reference_description, DALL·E is constrained to the same product."""
    ptype = product_type or "furniture"
    name = product_name or "product"
    if reference_description:
        view_instruction = (
            "Show the same product from the side." if "Side" in view_label else
            "Show the same product from above." if "Top" in view_label else
            "Show the same product in isometric 3D view." if "Isometric" in view_label else
            "Show the same product from the front."
        )
        ref_lower = reference_description.lower()
        negatives = []
        if any(x in ref_lower for x in ("all wood", "wood frame", "wooden frame")) and "metal" not in ref_lower:
            negatives.append("Do not show metal frame or metal legs.")
        if "smooth" in ref_lower and "seat" in ref_lower:
            negatives.append("Seat cushions are SMOOTH and PLAIN with NO tufting, NO dimples, NO buttons—do not add any tufting to the seat.")
        if "plain seat" in ref_lower or ("plain" in ref_lower and "seat" in ref_lower):
            negatives.append("Seat cushions must be flat and untufted.")
        if "square" in ref_lower and "tuft" in ref_lower:
            negatives.append("Back cushions only: square button-tufting.")
        if "wide" in ref_lower and ("arm" in ref_lower or "armrest" in ref_lower):
            negatives.append("Armrests are wide, flat, curved wooden surfaces—not thin or minimal.")
        negative_block = " ".join(negatives) if negatives else ""
        smooth_seat = "smooth" in ref_lower and "seat" in ref_lower
        lead = (
            f"Product with SMOOTH UNTUFTED seat cushions (no dimples on seat) and tufted back only. Same product, {view_instruction}. "
            if smooth_seat
            else f"Same exact product, only camera angle changes. {view_instruction}. "
        )
        return (
            f"{lead}"
            f"Match every detail below; do not substitute materials or styles. "
            f"{negative_block} "
            f"Product specification: {reference_description}. "
            f"Neutral background, studio lighting. No creative changes."
            f"{' Repeat: seat cushions are smooth and plain, no tufting or dimples.' if smooth_seat else ''}"
        )
    return (
        f"A high-quality detailed photograph of a {ptype} piece: {name}. "
        f"View: {view_label}. Professional product photography, neutral background, studio lighting."
    )


def _generate_image_openai_edit(
    ref_image_b64: str,
    view_label: str,
    api_key: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Image-to-image: pass reference image to OpenAI Image Edit (GPT Image).
    Returns (base64 PNG or None, error_code or None).
    """
    key = (api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or not ref_image_b64:
        return None, None
    prompt = IMAGE_EDIT_PROMPTS.get(view_label) or f"Same product from {view_label}. Keep every detail identical. Neutral background, studio lighting."
    try:
        img_bytes = base64.b64decode(ref_image_b64)
    except Exception:
        return None, None
    tmp_path = None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(img_bytes)
            tmp_path = f.name
        for model in ("gpt-image-1.5", "gpt-image-1-mini"):
            try:
                with open(tmp_path, "rb") as f:
                    resp = client.images.edit(
                        model=model,
                        image=f,
                        prompt=prompt[:1000],
                        quality="high",
                        size="1024x1024",
                    )
                if resp.data and len(resp.data) > 0:
                    b64 = getattr(resp.data[0], "b64_json", None)
                    return (b64, None) if b64 else (None, None)
            except Exception as e2:
                logger.debug("OpenAI image edit %s failed: %s", model, e2)
                continue
        return None, None
    except Exception as e:
        logger.debug("OpenAI image edit failed: %s", e)
        err_str = str(e).lower()
        if "billing_hard_limit_reached" in err_str or "billing hard limit" in err_str:
            return None, "billing_hard_limit_reached"
        if "model" in err_str and ("not found" in err_str or "invalid" in err_str):
            return None, "model_unavailable"
        return None, None
    finally:
        if tmp_path and Path(tmp_path).exists():
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass


def _generate_image_replicate_img2img(
    ref_image_b64: str,
    view_label: str,
    api_token: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Image-to-image via Replicate (Stable Diffusion img2img).
    Set REPLICATE_API_TOKEN to use. Returns (base64 PNG or None, error_code or None).
    """
    token = (api_token or "").strip() or os.environ.get("REPLICATE_API_TOKEN", "").strip()
    if not token or not ref_image_b64:
        return None, None
    prompt = IMAGE_EDIT_PROMPTS.get(view_label) or f"Same product from {view_label}. Keep every detail identical. Neutral background, studio lighting."
    try:
        import replicate
    except ImportError:
        return None, None
    try:
        data_uri = f"data:image/png;base64,{ref_image_b64}"
        out = replicate.run(
            "stability-ai/stable-diffusion-img2img",
            input={
                "image": data_uri,
                "prompt": prompt[:500],
                "prompt_strength": 0.65,
                "num_outputs": 1,
            },
        )
        if not out:
            return None, None
        url = out[0] if isinstance(out, list) else getattr(out, "url", str(out))
        if not url:
            return None, None
        import urllib.request
        with urllib.request.urlopen(url, timeout=60) as r:
            img_bytes = r.read()
        return base64.b64encode(img_bytes).decode("ascii"), None
    except Exception as e:
        logger.debug("Replicate img2img failed: %s", e)
        return None, None


def _generate_image_openai(prompt: str, api_key: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Generate one image with OpenAI DALL·E 3 (text-only). Returns (base64 PNG or None, error_code or None e.g. 'billing_hard_limit_reached')."""
    key = (api_key or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
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
            return b64, None
        return None, None
    except Exception as e:
        logger.debug("OpenAI image gen failed: %s", e)
        err_str = str(e).lower()
        if "billing_hard_limit_reached" in err_str or "billing hard limit" in err_str:
            return None, "billing_hard_limit_reached"
        return None, None


def generate_views_for_product(
    product_name: str,
    product_type: str,
    reference_image_b64: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
    openai_api_key: Optional[str] = None,
) -> dict[str, str]:
    """
    Generate 4 view images (Front, Side, Top, Isometric) for one product.
    When reference_image_b64 or reference_images are provided, Vision sees them and writes the exact DALL·E prompt per view.
    """
    out: dict[str, str] = {}
    ref_list = list(reference_images) if reference_images else []
    if reference_image_b64 and not ref_list:
        ref_list = [reference_image_b64]
    ref_list = [_normalize_image_b64(r) for r in ref_list if _normalize_image_b64(r)]
    ref = ref_list[0] if ref_list else None
    ref_description: Optional[str] = None
    if ref and openai_api_key:
        ref_description = _describe_reference_image(ref, (openai_api_key or "").strip())
    for view_label in VIEW_LABELS:
        b64: Optional[str] = None
        if ref and openai_api_key:
            b64, _ = _generate_image_openai_edit(ref, view_label, openai_api_key)
        if b64 is None and ref and os.environ.get("REPLICATE_API_TOKEN", "").strip():
            b64, _ = _generate_image_replicate_img2img(ref, view_label, os.environ.get("REPLICATE_API_TOKEN"))
        if b64 is None and openai_api_key:
            prompt = None
            if ref_list and openai_api_key:
                prompt = _get_dalle_prompt_from_reference_images(ref_list, view_label, product_name, (openai_api_key or "").strip())
            if not prompt and ref_description:
                prompt = _build_prompt(product_name, product_type, view_label, reference_description=ref_description)
            if not prompt:
                prompt = _build_prompt(product_name, product_type, view_label, reference_description=None)
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
    products_out = []
    any_ai = False
    billing_error_seen = False
    for i, product in enumerate(data.products):
        name = getattr(product, "name", None) or ""
        info = classify_product(name, None)
        ptype = info.get("product_type") or "Other"
        images = getattr(product, "images", None) or []
        ref_images = [img for img in images if _normalize_image_b64(img)]
        ref_b64 = _normalize_image_b64(ref_images[0]) if ref_images else None
        ref_description: Optional[str] = None
        if ref_b64 and key:
            ref_description = _describe_reference_image(ref_b64, key)
        views_list = []
        replicate_token = os.environ.get("REPLICATE_API_TOKEN", "").strip()
        for view_label in VIEW_LABELS:
            b64: Optional[str] = None
            error_code: Optional[str] = None
            source = "reference"
            # 1. Prefer image-to-image: OpenAI Image Edit (GPT Image) sees reference image
            if ref_b64 and key:
                b64, error_code = _generate_image_openai_edit(ref_b64, view_label, key)
                if b64:
                    source = "openai_edit"
            # 2. Fallback: Replicate img2img if token set
            if b64 is None and ref_b64 and replicate_token:
                b64, _ = _generate_image_replicate_img2img(ref_b64, view_label, replicate_token)
                if b64:
                    source = "replicate"
            # 3. Fallback: Vision + DALL·E 3 (text prompt from reference)
            if b64 is None and key:
                prompt = None
                if ref_images and key:
                    prompt = _get_dalle_prompt_from_reference_images(ref_images, view_label, name, key)
                if not prompt and ref_description:
                    prompt = _build_prompt(name, ptype, view_label, reference_description=ref_description)
                if not prompt:
                    prompt = _build_prompt(name, ptype, view_label, reference_description=None)
                b64, error_code = _generate_image_openai(prompt, key)
                if b64:
                    source = "openai"
            if error_code == "billing_hard_limit_reached":
                billing_error_seen = True
            if b64 is None and ref_b64:
                b64 = ref_b64
            if b64 and source != "reference":
                any_ai = True
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
