"""Cost of ownership and break-even arithmetic for the HPZ440 LLM stack.

Pure functions over numbers. No I/O, no network, no hardware.

"Tokens per dollar" is unbounded for hardware you already own, so the headline
figure here is a break-even monthly token volume: the volume at which paying a
hosted provider costs the same as amortized capex plus electricity.
"""

MIX_INPUT_TOKENS = 1000
MIX_OUTPUT_TOKENS = 300

HOURS_PER_MONTH = 720
AMORTIZATION_MONTHS = 36

CAPEX_USD = 300.0  # RTX 3060 12GB, purchased 2026-09-29.
PRICE_PER_KWH = 0.17  # Conrad's rate, 2026-10.


def mix_fractions(
    input_tokens: int = MIX_INPUT_TOKENS,
    output_tokens: int = MIX_OUTPUT_TOKENS,
) -> tuple[float, float]:
    """Fraction of a mixed-token unit that is input, and that is output."""
    total = input_tokens + output_tokens
    if total <= 0:
        raise ValueError("token mix must be positive")
    return input_tokens / total, output_tokens / total


def requests_per_mixed_mtok(
    input_tokens: int = MIX_INPUT_TOKENS,
    output_tokens: int = MIX_OUTPUT_TOKENS,
) -> float:
    """How many requests one million mixed tokens buys."""
    total = input_tokens + output_tokens
    if total <= 0:
        raise ValueError("token mix must be positive")
    return 1_000_000 / total


def monthly_power_cost(
    watts_idle: float,
    watts_load: float,
    hours_active: float,
    price_per_kwh: float = PRICE_PER_KWH,
    hours_per_month: int = HOURS_PER_MONTH,
) -> float:
    """Electricity for one month.

    Idle watts are charged for every powered hour that is not active, because
    the HPZ440 stays on. At low volume this term dominates.
    """
    if not 0.0 <= hours_active <= hours_per_month:
        raise ValueError(
            f"hours_active must be between 0 and {hours_per_month}, got {hours_active}"
        )
    idle_hours = hours_per_month - hours_active
    kwh = (watts_idle * idle_hours + watts_load * hours_active) / 1000.0
    return kwh * price_per_kwh


def monthly_cost_of_ownership(
    capex_usd: float = CAPEX_USD,
    *,
    watts_idle: float,
    watts_load: float,
    hours_active: float,
    price_per_kwh: float = PRICE_PER_KWH,
    amortization_months: int = AMORTIZATION_MONTHS,
) -> float:
    """Amortized hardware plus electricity, per month."""
    if amortization_months <= 0:
        raise ValueError("amortization_months must be positive")
    capex_monthly = capex_usd / amortization_months
    power = monthly_power_cost(watts_idle, watts_load, hours_active, price_per_kwh)
    return capex_monthly + power


def hosted_cost_per_mixed_mtok(
    price_in_per_mtok: float,
    price_out_per_mtok: float,
    input_tokens: int = MIX_INPUT_TOKENS,
    output_tokens: int = MIX_OUTPUT_TOKENS,
) -> float:
    """Dollars a hosted provider charges for one million mixed tokens.

    Providers price input and output separately, and on this hardware prefill is
    an order of magnitude faster than decode, so a single "tokens" unit is
    meaningless without a fixed mix.
    """
    frac_in, frac_out = mix_fractions(input_tokens, output_tokens)
    return price_in_per_mtok * frac_in + price_out_per_mtok * frac_out


def break_even_mixed_mtok(
    monthly_cost_usd: float,
    hosted_per_mixed_mtok: float,
) -> float:
    """Mixed Mtok per month at which owning costs the same as renting."""
    if hosted_per_mixed_mtok <= 0:
        raise ValueError("hosted price must be positive")
    return monthly_cost_usd / hosted_per_mixed_mtok
