"""
PDF pipeline: parse SQ PDF -> structured data (project, products, summary)
with template anchor detection and table extraction.
"""
import base64
import re
from pathlib import Path
from typing import Optional

from pypdf import PdfReader

from app.schema import (
    SQStructuredData,
    Project,
    Product,
    Summary,
)
from app.template_config import TemplateConfig
from app.template_extractor import TABLE_HEADER_TO_KEY
from app.validation import validate_sq_data, _safe_float


def _extract_image_bytes(doc, xref) -> Optional[bytes]:
    """Extract raw image bytes for xref; return None on failure."""
    try:
        base_img = doc.extract_image(xref)
        if base_img:
            b = base_img.get("image")
            if b:
                return b
    except Exception:
        pass
    try:
        import fitz
        pix = fitz.Pixmap(doc, xref)
        if pix.n > 4:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        img_bytes = pix.tobytes(output="png")
        pix = None
        return img_bytes
    except Exception:
        pass
    return None


def extract_images_from_pdf(pdf_path: str | Path, max_images: int = 500) -> list[str]:
    """Extract embedded images from PDF as base64 PNG strings in reading order (top-to-bottom, left-to-right).
    Uses get_image_info() when available so image order matches the reference table; fallback to page renders if none found."""
    out: list[str] = []
    try:
        import fitz
        doc = fitz.open(pdf_path)
        # 1) Try position-based order (reading order) so images match S.No. in the table
        ordered: list[tuple[int, float, float, int]] = []  # (page_no, y0, x0, xref)
        for page_no, page in enumerate(doc):
            if len(ordered) >= max_images:
                break
            info_list = getattr(page, "get_image_info", None)
            if info_list and callable(info_list):
                try:
                    infos = info_list(xrefs=True)
                except TypeError:
                    infos = info_list()
                except Exception:
                    infos = []
                for info in infos:
                    xref = info.get("xref") or 0
                    bbox = info.get("bbox")
                    if not xref or not bbox:
                        continue
                    # bbox is rect-like (x0, y0, x1, y1)
                    y0 = bbox[1] if len(bbox) > 1 else 0
                    x0 = bbox[0] if len(bbox) > 0 else 0
                    ordered.append((page_no, y0, x0, xref))
            else:
                # No get_image_info: fall back to get_images in page order
                for img in page.get_images(full=True):
                    if len(ordered) >= max_images:
                        break
                    ordered.append((page_no, 0, 0, img[0]))
        # Sort by page, then top-to-bottom (y0), then left-to-right (x0)
        ordered.sort(key=lambda x: (x[0], x[1], x[2]))
        seen_xrefs: dict[int, str] = {}  # xref -> base64 to avoid re-extracting same image
        for _page_no, _y0, _x0, xref in ordered:
            if len(out) >= max_images:
                break
            if xref in seen_xrefs:
                out.append(seen_xrefs[xref])
                continue
            raw = _extract_image_bytes(doc, xref)
            if raw:
                b64 = base64.b64encode(raw).decode("ascii")
                seen_xrefs[xref] = b64
                out.append(b64)
        # 2) If no position-based images, use legacy order (get_images per page)
        if len(out) == 0:
            for page in doc:
                for img in page.get_images(full=True):
                    if len(out) >= max_images:
                        break
                    xref = img[0]
                    raw = _extract_image_bytes(doc, xref)
                    if raw:
                        out.append(base64.b64encode(raw).decode("ascii"))
                if len(out) >= max_images:
                    break
        # 3) If no embedded images, render each page to PNG
        if len(out) == 0:
            for page in doc:
                if len(out) >= max_images:
                    break
                try:
                    mat = fitz.Matrix(150 / 72, 150 / 72)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img_bytes = pix.tobytes(output="png")
                    pix = None
                    if img_bytes:
                        out.append(base64.b64encode(img_bytes).decode("ascii"))
                except Exception:
                    pass
        doc.close()
    except Exception:
        pass
    return out


# Anchors for PDF text (spec: "Sales Quotation", "Project Name", "S.No")
PDF_ANCHORS = [
    "sales quotation",
    "project name",
    "client name",
    "quotation no",
    "date",
    "prepared by",
    "s.no",
    "sr no",
]


