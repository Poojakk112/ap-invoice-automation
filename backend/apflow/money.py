"""Money helpers. All amounts use Decimal (never float) and round half-up to cents."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def D(value) -> Decimal:
    """Convert str/int/Decimal to Decimal without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        value = repr(value)
    return Decimal(str(value).replace(",", "").replace("$", "").strip())


def q2(value) -> Decimal:
    """Round to cents, half-up (the convention used on invoices)."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(value) -> str:
    """Plain 2-decimal string, e.g. '1234.50' (used in CSV files)."""
    return f"{q2(value):.2f}"


def fmt_thousands(value) -> str:
    """Human format with thousands separators, e.g. '1,234.50' (used on documents)."""
    return f"{q2(value):,.2f}"


def line_tax(amount, rate) -> Decimal:
    """Tax is computed and rounded per line, then summed (documented policy)."""
    return q2(D(amount) * D(rate))
