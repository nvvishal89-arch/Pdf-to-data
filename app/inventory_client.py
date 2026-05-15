"""
Inventory / ERP API client for BOM matching.
Configurable via INVENTORY_API_URL and optional INVENTORY_API_KEY.
Placeholder when no URL (returns empty list).
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class InventoryItem:
    """Single inventory item from ERP."""
    def __init__(
        self,
        id: str,
        code: str,
        name: str,
        unit: str = "",
        category: str = "",
        raw: Optional[dict] = None,
    ):
        self.id = id
        self.code = (code or "").strip()
        self.name = (name or "").strip()
        self.unit = (unit or "").strip()
        self.category = (category or "").strip()
        self.raw = raw or {}

    def to_dict(self) -> dict:
        return {"id": self.id, "code": self.code, "name": self.name, "unit": self.unit, "category": self.category}


def get_inventory_items() -> list[InventoryItem]:
    """
    Fetch inventory items from ERP API.
    Expects JSON array of objects with id, code, name, unit, category (or equivalent).
    Returns empty list when URL not set or request fails.
    """
    url = (os.environ.get("INVENTORY_API_URL") or "").strip()
    if not url:
        logger.debug("INVENTORY_API_URL not set; skipping inventory fetch")
        return []
    try:
        import urllib.request
        req = urllib.request.Request(url)
        key = (os.environ.get("INVENTORY_API_KEY") or "").strip()
        if key:
            req.add_header("Authorization", f"Bearer {key}")
            req.add_header("X-API-Key", key)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")
    except Exception as e:
        logger.warning("Inventory API request failed: %s", e)
        return []
    try:
        import json
        raw_list = json.loads(data)
        if not isinstance(raw_list, list):
            raw_list = raw_list.get("items", raw_list.get("data", []))
        out = []
        for i, row in enumerate(raw_list):
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("id", row.get("item_id", i)))
            code = str(row.get("code", row.get("item_code", row.get("sku", ""))))
            name = str(row.get("name", row.get("item_name", row.get("description", ""))))
            unit = str(row.get("unit", row.get("uom", "")))
            category = str(row.get("category", row.get("type", "")))
            out.append(InventoryItem(id=item_id, code=code, name=name, unit=unit, category=category, raw=dict(row)))
        return out
    except Exception as e:
        logger.warning("Inventory API parse failed: %s", e)
        return []
