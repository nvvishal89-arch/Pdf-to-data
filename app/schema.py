"""Output schema for SQ structured data (from spec)."""
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator


def _num(v: Any, default: float | int) -> float | int:
    """Coerce None, empty string, or invalid to default for round-trip from JSON."""
    if v is None or v == "":
        return default
    if isinstance(v, (int, float)):
        return v
    try:
        return int(v) if isinstance(default, int) else float(v)
    except (TypeError, ValueError):
        return default


def _list_str(v: Any) -> list[str]:
    """Coerce None or non-list to list of strings; filter out nulls."""
    if v is None:
        return []
    if not isinstance(v, list):
        return []
    return [str(x) if x is not None else "" for x in v]


class Project(BaseModel):
    """Header/project block."""
    project_name: str = ""
    client_name: str = ""
    quotation_no: str = ""
    date: str = ""
    prepared_by: str = ""

    @field_validator("project_name", "client_name", "quotation_no", "date", "prepared_by", mode="before")
    @classmethod
    def _str_default(cls, v: Any) -> str:
        return "" if v is None else str(v)


class Product(BaseModel):
    """Single product row."""
    sr_no: int = 0
    name: str = ""
    description: str = ""
    dimensions: str = ""
    area: str = ""
    material: str = ""
    finish: str = ""
    qty: int = 1
    unit_price: float = 0.0
    amount: float = 0.0
    remarks: str = ""
    images: list[str] = Field(default_factory=list)
    image_views: list[str] = Field(default_factory=list, description="View label per image (Front View, Side View, etc.)")

    @field_validator("sr_no", mode="before")
    @classmethod
    def _sr_no_coerce(cls, v: Any) -> int:
        return int(_num(v, 0)) or 0

    @field_validator("qty", mode="before")
    @classmethod
    def _qty_coerce(cls, v: Any) -> int:
        return int(_num(v, 1)) or 1

    @field_validator("unit_price", "amount", mode="before")
    @classmethod
    def _float_coerce(cls, v: Any) -> float:
        return float(_num(v, 0.0))

    @field_validator("name", "description", "dimensions", "area", "material", "finish", "remarks", mode="before")
    @classmethod
    def _str_default(cls, v: Any) -> str:
        return "" if v is None else str(v)

    @field_validator("images", "image_views", mode="before")
    @classmethod
    def _list_coerce(cls, v: Any) -> list[str]:
        return _list_str(v)


class Summary(BaseModel):
    """Totals block."""
    subtotal: float = 0.0
    tax: float = 0.0
    grand_total: float = 0.0

    @field_validator("subtotal", "tax", "grand_total", mode="before")
    @classmethod
    def _float_coerce(cls, v: Any) -> float:
        return float(_num(v, 0.0))


class SQStructuredData(BaseModel):
    """Full SQ structured output."""
    project: Project = Field(default_factory=Project)
    products: list[Product] = Field(default_factory=list)
    summary: Summary = Field(default_factory=Summary)
    extracted_images: list[str] = Field(default_factory=list, description="Base64-encoded images extracted from PDF")

    @field_validator("project", mode="before")
    @classmethod
    def _project_coerce(cls, v: Any) -> Any:
        return v if v is not None and isinstance(v, dict) else {}

    @field_validator("summary", mode="before")
    @classmethod
    def _summary_coerce(cls, v: Any) -> Any:
        return v if v is not None and isinstance(v, dict) else {}

    @field_validator("products", mode="before")
    @classmethod
    def _products_list(cls, v: Any) -> list:
        if v is None:
            return []
        return list(v) if isinstance(v, (list, tuple)) else []

    @field_validator("extracted_images", mode="before")
    @classmethod
    def _extracted_images_list(cls, v: Any) -> list[str]:
        return _list_str(v)


class ValidationError(BaseModel):
    """Single validation issue."""
    field: str
    message: str
    value: Optional[str] = None


class ParseResult(BaseModel):
    """API response: data + validation errors."""
    data: SQStructuredData
    validation_errors: list[ValidationError] = Field(default_factory=list)
