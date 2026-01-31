"""
Phase 2: Image / Product classification (spec §7.3).
Product type (Wardrobe, TV Unit, Kitchen Cabinet, Bed, Sofa, Console) and view (Front, Side, Top, Isometric).
Rule-based from product name; vision API (OpenAI / Anthropic) when image_base64 provided and API key set.
"""
import os
import re
from typing import Optional

# Spec §7.3 Furniture-Specific Vision Models
PRODUCT_TYPES = [
    "Wardrobe",
    "TV Unit",
    "Kitchen Cabinet",
    "Bed",
    "Sofa",
    "Console",
    "Table",
    "Chair",
    "Storage",
    "Cabinet",
    "Desk",
    "Other",
]

VIEWS = ["Front View", "Side View", "Top View", "Isometric"]

# Keywords (lower) -> product type
TYPE_KEYWORDS = {
    "wardrobe": "Wardrobe",
    "tv unit": "TV Unit",
    "television": "TV Unit",
    "kitchen": "Kitchen Cabinet",
    "cabinet": "Cabinet",
    "bed": "Bed",
    "bedroom": "Bed",
    "sofa": "Sofa",
    "console": "Console",
    "table": "Table",
    "centre table": "Table",
    "center table": "Table",
    "coffee table": "Table",
    "side table": "Table",
    "chair": "Chair",
    "accent chair": "Chair",
    "study chair": "Chair",
    "bar chair": "Chair",
    "storage": "Storage",
    "desk": "Desk",
    "divider": "Other",
    "room divider": "Other",
}


def classify_product_type(name: str) -> str:
    """Classify product type from name (keyword-based). Returns one of PRODUCT_TYPES."""
    if not name:
        return "Other"
    lower = name.lower().strip()
    for kw, ptype in TYPE_KEYWORDS.items():
        if kw in lower:
            return ptype
    return "Other"


def classify_view_with_vision(image_base64: str) -> str:
    """
    Classify view (Front / Side / Top / Isometric) using vision API.
    Uses OPENAI_API_KEY (GPT-4o) or ANTHROPIC_API_KEY (Claude); no key -> returns "Front View".
    """
    view = _classify_view_openai(image_base64)
    if view is not None:
        return view
    view = _classify_view_anthropic(image_base64)
    if view is not None:
        return view
    return "Front View"


def _classify_view_openai(image_base64: str) -> Optional[str]:
    """Use OpenAI GPT-4o vision if OPENAI_API_KEY is set."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not image_base64:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        # Support data URL or raw base64
        b64 = image_base64.split(",")[-1] if "," in image_base64 else image_base64
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=64,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "This image shows a furniture or product. Reply with exactly one of: Front View, Side View, Top View, Isometric. No other text."
                        },
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ],
                }
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        for v in VIEWS:
            if v.lower() in text.lower():
                return v
        return "Front View"
    except Exception:
        return None


def _classify_view_anthropic(image_base64: str) -> Optional[str]:
    """Use Anthropic Claude vision if ANTHROPIC_API_KEY is set (and OpenAI not used)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not image_base64:
        return None
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        b64 = image_base64.split(",")[-1] if "," in image_base64 else image_base64
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=64,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": b64},
                        },
                        {
                            "type": "text",
                            "text": "This image shows a furniture or product. Reply with exactly one of: Front View, Side View, Top View, Isometric. No other text."
                        },
                    ],
                }
            ],
        )
        text = ""
        for b in response.content:
            if hasattr(b, "text"):
                text += getattr(b, "text", "") or ""
        text = text.strip()
        for v in VIEWS:
            if v.lower() in text.lower():
                return v
        return "Front View"
    except Exception:
        return None


def classify_view(name: str, image_base64: Optional[str] = None) -> str:
    """View detection. Uses vision API when image_base64 and API key present; else defaults to Front View."""
    if image_base64:
        return classify_view_with_vision(image_base64)
    return "Front View"


def classify_product(name: str, image_base64: Optional[str] = None) -> dict:
    """Return product_type and view for a product."""
    return {
        "product_type": classify_product_type(name),
        "view": classify_view(name, image_base64),
    }


def refine_dimensions_with_vision(image_base64: str, dimensions_str: str) -> str:
    """
    Optional (Track 2.3): Ask vision API to refine or confirm dimensions from image.
    Returns refined dimension string (e.g. "W x D x H in mm") or original if no API/key.
    """
    if not image_base64 or not dimensions_str.strip():
        return dimensions_str
    refined = _refine_dimensions_openai(image_base64, dimensions_str)
    if refined is not None:
        return refined
    refined = _refine_dimensions_anthropic(image_base64, dimensions_str)
    if refined is not None:
        return refined
    return dimensions_str


def _refine_dimensions_openai(image_base64: str, dimensions_str: str) -> Optional[str]:
    """Use OpenAI GPT-4o to refine dimensions from image."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        b64 = image_base64.split(",")[-1] if "," in image_base64 else image_base64
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=128,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Current dimensions from document: {dimensions_str}. Look at this furniture/product image and reply with refined dimensions in the same format (e.g. '1300 X 650 X 350' or 'W x D x H mm'). Reply with only the dimension string, no explanation."
                        },
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ],
                }
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        return text if text else None
    except Exception:
        return None


def _refine_dimensions_anthropic(image_base64: str, dimensions_str: str) -> Optional[str]:
    """Use Anthropic Claude to refine dimensions from image."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        b64 = image_base64.split(",")[-1] if "," in image_base64 else image_base64
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=128,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                        {"type": "text", "text": f"Current dimensions: {dimensions_str}. Look at this furniture image and reply with refined dimensions in the same format (e.g. '1300 X 650 X 350'). Reply with only the dimension string."},
                    ],
                }
            ],
        )
        text = "".join(getattr(b, "text", "") or "" for b in response.content)
        return text.strip() if text.strip() else None
    except Exception:
        return None
