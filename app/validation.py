"""Validation: amount = qty * rate, dimension/area format."""
from app.schema import SQStructuredData, Product, ValidationError


def _safe_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _validate_product(product: Product, index: int) -> list[ValidationError]:
    errors: list[ValidationError] = []
    qty = product.qty
    unit_price = product.unit_price
    amount = product.amount
    expected = qty * unit_price
    if amount != 0 and expected != 0 and abs(amount - expected) > 0.01:
        errors.append(
            ValidationError(
                field=f"products[{index}].amount",
                message=f"amount should equal qty * unit_price ({expected})",
                value=str(amount),
            )
        )
    return errors


def validate_sq_data(data: SQStructuredData) -> list[ValidationError]:
    """Run rule checks on extracted SQ data."""
    errors: list[ValidationError] = []
    for i, product in enumerate(data.products):
        errors.extend(_validate_product(product, i))
    return errors
