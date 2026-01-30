"""Template config schema (anchors + column mapping from Excel)."""
from typing import Any
from pydantic import BaseModel, Field


class HeaderAnchor(BaseModel):
    """Header label and its value cell (row, col) or key."""
    label: str
    key: str  # project_name, client_name, quotation_no, date, prepared_by
    row: int = 0
    col: int = 0
    value_col: int = 0  # column where value is (often label_col + 1)


class TableColumn(BaseModel):
    """Product table column mapping."""
    header: str
    key: str  # sr_no, name, description, dimensions, area, material, finish, qty, unit_price, amount, images
    col_index: int = 0


class TemplateConfig(BaseModel):
    """Config derived from Sample format SQ.xlsx."""
    header_anchors: list[HeaderAnchor] = Field(default_factory=list)
    table_header_row: int = 0
    table_columns: list[TableColumn] = Field(default_factory=list)
    data_start_row: int = 1
    raw_cells: dict[str, Any] = Field(default_factory=dict)  # label -> (row, col) for flexibility
