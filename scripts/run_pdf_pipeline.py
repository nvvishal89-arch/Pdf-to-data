"""Run PDF pipeline on Munish ji Sq.pdf and export to JSON, CSV, Excel."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pdf_pipeline import parse_pdf_with_validation
from app.export import export_json, export_csv, export_excel

def main():
    base = Path(__file__).resolve().parent.parent
    pdf_path = base / "Munish ji Sq.pdf"
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        sys.exit(1)
    out_dir = base / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    data, errors = parse_pdf_with_validation(pdf_path)
    print(f"Parsed {len(data.products)} products; {len(errors)} validation error(s)")
    for e in errors:
        print(f"  - {e.field}: {e.message}")
    export_json(data, out_dir / "sq_output.json")
    export_csv(data, out_dir / "sq_output.csv")
    export_excel(data, out_dir / "sq_output.xlsx")
    print(f"Exported to {out_dir}")

if __name__ == "__main__":
    main()