def _ocr_fallback(pdf_path: str | Path, max_pages: int = 3) -> str:
    """When pypdf returns little text, run OCR on first pages."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
        images = convert_from_path(str(pdf_path), first_page=1, last_page=max_pages, dpi=150)
        parts = []
        for img in images:
            parts.append(pytesseract.image_to_string(img))
        return "\n".join(parts)
    except Exception:
        return ""


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """Extract raw text using pypdf; fallback to OCR if text is empty or very short."""
    reader = PdfReader(pdf_path)
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    out = "\n".join(parts)
    if len(out.strip()) < 200:
        ocr_text = _ocr_fallback(pdf_path)
        if ocr_text:
            out = ocr_text
    return out


def _normalize(s: str) -> str:
    return (s or "").strip()


def _parse_header_from_text(text: str) -> dict[str, str]:
    """Heuristic: find label: value or label value on same/next line."""
    out: dict[str, str] = {}
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for anchor in ["project name", "client name", "quotation no", "quotation no.", "date", "prepared by"]:
            if anchor in line_lower:
                # try "Label: Value" or "Label Value"
                rest = line[line_lower.index(anchor) + len(anchor) :].strip()
                rest = rest.lstrip(":").strip()
                key = anchor.replace(" ", "_").replace(".", "")
                if rest:
                    out[key] = rest
                elif i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not next_line.lower().startswith(("s.no", "sr no", "product")):
                        out[key] = next_line
                break
    return out


def _parse_price_line(line: str) -> tuple[str, str, str]:
    """Extract unit_price, qty, amount from line like '₹ 7,302 1 ₹7,302' or '7302 1 7302'."""
    unit_price, qty, amount = "", "", ""
    line_clean = line.replace(",", "").replace("\u20b9", "").replace("₹", "").strip()
    nums = re.findall(r"[\d.]+", line_clean)
    if len(nums) >= 3:
        unit_price, qty, amount = nums[0], nums[1], nums[2]
    elif len(nums) == 2:
        unit_price, qty = nums[0], nums[1]
        amount = nums[1]
    elif len(nums) == 1:
        unit_price = amount = nums[0]
        qty = "1"
    return (unit_price, qty, amount)


def _parse_price_line_last_three(line: str) -> tuple[str, str, str]:
    """Extract unit_price, qty, amount from the LAST three numbers in a line (for lines that also contain dimensions)."""
    unit_price, qty, amount = "", "", ""
    line_clean = line.replace(",", "").replace("\u20b9", "").replace("₹", "").strip()
    nums = re.findall(r"[\d.]+", line_clean)
    if len(nums) >= 3:
        unit_price, qty, amount = nums[-3], nums[-2], nums[-1]
    return (unit_price, qty, amount)


# Month names for date-like row filter (e.g. "24 January2026")
_MONTH_YEAR_PATTERN = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s*\d{4}$",
    re.IGNORECASE,
)

# Stop parsing product table when we hit summary or Terms & Conditions
_TABLE_END_RE = re.compile(
    r"^(sub\s*total|total|grand\s*total|tax\b|terms\s*&?\s*conditions?|gst\s*\(?\d*%?\)?)\b",
    re.IGNORECASE,
)

# Phrases that indicate a row is from Terms & Conditions, not a product
_TERMS_PHRASES = (
    "validity of", "validity of quotation", "taxes &", "taxes and duties",
    "payment terms", "delivery period", "transportation", "design &", "design and customization",
    "warranty", "ownership of", "ownership of goods", "cancellations", "jurisdiction",
    "wood used", "foam", "finish", "terms:", "conditions:",
)
# Single words that are T&C section titles (when price/amount are zero)
_TERMS_WORDS = frozenset(
    {"validity", "taxes", "payment", "delivery", "transportation", "design", "ownership",
     "cancellations", "jurisdiction", "wood", "foam", "finish", "warranty"}
)

# Phrases that indicate a line is header/company/terms, not product description
_DESCRIPTION_SKIP_PHRASES = (
    "arten lifestyle", "pvt. ltd", "sales quotation", "project name", "quotation no",
    "validity of", "validity of quotation", "terms and conditions", "terms & conditions",
    "payment terms", "delivery period", "this quotation is valid",
)


def _split_name_and_dimensions(text: str) -> tuple[str, str]:
    """
    If text contains a dimension pattern (e.g. 20" X 16" or 2' Dia), split into product name and dimensions.
    Source table has Name (e.g. "Side Table") and Specs (e.g. "20\" X 16\" X 20\"H") as separate columns.
    """
    if not text or not text.strip():
        return (text.strip(), "")
    # Dimension pattern: space(s) + number + optional " or ' + X or Dia (e.g. " 20\" X", " 2' Dia")
    m = re.search(r"\s+\d+\s*[\"']?\s*(?:[xX×]|Dia)", text)
    if m:
        name_part = text[: m.start()].strip()
        dim_part = text[m.start() :].strip()
        return (name_part, dim_part) if name_part else (text.strip(), "")
    return (text.strip(), "")


def _is_section_header_row(row: dict[str, str]) -> bool:
    """True if row looks like a floor/section header (e.g. G.F. with 'sofa') not a product."""
    name = (row.get("name") or "").strip()
    dims = (row.get("dimensions") or "").strip().lower()
    up = (row.get("unit_price") or "").strip()
    amt = (row.get("amount") or "").strip()
    if not name or len(name) > 30:
        return False
    try:
        if float(up.replace(",", "")) != 0 or float(amt.replace(",", "")) != 0:
            return False
    except ValueError:
        pass
    if re.match(r"^[A-Z]\.?[A-Z]?\.?$", name.strip()) and dims in ("sofa", "table", "chair", "bed", "furniture"):
        return True
    return False


def _is_spurious_row(row: dict[str, str]) -> bool:
    """Return True if row looks like page/date noise (e.g. sr_no=24, name=January2026)."""
    name = (row.get("name") or "").strip()
    sr_no_s = (row.get("sr_no") or "").strip()
    if not name:
        return False
    if _MONTH_YEAR_PATTERN.match(name):
        return True
    try:
        n = int(sr_no_s)
        if n > 20 and len(name) <= 15 and re.search(r"20\d{2}", name):
            return True
    except ValueError:
        pass
    return False


def _is_terms_and_conditions_row(row: dict[str, str]) -> bool:
    """Return True if row looks like a Terms & Conditions line (not a product).

    Matching is **anchored** — the T&C phrase must START the row's name or description.
    Substring matching was too aggressive: many products legitimately contain words like
    "finish" / "foam" / "warranty" inside their specs (e.g. "ANTIQUE GOLD FINISH"), so a
    product whose price extraction failed (unit_price=0) would be misclassified as T&C
    and silently dropped. (This was the dominant cause of the "67 items -> 39 items"
    regression on the Maanvi Homes SQ.)
    """
    name = (row.get("name") or "").strip().lower()
    desc = (row.get("description") or "").strip().lower()
    unit_price = (row.get("unit_price") or "").strip()
    amount = (row.get("amount") or "").strip()
    if not name and not desc:
        return False
    try:
        up_val = float(unit_price.replace(",", "")) if unit_price else 0
        amt_val = float(amount.replace(",", "")) if amount else 0
    except ValueError:
        up_val = amt_val = 0
    if up_val != 0 or amt_val != 0:
        return False
    # Anchored match: phrase must appear at the start of name or description
    for phrase in _TERMS_PHRASES:
        if name.startswith(phrase) or desc.startswith(phrase):
            return True
    if name in _TERMS_WORDS or desc in _TERMS_WORDS:
        return True
    return False


def _unmerge_name_cell(rest: str) -> tuple[str, str, str, str, str]:
    """
    When the first cell merges name + dimensions + unit_price qty amount (e.g. row 9),
    extract name, dimensions, unit_price, qty, amount. Returns (name, dimensions, unit_price, qty, amount);
    dimensions/unit_price/qty/amount may be empty if not present.
    """
    name, dimensions, unit_price, qty, amount = "", "", "", "", ""
    rest = (rest or "").strip()
    if not rest:
        return (name, dimensions, unit_price, qty, amount)
    # Find trailing numeric block: optional ₹/Rs., then numbers like "31200 2" or "312002" and "62400"
    clean = rest.replace(",", "").replace("\u20b9", "").replace("₹", "")
    clean = re.sub(r"\bRs\.", " ", clean, flags=re.IGNORECASE)  # avoid ".62400" from "Rs.62,400"
    nums = re.findall(r"[\d.]+", clean)
    if len(nums) >= 3:
        unit_price, qty, amount = nums[-3], nums[-2], nums[-1]
        last_num_match = list(re.finditer(r"[\d,]+", rest))
        if len(last_num_match) >= 3:
            rest = rest[: last_num_match[-3].start()].strip()
        elif last_num_match:
            rest = rest[: last_num_match[-1].start()].strip()
        rest = re.sub(r"\s*[₹\u20b9]?\s*$", "", rest).strip()
    elif len(nums) == 2:
        a, b = nums[0], nums[1]
        try:
            ai, bi = int(float(a)), int(float(b))
            if ai > 0 and bi > 0:
                # Concatenated unit_price + qty (e.g. 312002 = 31200 and 2, amount 62400)
                if ai > bi and 1 <= (ai % 10) <= 9:
                    up, q = ai // 10, ai % 10
                    if up * q == bi:
                        unit_price, qty, amount = str(up), str(q), str(bi)
                    else:
                        unit_price, amount = str(ai), str(bi)
                        qty = str(round(bi / ai)) if ai and bi % ai == 0 else "1"
                else:
                    unit_price, amount = str(ai), str(bi)
                    qty = str(round(bi / ai)) if ai and bi % ai == 0 else "1"
            else:
                unit_price, amount = a, b
                qty = "1"
        except (ValueError, ZeroDivisionError):
            unit_price, amount = a, b
            qty = "1"
        last_num_match = list(re.finditer(r"[\d,]+", rest))
        if len(last_num_match) >= 2:
            rest = rest[: last_num_match[-2].start()].strip()
        elif last_num_match:
            rest = rest[: last_num_match[-1].start()].strip()
        rest = re.sub(r"\s*[₹\u20b9]?\s*$", "", rest).strip()
    if " dimensions:" in rest.lower():
        idx = rest.lower().find(" dimensions:")
        name = rest[:idx].strip()
        dimensions = rest[idx + len(" dimensions:"):].strip()
    else:
        name = rest.strip()
        # Source has Name and Specs as separate columns; split e.g. "Side Table 20\" X 16\" X 20\"H" -> name "Side Table", dimensions "20\" X 16\" X 20\"H"
        name_only, dim_part = _split_name_and_dimensions(name)
        if dim_part:
            name, dimensions = name_only, dim_part
    return (name, dimensions, unit_price, qty, amount)


def _split_embedded_item_lines(lines: list[str]) -> list[str]:
    """
    Split lines that contain an embedded next-item pattern so item 10 (etc.) gets its own line.
    E.g. "Bar Chair Dimensions: ... 31200 2 62400 10 Kid's Bedroom Bed Base Dimensions: ..."
    -> ["Bar Chair Dimensions: ... 31200 2 62400", "10 Kid's Bedroom Bed Base Dimensions: ..."]
    Avoids mixing items 9 and 10 when PDF has no separate row for item 10.
    """
    out: list[str] = []
    # Pattern: space(s) + item number (1-2 digits) + space(s) + name (starts with letter, then letters/apostrophe/spaces)
    # followed by "Dimensions:" or end or a long number (price). Avoids splitting " 2 ₹62,400" (qty 2).
    embedded_item_re = re.compile(
        r"\s+(\d{1,2})\s+([A-Za-z][A-Za-z'\s]{2,}?)(?=\s+Dimensions:|\s+\d{4,}|\s*₹|\s*\u20b9|\s*$)",
        re.IGNORECASE,
    )
    for line in lines:
        rest = line
        while rest:
            m = embedded_item_re.search(rest)
            if not m:
                out.append(rest.strip())
                break
            # Only split if the number looks like an item number (e.g. 10, 11) not a quantity (often 1-2 digits after price)
            num = int(m.group(1))
            before = rest[: m.start()].strip()
            after = (m.group(1) + " " + m.group(2).strip() + rest[m.end() :].lstrip()).strip()
            if before:
                out.append(before)
            # Continue splitting the "after" part in case it has another embedded item (e.g. 11)
            rest = after
    return out


def _parse_table_multiline(lines: list[str], header_idx: int) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """
    Parse when each product is a multi-line block: first line "1 Name", middle lines specs/description,
    last line "Price Qty Amount" (e.g. ₹ 7,302 1 ₹7,302).

    Returns (accepted_rows, skipped_rows). Each skipped row is
    {"sr_no", "name", "reason"} so callers can surface per-row skip causes via
    validation_errors instead of dropping silently.
    """
    rows: list[dict[str, str]] = []
    i = header_idx + 1
    while i < len(lines):
        line = lines[i]
        if _TABLE_END_RE.match(line.strip()):
            break
        # Product start: line like "1 Stand" or "2 Storage" or "9 Bar Chair Dimensions: ... 31200 2 ₹62,400"
        m = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if m:
            sr_no = m.group(1)
            raw_rest = _normalize(m.group(2))
            # Unmerge when first cell contains Dimensions + price/qty/amount (e.g. row 9)
            u_name, u_dims, u_price, u_qty, u_amt = _unmerge_name_cell(raw_rest)
            if u_price or u_qty or u_amt:
                name = u_name or raw_rest
                dimensions = u_dims
                unit_price, qty, amount = u_price, u_qty, u_amt
            else:
                name = raw_rest
                dimensions = ""
                unit_price, qty, amount = "", "", ""
            # Skip block if this line is spurious (e.g. "24 January2026"); otherwise we consume the next line ("8 Master Bedroom Coffee Table") and lose item 8
            tentative = {"sr_no": sr_no, "name": name, "description": "", "dimensions": dimensions, "qty": qty or "1", "unit_price": unit_price, "amount": amount}
            if _is_spurious_row(tentative):
                i += 1
                continue
            description_parts = [] if (u_price or u_qty or u_amt) else []
            i += 1
            while i < len(lines):
                ln = lines[i]
                if _TABLE_END_RE.match(ln.strip()):
                    break
                # Next item on its own line: "10 Kid's Bedroom Bed Base Dimensions: ..." (avoids mixing 9 and 10)
                next_m = re.match(r"^\s*(\d+)\s+(.+)$", ln)
                if next_m and next_m.group(1) != sr_no:
                    try:
                        next_num = int(next_m.group(1))
                        curr_num = int(sr_no)
                        if next_num == curr_num + 1:
                            # Flush current row and start next item in same iteration
                            description = " ".join(description_parts) if description_parts else ""
                            rows.append({
                                "sr_no": sr_no,
                                "name": name,
                                "description": description,
                                "dimensions": dimensions,
                                "area": "",
                                "material": "",
                                "finish": "",
                                "qty": qty or "1",
                                "unit_price": unit_price,
                                "amount": amount,
                            })
                            sr_no = next_m.group(1)
                            raw_name = _normalize(next_m.group(2))
                            # Unmerge name+dimensions+price when next line contains them (e.g. "2 Side Table 20\" X 20\" X 16\"H ₹24,750 1 ₹24,750")
                            u_name, u_dims, u_price, u_qty, u_amt = _unmerge_name_cell(raw_name)
                            if u_price or u_qty or u_amt:
                                name = u_name or raw_name
                                dimensions = u_dims
                                unit_price, qty, amount = u_price, u_qty, u_amt
                            elif " dimensions:" in raw_name.lower():
                                idx = raw_name.lower().find(" dimensions:")
                                name = raw_name[:idx].strip()
                                dimensions = raw_name[idx + len(" dimensions:"):].strip()
                                unit_price, qty, amount = "", "", ""
                            else:
                                name = raw_name
                                dimensions = ""
                                unit_price, qty, amount = "", "", ""
                            description_parts = []
                            i += 1
                            continue
                    except ValueError:
                        pass
                # PDF may have product rows without leading sr_no (columns split so "13" is missing). If line parses as full product and name differs from current, treat as next row.
                if "\u20b9" in ln or "₹" in ln:
                    u_name, u_dims, u_price, u_qty, u_amt = _unmerge_name_cell(_normalize(ln))
                    if (u_price or u_qty or u_amt) and (u_name or u_dims):
                        # Parsed name must look like a product name (letters), not dimension-only (e.g. "20\" X 16\"")
                        u_looks_like_name = u_name and len(re.findall(r"[A-Za-z]{2,}", u_name)) > 0
                        # Same product continuation (e.g. "Side Table 20\" X 16\" ₹18,000" for current "Side Table") -> use as price line below
                        name_eq = (u_name or "").strip() == (name or "").strip()
                        name_contained = (u_name and name and (u_name in name or name in u_name))
                        if (name_eq or name_contained) or not u_looks_like_name:
                            pass  # fall through to price line handling
                        else:
                            # Different product (e.g. "Living Area L Shape Sofa" vs "Living Area Sofa 7'3''") -> flush current, start next
                            description = " ".join(description_parts) if description_parts else ""
                            rows.append({
                                "sr_no": sr_no,
                                "name": name,
                                "description": description,
                                "dimensions": dimensions,
                                "area": "",
                                "material": "",
                                "finish": "",
                                "qty": qty or "1",
                                "unit_price": unit_price,
                                "amount": amount,
                            })
                            sr_no = str(int(sr_no) + 1)
                            name = u_name or _normalize(ln)
                            dimensions = u_dims
                            unit_price, qty, amount = u_price, u_qty, u_amt
                            description_parts = []
                            i += 1
                            continue
                # Price line: has ₹ or pattern "num num num" without "X" (e.g. "₹ 7,302 1 ₹7,302" or "36400 2 ?62,400")
                is_price_line = "\u20b9" in ln or "₹" in ln
                has_x = " x " in ln.lower() or " × " in ln
                nums_in_ln = re.findall(r"[\d,]+", ln)
                only_nums_regex = re.search(r"^\s*[₹\s\d,.]+\s*$", ln)
                # Allow lines that are mostly numbers (e.g. one stray "?" instead of ₹)
                stripped = re.sub(r"[\s\d,.\u20b9₹]", "", ln)
                mostly_nums = len(stripped) <= 1 and len(nums_in_ln) >= 2
                alt_price = not is_price_line and len(nums_in_ln) >= 2 and not has_x and (only_nums_regex or mostly_nums)
                if not is_price_line and has_x:
                    pass  # dimensions line, not price
                elif (is_price_line or alt_price) and not unit_price:
                    # Line has both dimensions (" X ") and price: use last three numbers (price, qty, amount), not first three (dimension digits)
                    if has_x:
                        unit_price, qty, amount = _parse_price_line_last_three(ln)
                    else:
                        unit_price, qty, amount = _parse_price_line(ln)
                    i += 1
                    break
                # Dimensions: "1300 X 650 X 350" or "900 Dia X 400 H / 700 Dia X 450 H" (or same line + "Base in HDMR...")
                dim_m = re.match(r"^([\d\s]+[xX×]\s*[\d\s]+.*)$", ln)
                has_dim_pattern = re.search(r"\d+\s*([xX×]|Dia\s*[xX×])\s*\d+", ln)
                if not dimensions and (dim_m or has_dim_pattern):
                    ln_norm = _normalize(ln)
                    # If line also has description (e.g. "900 Dia X 400 H ... Base in HDMR"), split
                    pos = -1
                    for sep in (" Base ", " Top in ", " Finish ", " construction ", " Internal "):
                        p = ln_norm.upper().find(sep.upper())
                        if p > 0 and (pos < 0 or p < pos):
                            pos = p
                    if pos > 0:
                        dimensions = ln_norm[:pos].strip()
                        if ln_norm[pos:].strip():
                            description_parts.append(ln_norm[pos:].strip())
                    else:
                        dimensions = ln_norm
                else:
                    # Populate dimensions from "Dimensions: ..." lines so the column is not empty
                    if not dimensions and "dimensions:" in ln.lower():
                        idx = ln.lower().find("dimensions:")
                        dim_val = _normalize(ln[idx + len("dimensions:"):])
                        if dim_val:
                            dimensions = dim_val
                    else:
                        ln_lower = ln.lower()
                        # Skip lines that are company/terms or that contain dimension-like content (should stay in dimensions, not description)
                        has_dim_in_line = bool(re.search(r"\d+\s*([xX×]|Dia\s*[xX×])\s*\d+|\d+\s*[\"']\s*[xX×]", ln))
                        if not any(p in ln_lower for p in _DESCRIPTION_SKIP_PHRASES) and not has_dim_in_line:
                            description_parts.append(_normalize(ln))
                i += 1
            description = " ".join(description_parts) if description_parts else ""
            rows.append({
                "sr_no": sr_no,
                "name": name,
                "description": description,
                "dimensions": dimensions,
                "area": "",
                "material": "",
                "finish": "",
                "qty": qty or "1",
                "unit_price": unit_price,
                "amount": amount,
            })
            continue
        i += 1
    accepted: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for r in rows:
        if _is_spurious_row(r):
            skipped.append({"sr_no": r.get("sr_no", ""), "name": (r.get("name") or "")[:60], "reason": "spurious_row"})
        elif _is_terms_and_conditions_row(r):
            skipped.append({"sr_no": r.get("sr_no", ""), "name": (r.get("name") or "")[:60], "reason": "terms_and_conditions"})
        elif _is_section_header_row(r):
            skipped.append({"sr_no": r.get("sr_no", ""), "name": (r.get("name") or "")[:60], "reason": "section_header"})
        else:
            accepted.append(r)
    return accepted, skipped


def _split_table_line(line: str) -> list[str]:
    """Split a table line (header or data) the same way for column alignment."""
    parts = re.split(r"\s{2,}|\t", line)
    if len(parts) >= 3:
        return parts
    parts = re.split(r"\s+", line)
    return parts


def _parse_header_columns(header_line: str) -> list[tuple[int, str]]:
    """
    Parse header line to build index -> schema_key mapping.
    Uses same split as data lines. Returns list of (part_index, schema_key).
    """
    parts = _split_table_line(header_line)
    result: list[tuple[int, str]] = []
    for idx, part in enumerate(parts):
        norm = (part or "").strip().lower()
        if not norm:
            continue
        for label, key in TABLE_HEADER_TO_KEY.items():
            if label in norm or norm in label:
                result.append((idx, key))
                break
    return result


def _parse_table_from_text(text: str, config: Optional[TemplateConfig] = None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """
    Heuristic table extraction. If header suggests multi-line blocks (Specs, Price Qty Amount),
    use block parsing; else one line per row.
    Splits lines that contain an embedded next-item (e.g. "10 Kid's Bedroom...") so items don't mix.

    Returns (accepted_rows, skipped_rows). Skipped rows carry a reason so callers can
    surface per-row drop causes.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    lines = _split_embedded_item_lines(lines)
    header_idx = -1
    header_line = ""
    for i, line in enumerate(lines):
        if re.search(r"s\.?\s*no\.?|sr\.?\s*no\.?", line, re.I):
            header_idx = i
            header_line = line
            break
    if header_idx < 0:
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if "product" in line_lower and ("qty" in line_lower or "amount" in line_lower or "description" in line_lower):
                header_idx = i
                header_line = line
                break
    if header_idx < 0:
        return [], []

    header_lower = header_line.lower()
    use_multiline = "specs" in header_lower and ("price" in header_lower or "qty" in header_lower) and "amount" in header_lower
    if use_multiline:
        return _parse_table_multiline(lines, header_idx)

    # Header-driven column mapping for single-line tables
    header_map = _parse_header_columns(header_line)
    if not header_map and config and config.table_columns:
        # Fallback: use template config column order (col_index is 1-based)
        header_map = [
            (tc.col_index - 1, tc.key)
            for tc in sorted(config.table_columns, key=lambda t: t.col_index)
        ]
    if not header_map:
        # Fallback: fixed indices for backward compatibility
        header_map = [
            (0, "sr_no"),
            (1, "name"),
            (2, "dimensions"),
            (3, "area"),
            (4, "material"),
            (5, "finish"),
            (6, "qty"),
            (7, "unit_price"),
            (8, "amount"),
        ]

    expected_keys = ("sr_no", "name", "description", "dimensions", "area", "material", "finish", "qty", "unit_price", "amount", "remarks")
    rows: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for i in range(header_idx + 1, len(lines)):
        line = lines[i]
        if _TABLE_END_RE.match(line.strip()):
            break
        parts = _split_table_line(line)
        if len(parts) < 2:
            continue
        row = {k: "" for k in expected_keys}
        row["qty"] = "1"
        for idx, key in header_map:
            if key in expected_keys and idx < len(parts):
                row[key] = _normalize(parts[idx])
        if row.get("description") == "" and row.get("name"):
            row["description"] = row["name"]
        if row["sr_no"] and not re.match(r"^\d+\.?\d*$", row["sr_no"]):
            skipped.append({"sr_no": row.get("sr_no", ""), "name": (row.get("name") or "")[:60], "reason": "sr_no_non_numeric"})
            continue
        if _is_spurious_row(row):
            skipped.append({"sr_no": row.get("sr_no", ""), "name": (row.get("name") or "")[:60], "reason": "spurious_row"})
            continue
        if _is_terms_and_conditions_row(row):
            skipped.append({"sr_no": row.get("sr_no", ""), "name": (row.get("name") or "")[:60], "reason": "terms_and_conditions"})
            continue
        if _is_section_header_row(row):
            skipped.append({"sr_no": row.get("sr_no", ""), "name": (row.get("name") or "")[:60], "reason": "section_header"})
            continue
        rows.append(row)
    return rows, skipped


def _parse_totals_from_text(text: str) -> dict[str, float]:
    """Extract subtotal, tax, grand total from text."""
    out: dict[str, float] = {"subtotal": 0.0, "tax": 0.0, "grand_total": 0.0}
    for line in text.splitlines():
        line_lower = line.lower()
        if "sub" in line_lower and "total" in line_lower:
            nums = re.findall(r"[\d,]+\.?\d*", line)
            if nums:
                out["subtotal"] = _safe_float(nums[-1])
        if re.match(r"^tax\b", line_lower):
            nums = re.findall(r"[\d,]+\.?\d*", line)
            if nums:
                out["tax"] = _safe_float(nums[-1])
        if "grand" in line_lower and "total" in line_lower:
            nums = re.findall(r"[\d,]+\.?\d*", line)
            if nums:
                out["grand_total"] = _safe_float(nums[-1])
    return out


def _extract_rows_via_pdfplumber(pdf_path: str | Path) -> list[dict[str, str]]:
    """Extract product rows using pdfplumber's table detector.

    pdfplumber preserves column boundaries — unlike the pypdf text stream we use as a
    fallback, it doesn't collapse "Sofa (3470+925)" into a price-shaped digit run, and
    it doesn't split a single product cell into two rows just because the cell wraps
    across visual lines. For multi-page tables, the first page's header drives the
    column→key mapping and later pages inherit it (most SQ PDFs only repeat the header
    on page 1).

    Returns rows in the same dict shape as ``_parse_table_from_text`` so the rest of
    the pipeline (image alignment, validation, schema mapping) is unchanged.
    Returns `[]` on any failure so callers can fall back to the text-heuristic path.

    Writes a debug log to `<output>/last-pdfplumber.log` on every run — useful when the
    extractor silently returns 0 rows because the table detector found nothing or
    because header detection missed.
    """
    log_lines: list[str] = []
    def log(msg: str) -> None:
        log_lines.append(msg)

    try:
        import pdfplumber  # local import: optional dep
    except ImportError:
        log("ABORT: pdfplumber not importable")
        _write_pdfplumber_log(log_lines)
        return []

    expected_keys = ("sr_no", "name", "description", "dimensions", "area", "material", "finish", "qty", "unit_price", "amount", "remarks")
    column_map: list[tuple[int, str]] = []
    header_seen = False
    rows: list[dict[str, str]] = []

    def _clean(c) -> str:
        if c is None:
            return ""
        s = str(c).strip()
        if s.startswith("(cid:"):
            return ""
        return s

    def _clean_money(s: str) -> str:
        return s.replace(",", "").replace("₹", "").replace("₹", "").strip()

    # Default column map used when the header row isn't recognised. Matches the
    # Arten SQ template (S.No | Name | Area | Image | Specs | Price | Qty | Amount | Remarks).
    DEFAULT_COL_MAP: list[tuple[int, str]] = [
        (0, "sr_no"), (1, "name"), (2, "area"), (3, "images"),
        (4, "dimensions"), (5, "unit_price"), (6, "qty"), (7, "amount"), (8, "remarks"),
    ]

    def _try_match_header(cells: list[str]) -> list[tuple[int, str]]:
        new_map: list[tuple[int, str]] = []
        for idx, cell in enumerate(cells):
            norm = cell.strip().lower().rstrip(".").rstrip(":")
            if not norm:
                continue
            for label, key in TABLE_HEADER_TO_KEY.items():
                label_norm = label.rstrip(".")
                if label_norm == norm or label_norm in norm or norm in label_norm:
                    new_map.append((idx, key))
                    break
        return new_map

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            log(f"opened pdf: pages={len(pdf.pages)}")
            for page_num, page in enumerate(pdf.pages, start=1):
                # Try strategies in order: lines (explicit borders), lines_strict,
                # then default ("text"). First non-empty result wins for this page.
                tables = []
                for strategy in (
                    {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
                    {"vertical_strategy": "lines_strict", "horizontal_strategy": "lines_strict"},
                    {"vertical_strategy": "text", "horizontal_strategy": "text"},
                    {},  # pdfplumber defaults
                ):
                    try:
                        tables = page.find_tables(table_settings=strategy) if strategy else page.find_tables()
                    except Exception as exc:
                        log(f"page {page_num} strategy={strategy}: exception {exc!r}")
                        tables = []
                    if tables:
                        log(f"page {page_num} strategy={strategy or 'default'}: {len(tables)} table(s)")
                        break
                if not tables:
                    log(f"page {page_num}: no tables found")
                    continue
                for ti, table in enumerate(tables):
                    extracted = table.extract()
                    if not extracted:
                        log(f"page {page_num} table {ti}: extract() empty")
                        continue
                    log(f"page {page_num} table {ti}: {len(extracted)} raw row(s), {len(extracted[0]) if extracted else 0} col(s)")
                    for ri, raw_row in enumerate(extracted):
                        cells = [_clean(c) for c in raw_row]
                        joined = " | ".join(cells).lower()
                        # Header detection: row containing "s.no" / "sr no"
                        if not header_seen:
                            if "s.no" in joined or "sr no" in joined or "sr.no" in joined or "product" in joined:
                                candidate_map = _try_match_header(cells)
                                if candidate_map:
                                    column_map = candidate_map
                                    header_seen = True
                                    log(f"page {page_num} table {ti} row {ri}: HEADER → {column_map}")
                                    continue
                            # First numeric row on the first table — assume sr_no=1 starts a product table and apply default mapping
                            if re.fullmatch(r"\d+\.?\d*", cells[0]) if cells else False:
                                column_map = DEFAULT_COL_MAP
                                header_seen = True
                                log(f"page {page_num} table {ti} row {ri}: inferred default header (cell0={cells[0]!r})")
                                # Fall through to process this row as data
                        if not column_map:
                            continue  # rows before any header are noise
                        # Build row using header mapping
                        row = {k: "" for k in expected_keys}
                        row["qty"] = "1"
                        for idx, key in column_map:
                            if key in expected_keys and idx < len(cells):
                                row[key] = cells[idx]
                        sr_no = (row.get("sr_no") or "").strip()
                        if not re.match(r"^\d+\.?\d*$", sr_no):
                            continue
                        if not (row.get("name") or row.get("description")):
                            continue
                        if row.get("unit_price"):
                            row["unit_price"] = _clean_money(row["unit_price"])
                        if row.get("amount"):
                            row["amount"] = _clean_money(row["amount"])
                        if row.get("qty"):
                            row["qty"] = re.sub(r"[^\d.]", "", row["qty"]) or "1"
                        # Multi-line specs: take dimension-like lines, leave rest in material
                        specs = (row.get("dimensions") or "").strip()
                        if specs:
                            lines = [l.strip() for l in specs.splitlines() if l.strip()]
                            dim_lines: list[str] = []
                            other_lines: list[str] = []
                            for ln in lines:
                                ln_lower = ln.lower()
                                if ln_lower.startswith("dimensions:"):
                                    dim_lines.append(ln.split(":", 1)[1].strip())
                                elif re.search(r"\b(?:dia\s*)?\d+\s*(?:mm|MM|cm|CM|m|M)?\s*[xX×]\s*", ln):
                                    dim_lines.append(ln)
                                elif re.search(r"\b\d+\s*mm\b", ln_lower):
                                    dim_lines.append(ln)
                                else:
                                    other_lines.append(ln)
                            if dim_lines:
                                row["dimensions"] = " ".join(dim_lines)
                            else:
                                row["dimensions"] = specs.replace("\n", " ").strip()
                            if other_lines and not row.get("material"):
                                row["material"] = " ".join(other_lines)
                        rows.append(row)
        log(f"final: {len(rows)} rows; header_seen={header_seen}")
    except Exception as exc:
        log(f"ABORT: top-level exception {exc!r}")
        _write_pdfplumber_log(log_lines)
        return []
    _write_pdfplumber_log(log_lines)
    return rows


def _write_pdfplumber_log(lines: list[str]) -> None:
    try:
        out_dir = Path(__file__).resolve().parent.parent / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "last-pdfplumber.log", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def parse_pdf_to_structured_data(
    pdf_path: str | Path,
    config: Optional[TemplateConfig] = None,
    use_vision_views: bool = False,
) -> tuple[SQStructuredData, list[dict[str, str]]]:
    """
    Parse SQ PDF into SQStructuredData.
    Uses config for column mapping if provided; otherwise uses heuristics from text.
    When use_vision_views=True, classifies view per image (vision API) and sets Product.image_views.

    Returns (data, skipped). `skipped` is a list of `{sr_no, name, reason}` dicts for rows
    that were detected during text parsing but rejected by a filter — callers surface this
    via validation_errors so silent drops become visible to the user.
    """
    text = extract_text_from_pdf(pdf_path)
    header = _parse_header_from_text(text)
    # Try pdfplumber's table extractor first — it respects column boundaries and won't
    # mis-split rows when product names contain embedded numbers (e.g. "Sofa (3470+925)").
    # Fall back to the text-heuristic only when pdfplumber finds nothing — even a partial
    # pdfplumber result is more correct than the heuristic on tables it does detect.
    table_rows = _extract_rows_via_pdfplumber(pdf_path)
    skipped: list[dict[str, str]] = []
    if not table_rows:
        table_rows, skipped = _parse_table_from_text(text, config)
    totals = _parse_totals_from_text(text)
    extracted_images = extract_images_from_pdf(pdf_path)

    project = Project(
        project_name=header.get("project_name", ""),
        client_name=header.get("client_name", ""),
        quotation_no=header.get("quotation_no", ""),
        date=header.get("date", ""),
        prepared_by=header.get("prepared_by", ""),
    )

    products: list[Product] = []
    # When num_images > num_products, assume leading images are non-product (e.g. logo) and skip them.
    # When num_images == num_products, use direct mapping (image i -> product i). If first image is much
    # smaller than the rest (likely a logo), skip it so product 0 gets the first product image.
    num_products = len(table_rows)
    num_images = len(extracted_images)
    image_offset = (num_images - num_products) if num_images > num_products else 0
    if image_offset == 0 and num_images == num_products and num_products >= 2 and num_images >= 2:
        try:
            sizes = [len(s) for s in extracted_images[:num_images]]
            if len(sizes) >= 2:
                med = sorted(sizes)[len(sizes) // 2]
                if med > 0 and sizes[0] < 0.5 * med:
                    image_offset = 1
        except Exception:
            pass
    for i, row in enumerate(table_rows):
        img_idx = image_offset + i
        product_images = [extracted_images[img_idx]] if img_idx < len(extracted_images) else []
        name = row.get("name", "")
        unit_price = _safe_float(row.get("unit_price", 0))
        qty = int(_safe_float(row.get("qty", 1))) or 1
        amount = _safe_float(row.get("amount", 0))
        dimensions = (row.get("dimensions") or "").strip()
        if unit_price == 0 and dimensions and re.match(r"^[\d,]+\.?\d*$", dimensions.replace(",", "")):
            unit_price = _safe_float(dimensions.replace(",", ""))
            if unit_price > 0:
                dimensions = ""
        if unit_price > 0 and (amount == 0 or abs(amount - unit_price * qty) > 0.01):
            amount = unit_price * qty
        if use_vision_views and product_images:
            from app.image_ai import classify_view
            image_views = [classify_view(name, img) for img in product_images]
        else:
            image_views = []
        products.append(
            Product(
                sr_no=int(_safe_float(row.get("sr_no", 0))) or (i + 1),
                name=name,
                description=row.get("description", row.get("name", "")),
                dimensions=dimensions,
                area=row.get("area", ""),
                material=row.get("material", ""),
                finish=row.get("finish", ""),
                qty=qty,
                unit_price=unit_price,
                amount=amount,
                remarks=row.get("remarks", ""),
                images=product_images,
                image_views=image_views,
            )
        )

    summary = Summary(
        subtotal=totals.get("subtotal", 0),
        tax=totals.get("tax", 0),
        grand_total=totals.get("grand_total", 0),
    )

    data = SQStructuredData(
        project=project,
        products=products,
        summary=summary,
        extracted_images=extracted_images,
    )

    # Debug dump (gated by env var): writes per-row diagnostics so future "X items dropped"
    # bugs can be inspected without re-instrumenting. Off by default.
    import os
    if os.environ.get("DEBUG_PARSE") == "1":
        try:
            import hashlib
            import json as _json
            out_dir = Path(__file__).resolve().parent.parent / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:10]
            debug_path = out_dir / f"debug-parse-{digest}.json"
            payload = {
                "products_count": len(products),
                "skipped_count": len(skipped),
                "skipped": skipped,
                "image_count": len(extracted_images),
                "image_offset": image_offset,
                "raw_text_first_2000": text[:2000],
            }
            with open(debug_path, "w", encoding="utf-8") as f:
                _json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    return data, skipped


def parse_pdf_with_validation(
    pdf_path: str | Path,
    config: Optional[TemplateConfig] = None,
    use_vision_views: bool = False,
) -> tuple[SQStructuredData, list]:
    """Parse PDF and run validation; return (data, validation_errors).

    validation_errors include both schema-level violations (amount mismatch, etc.) and
    per-row drop reasons surfaced by the parser, so the UI can show "N rows skipped".
    """
    from app.schema import ValidationError

    data, skipped = parse_pdf_to_structured_data(pdf_path, config, use_vision_views=use_vision_views)
    errors = validate_sq_data(data)
    for s in skipped:
        sr = s.get("sr_no") or "?"
        name = s.get("name") or ""
        reason = s.get("reason") or "unknown"
        errors.append(
            ValidationError(
                field=f"products[skipped]:row{sr}",
                message=f"Row {sr} ({name[:30]}) dropped: {reason}",
                value=name[:60],
            )
        )
    return data, errors


def merge_sq_data(existing: SQStructuredData, new_data: SQStructuredData) -> SQStructuredData:
    """
    Merge new_data into existing: append products (renumber sr_no 1, 2, ...),
    sum summary fields, concatenate extracted_images. Keep existing.project.
    """
    combined_products: list[Product] = []
    for i, p in enumerate(existing.products):
        combined_products.append(
            Product(
                sr_no=i + 1,
                name=p.name,
                description=p.description,
                dimensions=p.dimensions,
                area=p.area,
                material=p.material,
                finish=p.finish,
                qty=p.qty,
                unit_price=p.unit_price,
                amount=p.amount,
                remarks=p.remarks,
                images=p.images,
                image_views=p.image_views,
            )
        )
    offset = len(combined_products)
    for i, p in enumerate(new_data.products):
        combined_products.append(
            Product(
                sr_no=offset + i + 1,
                name=p.name,
                description=p.description,
                dimensions=p.dimensions,
                area=p.area,
                material=p.material,
                finish=p.finish,
                qty=p.qty,
                unit_price=p.unit_price,
                amount=p.amount,
                remarks=p.remarks,
                images=p.images,
                image_views=p.image_views,
            )
        )
    summary = Summary(
        subtotal=existing.summary.subtotal + new_data.summary.subtotal,
        tax=existing.summary.tax + new_data.summary.tax,
        grand_total=existing.summary.grand_total + new_data.summary.grand_total,
    )
    extracted_images = list(existing.extracted_images) + list(new_data.extracted_images)
    return SQStructuredData(
        project=existing.project,
        products=combined_products,
        summary=summary,
        extracted_images=extracted_images,
    )
