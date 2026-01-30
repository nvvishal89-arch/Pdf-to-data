"""Run template extractor on Sample format SQ.xlsx and save config to config/sq_template_config.json."""
import sys
from pathlib import Path

# Allow importing app from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.template_extractor import extract_template_to_json

def main():
    base = Path(__file__).resolve().parent.parent
    excel_path = base / "Sample format SQ.xlsx"
    out_path = base / "config" / "sq_template_config.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    extract_template_to_json(excel_path, out_path)
    print(f"Template config written to {out_path}")

if __name__ == "__main__":
    main()
