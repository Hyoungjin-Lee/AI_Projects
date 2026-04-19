"""
analyze_swing.py — 스윙(며칠~몇 주) 관점 종목 분석

사용법:
  python analyze_swing.py <종목코드>          # 기본: 일봉 120일
  python analyze_swing.py <종목코드> --days 60

출력: stdout에 표준 JSON (stock-analysis SKILL.md 명세 형식)
데이터: data/raw/<코드>_daily_*.json 캐시 자동 참조
       없으면 kis-api 스킬로 먼저 받아오도록 안내.
"""

import argparse
import json
import sys
import os
from datetime import date

import pandas as pd
import numpy as np

# 같은 scripts/ 폴더를 path에 추가
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from loader import load_latest
from indicators import sma, ema, rsi, macd, bollinger, atr, support_resistance


def analyze(code: str, days: int = 120) -> dict:
    """스윙 분석 메인 함수. 표준 JSON dict 반환."""

    # ── 1. 데이터 로드 ────────────────────────────────────────────────────────
    try:
        df = load_latest(code, "daily")
    except FileNotFoundError as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)

    # 날짜 오름차순 정렬 후 최근 days일 선택
    if "date" in df.columns:
        df = df.sort_values("date")
    df = df.tail(days).reset_index(drop=True)

    if len(df) < 30:
        _exit_error(code, f"데이터가 너무 적습니다 ({len(df)}행). 최소 30일 필요.")

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(dtype=float)

    data_from = str(df["date"].iloc[0].date()) if "date" in df.columns else "N/A"
    data_to   = str(df["date"].iloc[-1].date()) if "date" in df.columns else "N/A"

    # ── 2. 지표 계산 ──────────────────────────────────────────────────────────
    sma20 = sma(close, 20)
    sma60 = sma(close, 60)
    rsi14 = rsi(close, 14)
    macd_d = macd(close)
    boll  = bollinger(close, 20, 2)
    atr14 = atr(high, low, close, 14)
    sr    = support_resistance(close, lookback=min(60, len(close) - 1), n_levels=3)

    # 최신값
    c    = float(close.iloc[-1])
    s20  = float(sma20.iloc[-1]) if not pd.isna(sma20.iloc[-1]) else None
    s60  = float(sma60.iloc[-1]) if not pd.isna(sma60.iloc[-1]) else None
    r14  = float(rsi14.iloc[-1]) if not pd.isna(rsi14.iloc[-1]) else None
    macd_v = float(macd_d["macd"].iloc[-1]) if not pd.isna(macd_d["macd"].iloc[-1]) else None
    hist_v = float(macd_d["hist"].iloc[-1]) if not pd.isna(macd_d["hist"].iloc[-1]) else None
    pct_b  = float(boll["pct_b"].iloc[-1]) if not pd.isna(boll["pct_b"].iloc[-1]) else None
    atr_v  = float(atr14.iloc[-1]) if not pd.isna(atr14.iloc[-1]) else None

    # ── 3. 시그널 해석 ────────────────────────────────────────────────────────
    signals = []
    bullish_cnt = 0
    bearish_cnt = 0
    total_weight = 0

    # (a) 추세: SMA20 vs SMA60
    if s20 is not None and s60 is not None:
        trend_bull = s20 > s60
        gap_pct = (s20 - s60) / s60 * 100
        if trend_bull:
            bullish_cnt += 2; total_weight += 2
            interp = f"골든크로스 유지 (SMA20 SMA60 대비 +{gap_pct:.1f}%)"
        else:
            bearish_cnt += 2; total_weight += 2
            interp = f"데드크로스 상태 (SMA20 SMA60 대비 {gap_pct:.1f}%)"
        signals.append({"name": "SMA20/60 추세", "value": f"{s20:,.0f}/{s60:,.0f}", "interpretation": interp})

    # (b) RSI
    if r14 is not None:
        if r14 >= 70:
            bearish_cnt += 1; total_weight += 1
            rsi_interp = f"과매수 구간 ({r14:.1f}), 단기 조정 경계"
        elif r14 <= 30:
            bullish_cnt += 1; total_weight += 1
            rsi_interp = f"과매도 구간 ({r14:.1f}), 반등 가능성"
        elif 50 <= r14 < 70:
            bullish_cnt += 1; total_weight += 1
            rsi_interp = f"중립~상승 ({r14:.1f})"
        else:
            bearish_cnt += 1; total_weight += 1
            rsi_interp = f"중립~하락 ({r14:.1f})"
        signals.append({"name": "RSI(14)", "value": round(r14, 1), "interpretation": rsi_interp})

    # (c) MACD 히스토그램
    if hist_v is not None:
        # 히스토그램 방향 변화 확인
        prev_hist = float(macd_d["hist"].iloc[-2]) if len(macd_d["hist"]) >= 2 else None
        if hist_v > 0:
            bullish_cnt += 1; total_weight += 1
            cross_hint = " (골든크로스 후 확장)" if (prev_hist is not None and prev_hist < 0) else ""
            macd_interp = f"양수{cross_hint} → 강세 흐름"
        else:
            bearish_cnt += 1; total_weight += 1
            cross_hint = " (데드크로스 전환)" if (prev_hist is not None and prev_hist > 0) else ""
            macd_interp = f"음수{cross_hint} → 약세 흐름"
        signals.append({"name": "MACD Hist", "value": round(hist_v, 2), "interpretation": macd_interp})

    # (d) 볼린저 %b
    if pct_b is not None:
        if pct_b > 0.8:
            bearish_cnt += 1; total_weight += 1
            bb_interp = f"상단 밴드 근접 ({pct_b:.2f}), 단기 과열"
        elif pct_b < 0.2:
            bullish_cnt += 1; total_weight += 1
            bb_interp = f"하단 밴드 근접 ({pct_b:.2f}), 반등 시도 구간"
        else:
            total_weight += 1  # 중립
            bb_interp = f"밴드 중간 ({pct_b:.2f}), 방향성 대기"
        signals.append({"name": "볼린저 %b", "value": round(pct_b, 2), "interpretation": bb_interp})

    # (e) 거래량 (20일 평균 대비)
    vol_signal = None
    if not volume.empty and len(volume) >= 20:
        recent_vol = float(volume.iloc[-1])
        avg_vol_20 = float(volume.iloc[-20:].mean())
        vol_ratio = recent_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
        if vol_ratio >= 1.5:
            bullish_cnt += 1; total_weight += 1
            vol_interp = f"거래량 급증 ({vol_ratio:.1f}x 20일 평균)"
        elif vol_ratio <= 0.5:
            total_weight += 1
            vol_interp = f"거래량 감소 ({vol_ratio:.1f}x 20일 평균), 신호 신뢰도 낮음"
        else:
            total_weight += 1
            vol_interp = f"거래량 보통 ({vol_ratio:.1f}x 20일 평균)"
        signals.append({"name": "거래량", "value": f"{vol_ratio:.2f}x", "interpretation": vol_interp})

    # ── 4. 판정 ───────────────────────────────────────────────────────────────
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

    # ── 5. 손절/목표가 추정 (ATR 기반) ──────────────────────────────────────
    risks = []
    stop_loss = None
    target_price = None
    if atr_v is not None:
        stop_loss   = round(c - 2 * atr_v, 0)
        target_price = round(c + 4 * atr_v, 0)   # RR 2:1
        risks.append(f"ATR 기반 손절: {stop_loss:,.0f}원 (현재가 대비 -{2*atr_v/c*100:.1f}%)")

    if confidence < 0.4:
        risks.append("확신도 미달 (0.4 미만) — 시그널 충돌, 참고만 하세요")

    # 기타 리스크 경고
    if r14 is not None and r14 > 70 and (s20 and s20 > s60):
        risks.append("상승 추세 중 RSI 과매수 — 단기 숨고르기 가능")

    # ── 6. narrative ─────────────────────────────────────────────────────────
    trend_desc = "상승 추세" if (s20 and s60 and s20 > s60) else "하락 추세"
    rsi_desc   = f"RSI {r14:.0f}" if r14 else ""
    macd_desc  = "MACD 강세" if (hist_v and hist_v > 0) else "MACD 약세"
    narrative = (
        f"{code}는 {trend_desc}({macd_desc}), {rsi_desc}로 "
        f"{'매수' if verdict == 'BUY' else '매도' if verdict == 'SELL' else '관망'}을 권고. "
        f"손절 {stop_loss:,.0f}원 · 목표 {target_price:,.0f}원 (ATR 2배/4배)."
        if stop_loss else
        f"{code} 스윙 분석: {trend_desc}, {macd_desc}. verdict={verdict}."
    )

    return {
        "code": code,
        "perspective": "swing",
        "verdict": verdict,
        "confidence": confidence,
        "key_signals": signals,
        "support_levels": sr["support"],
        "resistance_levels": sr["resistance"],
        "stop_loss": stop_loss,
        "target_price": target_price,
        "narrative": narrative,
        "risks": risks,
        "data_window": {
            "from": data_from,
            "to":   data_to,
            "days": len(df),
        },
    }


def _exit_error(code, msg):
    result = {
        "code": code, "perspective": "swing",
        "verdict": "WATCH", "confidence": 0.0,
        "key_signals": [], "support_levels": [], "resistance_levels": [],
        "narrative": msg, "risks": [msg],
        "data_window": {"from": None, "to": None, "days": 0},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="스윙 분석")
    parser.add_argument("code", help="종목코드 (예: 005930)")
    parser.add_argument("--days", type=int, default=120, help="일봉 기간 (기본 120)")
    args = parser.parse_args()

    result = analyze(args.code, args.days)
    print(json.dumps(result, ensure_ascii=False, indent=2))
