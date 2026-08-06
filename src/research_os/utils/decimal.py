"""Shared finite-Decimal parsing and canonical fixed-point serialization."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional


DECIMAL_INPUT_PATTERN = r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$"
DECIMAL_INPUT_RE = re.compile(DECIMAL_INPUT_PATTERN)


def normalize_decimal_string(
    value: object,
    *,
    precision: Optional[int] = None,
    rounding_mode: Optional[str] = None,
) -> str:
    """Parse a finite Decimal and return its canonical non-exponent string.

    ``precision`` is never a tolerance. It applies only when the caller's
    deterministic contract explicitly supplies a rounding mode.
    """
    text = str(value)
    if not DECIMAL_INPUT_RE.fullmatch(text):
        raise ValueError(f"invalid decimal: {value!r}")
    try:
        number = Decimal(text)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid decimal: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"non-finite decimal: {value!r}")
    if rounding_mode is not None:
        modes = {"ROUND_HALF_UP": ROUND_HALF_UP}
        if rounding_mode not in modes or precision is None:
            raise ValueError(f"unsupported decimal quantization: {rounding_mode!r}")
        number = number.quantize(Decimal(1).scaleb(-precision), rounding=modes[rounding_mode])
    if number == 0:
        return "0"
    canonical = format(number, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return canonical
