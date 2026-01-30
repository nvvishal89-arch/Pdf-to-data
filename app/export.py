"""Export SQ structured data to JSON, CSV, and Excel."""
import csv
import json
from pathlib import Path
from io import StringIO

from app.schema import SQStructuredData


def export_json(data: SQStructuredData, path: str | Path | None = None) -> str:
    """Export to JSON; optionally write to file. Returns JSON string."""
    out = data.model_dump_json(indent=2)
    if path:
        Path(path).write_text(out, encoding="utf-8")
    return out


def export_csv(data: SQStructuredData, path: str | Path | None = None) -> str:
    """Export products table to CSV; optionally write to file. Returns CSV string."""
    buffer = StringIO()
    w = csv.writer(buffer)
    w.writerow(
        [
            "sr_no",
            "name",
            "description",
            "dimensions",
            "area",
            "material",
            "finish",
            "qty",
            "unit_price",
            "amount",
        ]
    )
    for p in data.products:
        w.writerow(
            [
                p.sr_no,
                p.name,
                p.description,
                p.dimensions,
                p.area,
                p.material,
                p.finish,
                p.qty,
                p.unit_price,
                p.amount,
            ]
        )
    out = buffer.getvalue()
    if path:
        Path(path).write_text(out, encoding="utf-8")
    return out


def export_excel(data: SQStructuredData, path: str | Path) -> None:
    """Export to Excel matching SQ format (header block + product table + summary)."""
    import xlsxwriter

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(path))
    ws = workbook.add_worksheet("SQ")

    header = workbook.add_format({"bold": True})
    row = 0
    proj = data.project
    ws.write(row, 0, "Project Name", header)
    ws.write(row, 1, proj.project_name)
    row += 1
    ws.write(row, 0, "Client Name", header)
    ws.write(row, 1, proj.client_name)
    row += 1
    ws.write(row, 0, "Quotation No", header)
    ws.write(row, 1, proj.quotation_no)
    row += 1
    ws.write(row, 0, "Date", header)
    ws.write(row, 1, proj.date)
    row += 1
    ws.write(row, 0, "Prepared By", header)
    ws.write(row, 1, proj.prepared_by)
    row += 2

    # Table header
    cols = [
        "S.No",
        "Product Description",
        "Size / Dimensions",
        "Area",
        "Material",
        "Finish",
        "Qty",
        "Rate",
        "Amount",
    ]
    for c, col in enumerate(cols):
        ws.write(row, c, col, header)
    row += 1
    for p in data.products:
        ws.write(row, 0, p.sr_no)
        ws.write(row, 1, p.name or p.description)
        ws.write(row, 2, p.dimensions)
        ws.write(row, 3, p.area)
        ws.write(row, 4, p.material)
        ws.write(row, 5, p.finish)
        ws.write(row, 6, p.qty)
        ws.write(row, 7, p.unit_price)
        ws.write(row, 8, p.amount)
        row += 1
    row += 1
    s = data.summary
    ws.write(row, 0, "Subtotal", header)
    ws.write(row, 1, s.subtotal)
    row += 1
    ws.write(row, 0, "Tax", header)
    ws.write(row, 1, s.tax)
    row += 1
    ws.write(row, 0, "Grand Total", header)
    ws.write(row, 1, s.grand_total)

    workbook.close()
