import pytest

from bench import cost


def test_mix_fractions_sum_to_one():
    frac_in, frac_out = cost.mix_fractions()
    assert frac_in == pytest.approx(1000 / 1300)
    assert frac_out == pytest.approx(300 / 1300)
    assert frac_in + frac_out == pytest.approx(1.0)


def test_requests_per_mixed_mtok():
    # 1,000,000 tokens at 1300 tokens per request.
    assert cost.requests_per_mixed_mtok() == pytest.approx(769.2307, abs=1e-4)


def test_monthly_power_cost_worked_example():
    # 12 W idle for 660 h = 7.920 kWh; 170 W under load for 60 h = 10.200 kWh.
    # 18.120 kWh at $0.17 = $3.0804.
    assert cost.monthly_power_cost(12.0, 170.0, 60.0) == pytest.approx(3.0804, abs=1e-4)


def test_monthly_power_cost_idle_only():
    # hours_active = 0: 12 W for the full 720 h = 8.64 kWh at $0.17 = $1.4688.
    assert cost.monthly_power_cost(12.0, 170.0, 0.0) == pytest.approx(1.4688, abs=1e-4)


def test_monthly_power_cost_fully_loaded():
    # hours_active = 720: no idle hours remain. 170 W x 720 h = 122.4 kWh = $20.808.
    assert cost.monthly_power_cost(12.0, 170.0, 720.0) == pytest.approx(20.808, abs=1e-3)


def test_monthly_power_cost_rejects_impossible_hours():
    with pytest.raises(ValueError):
        cost.monthly_power_cost(12.0, 170.0, 721.0)
    with pytest.raises(ValueError):
        cost.monthly_power_cost(12.0, 170.0, -1.0)


def test_monthly_cost_of_ownership_worked_example():
    # $300 / 36 months = $8.3333 capex, plus $3.0804 power.
    result = cost.monthly_cost_of_ownership(
        watts_idle=12.0, watts_load=170.0, hours_active=60.0
    )
    assert result == pytest.approx(11.4137, abs=1e-4)


def test_hosted_cost_symmetric_prices():
    # Equal input and output prices: the mix cannot change the per-Mtok figure.
    assert cost.hosted_cost_per_mixed_mtok(0.20, 0.20) == pytest.approx(0.20)


def test_hosted_cost_asymmetric_prices():
    # 0.10 * (1000/1300) + 0.40 * (300/1300)
    assert cost.hosted_cost_per_mixed_mtok(0.10, 0.40) == pytest.approx(0.1692307, abs=1e-6)


def test_break_even_worked_example():
    assert cost.break_even_mixed_mtok(11.4137, 0.20) == pytest.approx(57.0685, abs=1e-3)


def test_break_even_rejects_free_hosting():
    with pytest.raises(ValueError):
        cost.break_even_mixed_mtok(11.41, 0.0)
