from datetime import date

from pattern_lifecycle import _judge_outcome, _next_trading_day, _previous_trading_day


def test_judge_outcome_cases():
    assert _judge_outcome(3.01) == "true_positive"
    assert _judge_outcome(-1.01) == "false_positive"
    assert _judge_outcome(1.5) == "neutral"
    assert _judge_outcome(None) == "pending"


def test_previous_trading_day_skips_saturday_and_sunday():
    assert _previous_trading_day(date(2026, 5, 4)) == date(2026, 5, 1)
    assert _previous_trading_day(date(2026, 5, 5)) == date(2026, 5, 4)


def test_next_trading_day_skips_saturday_and_sunday():
    assert _next_trading_day(date(2026, 5, 1)) == date(2026, 5, 4)
    assert _next_trading_day(date(2026, 5, 4), n=3) == date(2026, 5, 7)
