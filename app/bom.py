"""
BOM (Bill of Materials) from SQ products + inventory matching.
Product-based BOM; match to ERP inventory API; highlight mismatches.
"""
import re
from typing import Optional

from app.schema import SQStructuredData
from app.inventory_client import get_inventory_items, InventoryItem


class BOMLine:
    """Single BOM line (product or derived item)."""
    def __init__(
        self,
        line_index: int,
        product_ref: str,
        item_code_or_name: str,
        quantity: float,
        unit: str,
        dimensions: str = "",
        material: str = "",
        source: str = "product",
        match_status: str = "not_found",
        inventory_item_id: Optional[str] = None,
        inventory_code: Optional[str] = None,
        warning: Optional[str] = None,
    ):
        self.line_index = line_index
        self.product_ref = product_ref
        self.item_code_or_name = item_code_or_name
        self.quantity = quantity
        self.unit = unit
        self.dimensions = dimensions
        self.material = material
        self.source = source
        self.match_status = match_status
        self.inventory_item_id = inventory_item_id
        self.inventory_code = inventory_code
        self.warning = warning

    def to_dict(self) -> dict:
        return {
            "line_index": self.line_index,
            "product_ref": self.product_ref,
            "item_code_or_name": self.item_code_or_name,
            "quantity": self.quantity,
            "unit": self.unit,
            "dimensions": self.dimensions,
            "material": self.material,
            "source": self.source,
            "match_status": self.match_status,
            "inventory_item_id": self.inventory_item_id,
            "inventory_code": self.inventory_code,
            "warning": self.warning,
        }


def _normalize(s: str) -> str:
    return (s or "").strip().lower()


def _fuzzy_score(a: str, b: str) -> float:
    """Simple similarity: 1 if exact match (after norm), else fraction of words in common."""
    if not a or not b:
        return 0.0
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return 1.0
    wa, wb = set(re.findall(r"\w+", na)), set(re.findall(r"\w+", nb))
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)


def _match_line_to_inventory(
    item_code_or_name: str,
    material: str,
    inventory: list[InventoryItem],
) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """
    Match BOM line to inventory. Returns (match_status, inventory_item_id, inventory_code, warning).
    """
    search = f"{item_code_or_name} {material}".strip()
    if not search:
        return "not_found", None, None, "No item description"
    exact = [i for i in inventory if _normalize(i.code) == _normalize(item_code_or_name) or _normalize(i.name) == _normalize(item_code_or_name)]
    if exact:
        return "matched", exact[0].id, exact[0].code or exact[0].name, None
    best_score = 0.0
    best_item: Optional[InventoryItem] = None
    for inv in inventory:
        s1 = _fuzzy_score(search, inv.code or "")
        s2 = _fuzzy_score(search, inv.name)
        s3 = _fuzzy_score(search, inv.category or "")
        score = max(s1, s2, s3 * 0.8)
        if score > best_score and score >= 0.3:
            best_score = score
            best_item = inv
    if best_item:
        return "fuzzy", best_item.id, best_item.code or best_item.name, f"Closest: {best_item.name} ({best_item.code})"
    return "not_found", None, None, f"Item '{item_code_or_name}' not found in inventory"


def generate_bom_from_sq(data: SQStructuredData) -> list[BOMLine]:
    """Product-based BOM: one line per product (name + material as item)."""
    lines = []
    for i, p in enumerate(data.products):
        name = (getattr(p, "name", None) or "").strip()
        material = (getattr(p, "material", None) or "").strip()
        dimensions = (getattr(p, "dimensions", None) or "").strip()
        qty = int(getattr(p, "qty", 1) or 1)
        item_code_or_name = name or f"Product {i+1}"
        if material:
            item_code_or_name = f"{item_code_or_name} – {material}"
        lines.append(BOMLine(
            line_index=i,
            product_ref=name or f"Product {i+1}",
            item_code_or_name=item_code_or_name,
            quantity=float(qty),
            unit="pcs",
            dimensions=dimensions,
            material=material,
            source="product",
            match_status="not_found",
        ))
    return lines


def match_bom_to_inventory(lines: list[BOMLine], inventory: list[InventoryItem]) -> list[str]:
    """
    Update each line with match_status, inventory_item_id, inventory_code, warning.
    Returns list of global warnings (e.g. "Inventory API unavailable").
    """
    warnings: list[str] = []
    for line in lines:
        status, inv_id, inv_code, warn = _match_line_to_inventory(
            line.item_code_or_name,
            line.material,
            inventory,
        )
        line.match_status = status
        line.inventory_item_id = inv_id
        line.inventory_code = inv_code
        line.warning = warn
        if status == "not_found" and warn:
            warnings.append(warn)
    return warnings


def generate_bom(
    data: SQStructuredData,
    line_overrides: Optional[list[dict]] = None,
) -> dict:
    """
    Generate BOM from SQ data, match to inventory API, apply optional line overrides.
    Returns { "project_ref", "lines": [BOMLine.to_dict], "warnings": [] }.
    """
    project_ref = (data.project.project_name or data.project.client_name or "").strip() or "SQ"
    lines = generate_bom_from_sq(data)
    inventory = get_inventory_items()
    global_warnings: list[str] = []
    if not inventory:
        global_warnings.append("No inventory loaded. Set INVENTORY_API_URL for live matching.")
    global_warnings.extend(match_bom_to_inventory(lines, inventory))
    if line_overrides:
        for ov in line_overrides:
            idx = ov.get("line_index")
            inv_id = ov.get("inventory_item_id")
            inv_code = ov.get("inventory_code")
            if idx is not None and 0 <= idx < len(lines):
                line = lines[idx]
                if inv_id is not None:
                    line.inventory_item_id = str(inv_id)
                    line.match_status = "matched"
                    line.warning = None
                if inv_code is not None:
                    line.inventory_code = str(inv_code)
    return {
        "project_ref": project_ref,
        "lines": [ln.to_dict() for ln in lines],
        "warnings": global_warnings,
    }
