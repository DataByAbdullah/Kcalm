from decimal import Decimal, ROUND_HALF_UP


NUTRITION_SCALE_FACTOR = 1000


def scale_amount(value: float | int | Decimal) -> int:
    amount = Decimal(str(value))
    scaled = (amount * Decimal(NUTRITION_SCALE_FACTOR)).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return int(scaled)


def unscale_amount(value: int) -> float:
    amount = Decimal(value) / Decimal(NUTRITION_SCALE_FACTOR)
    return float(amount)


def scaled_tolerance_bounds(target: float, tolerance: float) -> tuple[int, int]:
    target_amount = Decimal(str(target))
    tolerance_amount = Decimal(str(tolerance))
    lower = target_amount * (Decimal("1") - tolerance_amount)
    upper = target_amount * (Decimal("1") + tolerance_amount)
    return scale_amount(lower), scale_amount(upper)
