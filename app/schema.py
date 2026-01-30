"""Output schema for SQ structured data (from spec)."""
from typing import Optional
from pydantic import BaseModel, Field


class Project(BaseModel):
    """Header/project block."""
    project_name: str = ""
    client_name: str = ""
    quotation_no: str = ""
    date: str = ""
    prepared_by: str = ""


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
    images: list[str] = Field(default_factory=list)


class Summary(BaseModel):
    """Totals block."""
    subtotal: float = 0.0
    tax: float = 0.0
    grand_total: float = 0.0


class SQStructuredData(BaseModel):
    """Full SQ structured output."""
    project: Project = Field(default_factory=Project)
    products: list[Product] = Field(default_factory=list)
    summary: Summary = Field(default_factory=Summary)
    extracted_images: list[str] = Field(default_factory=list, description="Base64-encoded images extracted from PDF")


class ValidationError(BaseModel):
    """Single validation issue."""
    field: str
    message: str
    value: Optional[str] = None


class ParseResult(BaseModel):
    """API response: data + validation errors."""
    data: SQStructuredData
    validation_errors: list[ValidationError] = Field(default_factory=list)
