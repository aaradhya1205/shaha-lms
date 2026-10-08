"""Rupee <-> paise conversion and Indian-style formatting (₹1,25,200)."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def to_paise(value: str | int | float) -> int:
    """'1,25,200.50' / '₹125200' / 125200 -> 12520050. Raises ValueError if not a number."""
    text = str(value).replace(",", "").replace("₹", "").strip()
    if not text:
        raise ValueError("empty amount")
    try:
        rupees = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    if not rupees.is_finite():
        raise ValueError(f"not a number: {value!r}")
    return int((rupees * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def inr(paise: int | None, decimals: bool = False) -> str:
    """12520050 -> '₹1,25,200' (Indian digit grouping)."""
    if paise is None:
        return "—"
    negative = paise < 0
    rupees, rem = divmod(abs(int(paise)), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    text = f"₹{digits}" + (f".{rem:02d}" if decimals and rem else "")
    return "-" + text if negative else text


def rupees_input(paise: int | None) -> str:
    """Value for an <input type=number> field."""
    if paise is None:
        return ""
    rupees, rem = divmod(int(paise), 100)
    return f"{rupees}.{rem:02d}" if rem else str(rupees)
