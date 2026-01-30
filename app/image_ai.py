"""
Phase 2: Image / Product classification (spec §7.3).
Product type (Wardrobe, TV Unit, Kitchen Cabinet, Bed, Sofa, Console) and view (Front, Side, Top, Isometric).
Rule-based from product name; can be replaced by vision API later.
"""
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


def classify_view(name: str, image_base64: Optional[str] = None) -> str:
    """View detection. From name only we default to Front; image_base64 can feed vision API later."""
    if image_base64:
        # TODO: call vision API (Claude/GPT-4V) for view classification
        pass
    return "Front View"


def classify_product(name: str, image_base64: Optional[str] = None) -> dict:
    """Return product_type and view for a product."""
    return {
        "product_type": classify_product_type(name),
        "view": classify_view(name, image_base64),
    }
