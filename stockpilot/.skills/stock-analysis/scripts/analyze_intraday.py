"""
analyze_intraday.py — 단타(데이트레이딩) 관점 종목 분석

사용법:
  python analyze_intraday.py <종목코드>

데이터:
  - 분봉: data/raw/<코드>_minute_*.json
  - 호가: data/raw/<코드>_orderbook_*.json
  - 현재가: data/raw/<코드>_quote_*.json
  없으면 kis-api 스킬로 먼저 받도록 안내.

출력: stdout에 표준 JSON
"""

import argparse
import json
import sys
import os

import pandas as pd
import numpy as np

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from loader import load_latest
from indicators import vwap, sma, rsi


def analyze(code: str) -> dict:
    """단타 분석 메인 함수. 표준 JSON dict 반환."""

    # ── 1. 데이터 로드 ────────────────────────────────────────────────────────
    minute_df = _load_safe(code, "minute")
    orderbook_df = _load_safe(code, "orderbook")
    quote_df = _load_safe(code, "quote")

    if minute_df is None:
        _exit_error(code, "분봉 데이터가 없습니다. get_minute_chart.py로 먼저 받아오세요.")

    # 오름차순 정렬
    minute_df = minute_df.sort_index().reset_index(drop=True)

    # ── 2. VWAP ───────────────────────────────────────────────────────────────
    signals = []
    bullish_cnt = 0
    bearish_cnt = 0
    total_weight = 0

    # 컬럼 매핑 유연 처리
    high_col   = _find_col(minute_df, ["high", "stck_hgpr"])
    low_col    = _find_col(minute_df, ["low", "stck_lwpr"])
    close_col  = _find_col(minute_df, ["close", "stck_clpr", "stck_prpr"])
    volume_col = _find_col(minute_df, ["volume", "acml_vol", "cntg_vol"])

    has_ohlcv = all(c is not None for c in [high_col, low_col, close_col, volume_col])

    current_price = None
    if quote_df is not None:
        cp_col = _find_col(quote_df, ["current_price", "stck_prpr", "close"])
        if cp_col:
            current_price = float(quote_df[cp_col].iloc[-1])

    vwap_val = None
    if has_ohlcv:
        h = minute_df[high_col].astype(float)
        l = minute_df[low_col].astype(float)
        c_series = minute_df[close_col].astype(float)
        v = minute_df[volume_col].astype(float)

        vwap_series = vwap(h, l, c_series, v)
        vwap_val = float(vwap_series.iloc[-1]) if not pd.isna(vwap_series.iloc[-1]) else None
        last_close = float(c_series.iloc[-1])
        if current_price is None:
            current_price = last_close

        if vwap_val is not None:
            vwap_gap_pct = (current_price - vwap_val) / vwap_val * 100
            if vwap_gap_pct > 0.5:
                bullish_cnt += 2; total_weight += 2
                vwap_interp = f"VWAP 위 +{vwap_gap_pct:.2f}% → 매수 우위"
            elif vwap_gap_pct < -0.5:
                bearish_cnt += 2; total_weight += 2
                vwap_interp = f"VWAP 아래 {vwap_gap_pct:.2f}% → 매도 우위"
            else:
                total_weight += 2
                vwap_interp = f"VWAP 근접 ({vwap_gap_pct:+.2f}%) → 방향 탐색"
            signals.append({"name": "VWAP", "value": f"{vwap_val:,.0f}", "interpretation": vwap_interp})

    # ── 3. 5분봉 추세 (분봉 5개씩 묶기) ──────────────────────────────────────
    if has_ohlcv and len(minute_df) >= 10:
        c_series = minute_df[close_col].astype(float)
        # 5개씩 묶어 마지막 값 (5분봉 close 대용)
        n5 = len(c_series) // 5 * 5
        bars5 = c_series.iloc[-n5:].values.reshape(-1, 5)[:, -1]
        bars5 = pd.Series(bars5)

        if len(bars5) >= 5:
            sma5_5 = float(bars5.rolling(3).mean().iloc[-1])
            last5  = float(bars5.iloc[-1])
            if last5 > sma5_5:
                bullish_cnt += 1; total_weight += 1
                t5_interp = "단기 상승 추세 (5분봉 3MA 위)"
            else:
                bearish_cnt += 1; total_weight += 1
                t5_interp = "단기 하락 추세 (5분봉 3MA 아래)"
            signals.append({"name": "5분봉 추세", "value": f"{last5:,.0f}", "interpretation": t5_interp})

    # ── 4. 호가 불균형 ────────────────────────────────────────────────────────
    imbalance = None
    if orderbook_df is not None and not orderbook_df.empty:
        bid_cols = [c for c in orderbook_df.columns if "bidp_rsqn" in c or "bid_qty" in c]
        ask_cols = [c for c in orderbook_df.columns if "askp_rsqn" in c or "ask_qty" in c]
        if bid_cols and ask_cols:
            last_row = orderbook_df.iloc[-1]
            bid_sum = sum(float(last_row.get(c, 0) or 0) for c in bid_cols)
            ask_sum = sum(float(last_row.get(c, 0) or 0) for c in ask_cols)
            if ask_sum > 0:
                imbalance = round(bid_sum / ask_sum, 2)
                if imbalance > 1.3:
                    bullish_cnt += 1; total_weight += 1
                    ob_interp = f"매수 잔량 우세 ({imbalance:.2f}x) → 단기 상승 압력"
                elif imbalance < 0.7:
                    bearish_cnt += 1; total_weight += 1
                    ob_interp = f"매도 잔량 우세 ({imbalance:.2f}x) → 단기 하락 압력"
                else:
                    total_weight += 1
                    ob_interp = f"매수/매도 균형 ({imbalance:.2f}x)"
                signals.append({"name": "호가 불균형(Bid/Ask)", "value": imbalance, "interpretation": ob_interp})

    # ── 5. 당일 등락폭 + 거래량 급증 ─────────────────────────────────────────
    if quote_df is not None and not quote_df.empty:
        chg_col = _find_col(quote_df, ["prdy_ctrt", "change_rate"])
        if chg_col:
            chg = float(quote_df[chg_col].iloc[-1])
            if chg >= 3:
                bullish_cnt += 1; total_weight += 1
                chg_interp = f"강한 양봉 +{chg:.2f}%"
            elif chg <= -3:
                bearish_cnt += 1; total_weight += 1
                chg_interp = f"강한 음봉 {chg:.2f}%"
            else:
                total_weight += 1
                chg_interp = f"등락 {chg:+.2f}%"
            signals.append({"name": "당일 등락률", "value": f"{chg:+.2f}%", "interpretation": chg_interp})

    # ── 6. 판정 ───────────────────────────────────────────────────────────────
    if total_weight == 0:
        verdict = "WATCH"
        confidence = 0.0
    else:
        bull_ratio = bullish_cnt / total_weight
        bear_ratio = bearish_cnt / total_weight
        confidence = round(abs(bull_ratio - bear_ratio), 2)

        if bull_ratio >= 0.6:
            verdict = "BUY"
        elif bear_ratio >= 0.6:
            verdict = "SELL"
        elif bull_ratio >= 0.4:
            verdict = "HOLD"
        else:
            verdict = "WATCH"

    risks = []
    if confidence < 0.4:
        risks.append("확신도 미달 (0.4 미만) — 단타 진입 신중히")
    if vwap_val and current_price:
        dist = abs(current_price - vwap_val) / vwap_val * 100
        if dist > 2:
            risks.append(f"현재가가 VWAP과 {dist:.1f}% 이상 이격 — 평균 회귀 위험")

    data_to = str(minute_df.index[-1]) if hasattr(minute_df.index[-1], "strftime") else "오늘"
    narrative = (
        f"단타 관점: 현재가 {current_price:,.0f}원, VWAP {vwap_val:,.0f}원 대비 "
        f"{'위' if current_price > vwap_val else '아래'}. "
        f"호가 불균형 {imbalance}x. 종합 판정 {verdict}."
    ) if vwap_val and current_price else f"{code} 단타 분석: 데이터 부족으로 WATCH."

    return {
        "code": code,
        "perspective": "intraday",
        "verdict": verdict,
        "confidence": confidence,
        "key_signals": signals,
        "support_levels": [],
        "resistance_levels": [],
        "narrative": narrative,
        "risks": risks,
        "data_window": {
            "from": None,
            "to":   data_to,
            "days": 1,
        },
    }


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _load_safe(code, kind):
    """캐시 없으면 None 반환 (오류 X)."""
    try:
        return load_latest(code, kind)
    except FileNotFoundError:
        return None


def _find_col(df, candidates):
    """후보 컬럼명 중 DataFrame에 존재하는 첫 번째 반환."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _exit_error(code, msg):
    result = {
        "code": code, "perspective": "intraday",
        "verdict": "WATCH", "confidence": 0.0,
        "key_signals": [], "support_levels": [], "resistance_levels": [],
        "narrative": msg, "risks": [msg],
        "data_window": {"from": None, "to": None, "days": 0},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="단타(인트라데이) 분석")
    parser.add_argument("code", help="종목코드 (예: 005930)")
    args = parser.parse_args()

    result = analyze(args.code)
    print(json.dumps(result, ensure_ascii=False, indent=2))
