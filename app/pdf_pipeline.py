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
from app.validation import validate_sq_data, _safe_float


def extract_images_from_pdf(pdf_path: str | Path, max_images: int = 50) -> list[str]:
    """Extract embedded images from PDF as base64 PNG strings; fallback to page renders if none found."""
    out: list[str] = []
    try:
        import fitz
        doc = fitz.open(pdf_path)
        # 1) Embedded XObject images via get_images + extract_image
        for page in doc:
            for img in page.get_images(full=True):
                if len(out) >= max_images:
                    break
                xref = img[0]
                try:
                    base_img = doc.extract_image(xref)
                    if base_img:
                        b = base_img.get("image")
                        if b:
                            out.append(base64.b64encode(b).decode("ascii"))
                            continue
                except Exception:
                    pass
                # Fallback: build Pixmap from xref and export as PNG
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n > 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    img_bytes = pix.tobytes(output="png")
                    pix = None
                    if img_bytes:
                        out.append(base64.b64encode(img_bytes).decode("ascii"))
                except Exception:
                    pass
            if len(out) >= max_images:
                break
        # 2) If no embedded images, render each page to PNG so user still gets visuals
        if len(out) == 0:
            for i, page in enumerate(doc):
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
    line_clean = line.replace(",", "").replace("\u20b9", "").strip()  # ₹
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


def _parse_table_multiline(lines: list[str], header_idx: int) -> list[dict[str, str]]:
    """
    Parse when each product is a multi-line block: first line "1 Name", middle lines specs/description,
    last line "Price Qty Amount" (e.g. ₹ 7,302 1 ₹7,302).
    """
    rows: list[dict[str, str]] = []
    i = header_idx + 1
    while i < len(lines):
        line = lines[i]
        if re.match(r"^(sub\s*total|total|grand\s*total|tax)", line, re.I):
            break
        # Product start: line like "1 Stand" or "2 Storage"
        m = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if m:
            sr_no = m.group(1)
            name = _normalize(m.group(2))
            dimensions = ""
            description_parts: list[str] = []
            unit_price, qty, amount = "", "", ""
            i += 1
            first_block = len(rows) == 0
            while i < len(lines):
                ln = lines[i]
                if re.match(r"^(sub\s*total|total|grand\s*total|tax)", ln, re.I):
                    break
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
                elif is_price_line or alt_price:
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
    return rows


def _parse_table_from_text(text: str) -> list[dict[str, str]]:
    """
    Heuristic table extraction. If header suggests multi-line blocks (Specs, Price Qty Amount),
    use block parsing; else one line per row.
    """
    lines = [l for l in text.splitlines() if l.strip()]
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
        return []

    header_lower = header_line.lower()
    use_multiline = "specs" in header_lower and ("price" in header_lower or "qty" in header_lower) and "amount" in header_lower
    if use_multiline:
        rows = _parse_table_multiline(lines, header_idx)
        return rows

    def _parts_for_line(line: str) -> list[str]:
        parts = re.split(r"\s{2,}|\t", line)
        if len(parts) >= 3:
            return parts
        parts = re.split(r"\s+", line)
        return parts[:9] if len(parts) > 9 else parts

    rows: list[dict[str, str]] = []
    skipped_reason: list[str] = []
    for i in range(header_idx + 1, len(lines)):
        line = lines[i]
        if re.match(r"^(sub\s*total|total|grand\s*total|tax)", line, re.I):
            skipped_reason.append(f"row{i}:total_line")
            break
        parts = _parts_for_line(line)
        if len(parts) < 2:
            skipped_reason.append(f"row{i}:len(parts)={len(parts)}")
            continue
        row = {
            "sr_no": _normalize(parts[0]) if len(parts) > 0 else "",
            "name": _normalize(parts[1]) if len(parts) > 1 else "",
            "dimensions": _normalize(parts[2]) if len(parts) > 2 else "",
            "area": _normalize(parts[3]) if len(parts) > 3 else "",
            "material": _normalize(parts[4]) if len(parts) > 4 else "",
            "finish": _normalize(parts[5]) if len(parts) > 5 else "",
            "qty": _normalize(parts[6]) if len(parts) > 6 else "",
            "unit_price": _normalize(parts[7]) if len(parts) > 7 else "",
            "amount": _normalize(parts[8]) if len(parts) > 8 else "",
        }
        if row["sr_no"] and not re.match(r"^\d+\.?\d*$", row["sr_no"]):
            skipped_reason.append(f"row{i}:sr_no_non_numeric={repr(row['sr_no'])}")
            continue
        rows.append(row)
    return rows


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


def parse_pdf_to_structured_data(
    pdf_path: str | Path,
    config: Optional[TemplateConfig] = None,
) -> SQStructuredData:
    """
    Parse SQ PDF into SQStructuredData.
    Uses config for column mapping if provided; otherwise uses heuristics from text.
    """
    text = extract_text_from_pdf(pdf_path)
    header = _parse_header_from_text(text)
    table_rows = _parse_table_from_text(text)
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
    # When PDF has more images than products (e.g. logo first), skip leading images so row N gets the image that appears in that row.
    num_products = len(table_rows)
    num_images = len(extracted_images)
    image_offset = max(0, num_images - num_products)
    for i, row in enumerate(table_rows):
        img_idx = image_offset + i
        product_images = [extracted_images[img_idx]] if img_idx < len(extracted_images) else []
        products.append(
            Product(
                sr_no=int(_safe_float(row.get("sr_no", 0))) or (i + 1),
                name=row.get("name", ""),
                description=row.get("description", row.get("name", "")),
                dimensions=row.get("dimensions", ""),
                area=row.get("area", ""),
                material=row.get("material", ""),
                finish=row.get("finish", ""),
                qty=int(_safe_float(row.get("qty", 1))),
                unit_price=_safe_float(row.get("unit_price", 0)),
                amount=_safe_float(row.get("amount", 0)),
                images=product_images,
            )
        )

    summary = Summary(
        subtotal=totals.get("subtotal", 0),
        tax=totals.get("tax", 0),
        grand_total=totals.get("grand_total", 0),
    )

    return SQStructuredData(
        project=project,
        products=products,
        summary=summary,
        extracted_images=extracted_images,
    )


def parse_pdf_with_validation(
    pdf_path: str | Path,
    config: Optional[TemplateConfig] = None,
) -> tuple[SQStructuredData, list]:
    """Parse PDF and run validation; return (data, validation_errors)."""
    from app.schema import ValidationError

    data = parse_pdf_to_structured_data(pdf_path, config)
    errors = validate_sq_data(data)
    return data, errors
