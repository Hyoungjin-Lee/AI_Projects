"""
analyze_quant.py — 정량(시스템 트레이딩) 관점 종목 분석

사용법:
  python analyze_quant.py <종목코드>          # 기본: 일봉 200일
  python analyze_quant.py <종목코드> --days 200

수수료/세금/슬리피지: 매도세 0.18%, 수수료 0.015%, 슬리피지 0.05%
시그널: 골든/데드크로스, SMA5/20 크로스, 모멘텀(20일/60일)

출력: stdout에 표준 JSON + 백테스트 요약 테이블(narrative에 포함)
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
from indicators import sma, ema, rsi, macd, atr, drawdown, sharpe


# 비용 상수
COMMISSION = 0.00015   # 매수/매도 공통 수수료 0.015%
TAX        = 0.0018    # 매도세 0.18%
SLIPPAGE   = 0.0005    # 슬리피지 0.05%
TOTAL_SELL_COST = COMMISSION + TAX + SLIPPAGE
TOTAL_BUY_COST  = COMMISSION + SLIPPAGE


def analyze(code: str, days: int = 200) -> dict:
    """정량 분석 메인 함수. 표준 JSON dict 반환."""

    # ── 1. 데이터 로드 ────────────────────────────────────────────────────────
    try:
        df = load_latest(code, "daily")
    except FileNotFoundError as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)

    if "date" in df.columns:
        df = df.sort_values("date")
    df = df.tail(days).reset_index(drop=True)

    if len(df) < 60:
        _exit_error(code, f"데이터 부족 ({len(df)}행). 정량 분석에 최소 60일 필요.")

    close = df["close"].astype(float)
    high  = df["high"].astype(float) if "high" in df.columns else None
    low   = df["low"].astype(float) if "low" in df.columns else None

    data_from = str(df["date"].iloc[0].date()) if "date" in df.columns else "N/A"
    data_to   = str(df["date"].iloc[-1].date()) if "date" in df.columns else "N/A"

    # ── 2. 지표 계산 ──────────────────────────────────────────────────────────
    sma5  = sma(close, 5)
    sma20 = sma(close, 20)
    sma60 = sma(close, 60)
    sma120 = sma(close, min(120, len(close) - 1))

    daily_returns = close.pct_change().dropna()
    vol_ann = float(daily_returns.std(ddof=1) * np.sqrt(252)) if len(daily_returns) > 1 else None

    mom20 = float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if len(close) > 21 else None
    mom60 = float((close.iloc[-1] / close.iloc[-61] - 1) * 100) if len(close) > 61 else None

    # ── 3. 골든/데드크로스 시그널 ────────────────────────────────────────────
    signals = []
    bullish_cnt = 0
    bearish_cnt = 0
    total_weight = 0

    s5_now  = float(sma5.iloc[-1])  if not pd.isna(sma5.iloc[-1])  else None
    s5_prev = float(sma5.iloc[-2])  if len(sma5) >= 2 and not pd.isna(sma5.iloc[-2])  else None
    s20_now = float(sma20.iloc[-1]) if not pd.isna(sma20.iloc[-1]) else None
    s20_prev= float(sma20.iloc[-2]) if len(sma20) >= 2 and not pd.isna(sma20.iloc[-2]) else None
    s60_now = float(sma60.iloc[-1]) if not pd.isna(sma60.iloc[-1]) else None
    s60_prev= float(sma60.iloc[-2]) if len(sma60) >= 2 and not pd.isna(sma60.iloc[-2]) else None

    # SMA20 vs SMA60 골든/데드크로스
    if s20_now and s60_now and s20_prev and s60_prev:
        golden = s20_prev <= s60_prev and s20_now > s60_now
        dead   = s20_prev >= s60_prev and s20_now < s60_now
        if golden:
            bullish_cnt += 3; total_weight += 3
            cross_interp = "골든크로스 발생 — 중기 매수 시그널"
        elif dead:
            bearish_cnt += 3; total_weight += 3
            cross_interp = "데드크로스 발생 — 중기 매도 시그널"
        elif s20_now > s60_now:
            bullish_cnt += 2; total_weight += 3
            cross_interp = f"골든크로스 유지 (SMA20 {s20_now:,.0f} > SMA60 {s60_now:,.0f})"
        else:
            bearish_cnt += 2; total_weight += 3
            cross_interp = f"데드크로스 유지 (SMA20 {s20_now:,.0f} < SMA60 {s60_now:,.0f})"
        signals.append({"name": "SMA20/60 크로스", "value": f"{s20_now:,.0f}/{s60_now:,.0f}", "interpretation": cross_interp})

    # SMA5 vs SMA20 단기 크로스
    if s5_now and s20_now and s5_prev and s20_prev:
        if s5_prev <= s20_prev and s5_now > s20_now:
            bullish_cnt += 1; total_weight += 1
            s5_interp = "SMA5/20 단기 골든크로스"
        elif s5_prev >= s20_prev and s5_now < s20_now:
            bearish_cnt += 1; total_weight += 1
            s5_interp = "SMA5/20 단기 데드크로스"
        elif s5_now > s20_now:
            bullish_cnt += 1; total_weight += 1
            s5_interp = "SMA5 > SMA20 단기 강세"
        else:
            bearish_cnt += 1; total_weight += 1
            s5_interp = "SMA5 < SMA20 단기 약세"
        signals.append({"name": "SMA5/20 크로스", "value": f"{s5_now:,.0f}/{s20_now:,.0f}", "interpretation": s5_interp})

    # 모멘텀
    if mom20 is not None:
        if mom20 > 5:
            bullish_cnt += 1; total_weight += 1
            m20_interp = f"20일 모멘텀 강세 (+{mom20:.1f}%)"
        elif mom20 < -5:
            bearish_cnt += 1; total_weight += 1
            m20_interp = f"20일 모멘텀 약세 ({mom20:.1f}%)"
        else:
            total_weight += 1
            m20_interp = f"20일 모멘텀 중립 ({mom20:+.1f}%)"
        signals.append({"name": "20일 모멘텀", "value": f"{mom20:+.1f}%", "interpretation": m20_interp})

    if mom60 is not None:
        if mom60 > 10:
            bullish_cnt += 1; total_weight += 1
            m60_interp = f"60일 모멘텀 강세 (+{mom60:.1f}%)"
        elif mom60 < -10:
            bearish_cnt += 1; total_weight += 1
            m60_interp = f"60일 모멘텀 약세 ({mom60:.1f}%)"
        else:
            total_weight += 1
            m60_interp = f"60일 모멘텀 중립 ({mom60:+.1f}%)"
        signals.append({"name": "60일 모멘텀", "value": f"{mom60:+.1f}%", "interpretation": m60_interp})

    # 변동성
    if vol_ann is not None:
        if vol_ann > 0.4:
            risks_signal = "고변동성"
            bearish_cnt += 1; total_weight += 1
        elif vol_ann < 0.15:
            risks_signal = "저변동성"
            total_weight += 1
        else:
            risks_signal = "보통 변동성"
            total_weight += 1
        signals.append({
            "name": "연환산 변동성",
            "value": f"{vol_ann*100:.1f}%",
            "interpretation": f"{risks_signal} (연 {vol_ann*100:.1f}%)"
        })

    # ── 4. 백테스트 (SMA20/60 크로스 전략) ──────────────────────────────────
    bt = _backtest_ma_cross(close, sma20, sma60)

    # ── 5. 리스크 메트릭 ─────────────────────────────────────────────────────
    equity = (1 + daily_returns).cumprod()
    dd_info = drawdown(equity)
    mdd = dd_info["mdd"]
    sharpe_r = sharpe(daily_returns, rf=0.03, periods_per_year=252)

    signals.append({"name": "MDD", "value": f"{mdd*100:.1f}%", "interpretation": f"최대 낙폭 {mdd*100:.1f}%"})
    signals.append({"name": "샤프비율", "value": sharpe_r, "interpretation": f"샤프 {sharpe_r} (1 이상 양호)"})

    # ── 6. 판정 ───────────────────────────────────────────────────────────────
    if total_weight == 0:
        verdict = "WATCH"
        confidence = 0.0
    else:
        bull_ratio = bullish_cnt / total_weight
        bear_ratio = bearish_cnt / total_weight
        confidence = round(abs(bull_ratio - bear_ratio), 2)

        if bull_ratio >= 0.55:
            verdict = "BUY"
        elif bear_ratio >= 0.55:
            verdict = "SELL"
        elif bull_ratio >= 0.4:
            verdict = "HOLD"
        else:
            verdict = "WATCH"

    risks = []
    if mdd < -0.3:
        risks.append(f"MDD {mdd*100:.1f}% — 장기 보유 시 큰 손실 경험")
    if vol_ann and vol_ann > 0.4:
        risks.append(f"연 변동성 {vol_ann*100:.1f}% 고변동 — 포지션 크기 축소 권장")
    if confidence < 0.4:
        risks.append("확신도 미달 (0.4 미만) — 시스템 진입 보류")

    bt_summary = (
        f"백테스트(SMA20/60, {len(close)}일): "
        f"총수익 {bt['total_return']*100:.1f}%, "
        f"승률 {bt['win_rate']*100:.0f}%, "
        f"거래횟수 {bt['trade_count']}회, "
        f"샤프 {bt['sharpe']:.2f} "
        f"(수수료+세금+슬리피지 포함)"
    )

    narrative = (
        f"{code} 정량 분석 ({data_from}~{data_to}): "
        f"모멘텀 {mom20:+.1f}%(20일)/{mom60:+.1f}%(60일), "
        f"연 변동성 {vol_ann*100:.1f}%, MDD {mdd*100:.1f}%, 샤프 {sharpe_r}. "
        f"판정 {verdict}. {bt_summary}"
    ) if mom20 is not None and vol_ann is not None else f"{code} 정량 분석 판정: {verdict}."

    return {
        "code": code,
        "perspective": "quant",
        "verdict": verdict,
        "confidence": confidence,
        "key_signals": signals,
        "support_levels": [],
        "resistance_levels": [],
        "narrative": narrative,
        "risks": risks,
        "backtest": bt,
        "data_window": {
            "from": data_from,
            "to":   data_to,
            "days": len(df),
        },
    }


def _backtest_ma_cross(close: pd.Series, fast_ma: pd.Series, slow_ma: pd.Series) -> dict:
    """
    SMA20/60 골든·데드크로스 단순 백테스트.
    골든크로스 → 매수, 데드크로스 → 매도.
    비용: 매수(수수료+슬리피지), 매도(수수료+세금+슬리피지).
    """
    position = 0
    entry_price = 0.0
    trades = []
    equity = [1.0]
    cash = 1.0

    for i in range(1, len(close)):
        f_prev = fast_ma.iloc[i - 1]
        s_prev = slow_ma.iloc[i - 1]
        f_now  = fast_ma.iloc[i]
        s_now  = slow_ma.iloc[i]

        if pd.isna(f_now) or pd.isna(s_now):
            equity.append(equity[-1])
            continue

        price = float(close.iloc[i])

        # 골든크로스: 매수
        if f_prev <= s_prev and f_now > s_now and position == 0:
            entry_price = price * (1 + TOTAL_BUY_COST)
            position = 1

        # 데드크로스: 매도
        elif f_prev >= s_prev and f_now < s_now and position == 1:
            exit_price = price * (1 - TOTAL_SELL_COST)
            ret = exit_price / entry_price - 1
            trades.append(ret)
            cash *= (1 + ret)
            position = 0
            entry_price = 0.0

        # 보유 중 평가
        if position == 1:
            unrealized = price / (entry_price / (1 + TOTAL_BUY_COST)) - 1
            equity.append(cash * (1 + unrealized))
        else:
            equity.append(cash)

    total_return = equity[-1] - 1
    win_trades = [t for t in trades if t > 0]
    win_rate = len(win_trades) / len(trades) if trades else 0.0
    equity_s = pd.Series(equity)
    daily_eq_ret = equity_s.pct_change().dropna()
    bt_sharpe = sharpe(daily_eq_ret) if len(daily_eq_ret) > 1 else float("nan")

    return {
        "total_return": round(total_return, 4),
        "win_rate": round(win_rate, 3),
        "trade_count": len(trades),
        "sharpe": round(bt_sharpe, 2) if not np.isnan(bt_sharpe) else None,
        "cost_included": True,
    }


def _exit_error(code, msg):
    result = {
        "code": code, "perspective": "quant",
        "verdict": "WATCH", "confidence": 0.0,
        "key_signals": [], "support_levels": [], "resistance_levels": [],
        "narrative": msg, "risks": [msg],
        "data_window": {"from": None, "to": None, "days": 0},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="정량(시스템) 분석")
    parser.add_argument("code", help="종목코드 (예: 005930)")
    parser.add_argument("--days", type=int, default=200, help="일봉 기간 (기본 200)")
    args = parser.parse_args()

    result = analyze(args.code, args.days)
    print(json.dumps(result, ensure_ascii=False, indent=2))
