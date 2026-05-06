"""
시장 캘린더 — 한국 주식시장(KRX) 영업일 판정 공통 유틸.

목적:
  자동 실행되는 모든 텔레그램 발송 스크립트(morning_report, intraday_*,
  closing_report, stock_discovery, watchlist_sync, pattern_lifecycle)의
  시작 부분에서 호출하여 휴장일에 메시지 발송을 차단한다.

판정 기준:
  - 토(5)/일(6) → 휴장
  - 한국 공휴일(holidays.KR) → 휴장 (대체공휴일 포함)
  - 위 둘 다 아니면 영업일

사용 예:
    from market_calendar import is_trading_day, exit_if_holiday
    exit_if_holiday("morning_report")  # 휴장이면 즉시 sys.exit(0)

라이브러리:
  holidays >= 0.x — 2026년 KR 공휴일 21건 (대체공휴일 포함) 검증 완료.
  미설치 시 weekday만으로 판정 (안전성 ↓ — 5/5 같은 평일 공휴일 누락).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

_WEEKDAYS = {0, 1, 2, 3, 4}  # 월~금


def _kr_holidays(year: int):
    """holidays.KR 인스턴스 (캐시). 라이브러리 미설치 시 None."""
    try:
        import holidays  # type: ignore
        return holidays.KR(years=[year])
    except ImportError:
        return None


def is_trading_day(d: date | None = None) -> bool:
    """
    한국 주식시장 영업일 여부.
    토/일/공휴일이면 False, 평일이고 공휴일 아니면 True.
    """
    d = d or date.today()
    if d.weekday() not in _WEEKDAYS:
        return False
    kr = _kr_holidays(d.year)
    if kr is not None and d in kr:
        return False
    return True


def holiday_name(d: date | None = None) -> str | None:
    """공휴일이면 이름 반환, 아니면 None. (주말은 None)"""
    d = d or date.today()
    kr = _kr_holidays(d.year)
    if kr is None:
        return None
    return kr.get(d)


def previous_trading_day(d: date | None = None) -> date:
    """이전 영업일 (주말 + 공휴일 제외)."""
    d = d or date.today()
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def exit_if_holiday(script_name: str = "script") -> None:
    """
    오늘이 휴장일이면 stderr에 안내 후 sys.exit(0).
    각 자동 발송 스크립트의 가장 윗부분에서 호출.
    """
    today = date.today()
    if is_trading_day(today):
        return
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][today.weekday()]
    name = holiday_name(today)
    if name:
        reason = f"공휴일 — {name}"
    elif today.weekday() == 5:
        reason = "토요일 (주말)"
    elif today.weekday() == 6:
        reason = "일요일 (주말)"
    else:
        reason = "휴장일"
    print(
        f"[{script_name}] 오늘({today} {weekday_kr})은 {reason} — 텔레그램 발송 생략, 종료.",
        file=sys.stderr,
    )
    sys.exit(0)
