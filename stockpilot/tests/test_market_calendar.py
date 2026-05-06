"""market_calendar.py 단위 테스트.

휴장일(주말 + 한국 공휴일) 판정 로직 + 이전 영업일 계산 검증.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "morning_report"))
from market_calendar import (  # noqa: E402
    holiday_name,
    is_trading_day,
    previous_trading_day,
)


@pytest.mark.parametrize(
    "d, expected, label",
    [
        # 평일 영업일
        (date(2026, 5, 6), True, "수요일 영업일"),
        (date(2026, 5, 7), True, "목요일 영업일"),
        (date(2026, 5, 11), True, "월요일 영업일"),
        # 주말
        (date(2026, 5, 9), False, "토요일"),
        (date(2026, 5, 10), False, "일요일"),
        # 평일 한국 공휴일
        (date(2026, 1, 1), False, "신정 (목)"),
        (date(2026, 5, 5), False, "어린이날 (화)"),
        (date(2026, 6, 3), False, "지방선거일 (수)"),
        (date(2026, 9, 24), False, "추석 전날 (목)"),
        (date(2026, 9, 25), False, "추석 (금)"),
        (date(2026, 10, 9), False, "한글날 (금)"),
        (date(2026, 12, 25), False, "성탄절 (금)"),
        # 대체공휴일
        (date(2026, 3, 2), False, "삼일절 대체 (월)"),
        (date(2026, 5, 25), False, "부처님오신날 대체 (월)"),
        (date(2026, 8, 17), False, "광복절 대체 (월)"),
        (date(2026, 10, 5), False, "개천절 대체 (월)"),
        # 설날 연휴 3일 (월~수)
        (date(2026, 2, 16), False, "설날 전날 (월)"),
        (date(2026, 2, 17), False, "설날 (화)"),
        (date(2026, 2, 18), False, "설날 다음날 (수)"),
    ],
)
def test_is_trading_day(d: date, expected: bool, label: str) -> None:
    """is_trading_day 19개 시나리오 — 평일/주말/공휴일/대체공휴일/연휴 모두 검증."""
    assert is_trading_day(d) is expected, f"{d} {label}: expected {expected}"


def test_holiday_name_returns_korean() -> None:
    """공휴일 이름이 한국어로 반환됨."""
    assert holiday_name(date(2026, 5, 5)) == "어린이날"
    assert holiday_name(date(2026, 12, 25)) == "기독탄신일"
    # 주말은 None (공휴일 아님)
    assert holiday_name(date(2026, 5, 9)) is None
    # 평일 영업일도 None
    assert holiday_name(date(2026, 5, 6)) is None


def test_previous_trading_day_skips_weekend() -> None:
    """월요일의 이전 영업일은 직전 금요일."""
    # 5/11 월 → 5/8 금 (5/9 토, 5/10 일 스킵)
    assert previous_trading_day(date(2026, 5, 11)) == date(2026, 5, 8)


def test_previous_trading_day_skips_holiday() -> None:
    """공휴일도 스킵."""
    # 5/6 수 → 5/4 월 (5/5 어린이날 스킵)
    assert previous_trading_day(date(2026, 5, 6)) == date(2026, 5, 4)


def test_previous_trading_day_skips_holiday_chain() -> None:
    """주말 + 공휴일이 연속으로 이어진 경우도 스킵."""
    # 5/26 화 → 5/22 금 (5/23 토, 5/24 일, 5/25 부처님 대체 스킵)
    assert previous_trading_day(date(2026, 5, 26)) == date(2026, 5, 22)


def test_previous_trading_day_skips_seol_chuseok() -> None:
    """설날 3일 연휴 + 주말 스킵."""
    # 2/19 목 → 2/13 금 (2/14 토, 2/15 일, 2/16~18 설날 스킵)
    assert previous_trading_day(date(2026, 2, 19)) == date(2026, 2, 13)
