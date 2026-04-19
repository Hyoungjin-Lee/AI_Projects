"""
indicators.py — pandas/numpy 기반 기술적 지표 라이브러리

외부 의존성 없이 pandas + numpy 만으로 구현.
모든 함수는 pandas Series(또는 DataFrame)를 받아 pandas Series(또는 dict)를 반환.

함수 목록:
  sma(series, n)                         — 단순 이동평균
  ema(series, n)                         — 지수 이동평균
  rsi(close, n=14)                       — RSI (Wilder's Smoothing)
  macd(close, fast=12, slow=26, signal=9)— MACD, 시그널, 히스토그램
  bollinger(close, n=20, k=2)            — 볼린저밴드 + %b + 밴드폭
  atr(high, low, close, n=14)            — Average True Range
  vwap(high, low, close, volume)         — VWAP (분봉 누적 기준)
  support_resistance(close, lookback, n) — 단순 피벗 기반 지지/저항
  drawdown(equity)                       — 낙폭 시리즈 + MDD
  sharpe(returns, rf, periods_per_year)  — 샤프 비율
"""

import numpy as np
import pandas as pd


# ── 이동평균 ──────────────────────────────────────────────────────────────────

def sma(series: pd.Series, n: int) -> pd.Series:
    """단순 이동평균 (Simple Moving Average)."""
    return series.rolling(window=n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    """지수 이동평균 (Exponential Moving Average), pandas ewm 사용."""
    return series.ewm(span=n, adjust=False).mean()


# ── RSI ───────────────────────────────────────────────────────────────────────

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """
    RSI — Wilder's Smoothing 방식 (RMA).

    첫 n개 평균을 SMA로 초기화한 뒤 이후는 RMA로 갱신.
    0~100 범위.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    # Wilder's RMA (alpha = 1/n)
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ── MACD ──────────────────────────────────────────────────────────────────────

def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """
    MACD, 시그널, 히스토그램을 dict로 반환.

    Returns
    -------
    {
      "macd":    pd.Series,   # EMA(fast) - EMA(slow)
      "signal":  pd.Series,   # EMA(macd, signal)
      "hist":    pd.Series,   # macd - signal
    }
    """
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "hist": hist}


# ── 볼린저밴드 ────────────────────────────────────────────────────────────────

def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> dict:
    """
    볼린저밴드 + %b + 밴드폭.

    Returns
    -------
    {
      "upper":     pd.Series,
      "mid":       pd.Series,   # SMA(n)
      "lower":     pd.Series,
      "pct_b":     pd.Series,   # (close - lower) / (upper - lower)
      "bandwidth": pd.Series,   # (upper - lower) / mid
    }
    """
    mid = sma(close, n)
    std = close.rolling(window=n, min_periods=n).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    band_range = upper - lower
    pct_b = (close - lower) / band_range.replace(0, np.nan)
    bandwidth = band_range / mid.replace(0, np.nan)
    return {"upper": upper, "mid": mid, "lower": lower, "pct_b": pct_b, "bandwidth": bandwidth}


# ── ATR ───────────────────────────────────────────────────────────────────────

def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """
    Average True Range — Wilder's RMA 방식.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


# ── VWAP ──────────────────────────────────────────────────────────────────────

def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    VWAP — 분봉 누적 계산 (당일 시가~현재 누적).

    Typical Price = (high + low + close) / 3
    VWAP = Σ(TP × volume) / Σvolume
    분봉 데이터 전체를 당일 세션으로 간주한다.
    """
    tp = (high + low + close) / 3
    cum_tp_vol = (tp * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


# ── 지지/저항 ─────────────────────────────────────────────────────────────────

def support_resistance(
    close: pd.Series,
    lookback: int = 60,
    n_levels: int = 3,
) -> dict:
    """
    단순 피벗 기반 지지/저항 레벨.

    lookback 기간 내에서 로컬 최저(지지)·최고(저항) 피벗 포인트를 찾아
    가격 클러스터링으로 n_levels개씩 추린다.

    Returns
    -------
    {
      "support":    list[float],   # 오름차순
      "resistance": list[float],   # 오름차순
    }
    """
    window = close.iloc[-lookback:] if len(close) >= lookback else close

    # 로컬 최소/최대: 좌우 각 2개 이상보다 작은/큰 포인트
    lows, highs = [], []
    arr = window.values
    for i in range(2, len(arr) - 2):
        if arr[i] < arr[i - 1] and arr[i] < arr[i - 2] and arr[i] < arr[i + 1] and arr[i] < arr[i + 2]:
            lows.append(arr[i])
        if arr[i] > arr[i - 1] and arr[i] > arr[i - 2] and arr[i] > arr[i + 1] and arr[i] > arr[i + 2]:
            highs.append(arr[i])

    support = _cluster_levels(lows, n_levels)
    resistance = _cluster_levels(highs, n_levels)
    return {"support": support, "resistance": resistance}


def _cluster_levels(levels: list, n: int, tol_pct: float = 0.01) -> list:
    """가격 레벨을 1% 이내 구간으로 클러스터링해 대표값(중앙값) n개 반환."""
    if not levels:
        return []
    arr = sorted(levels)
    clusters = []
    group = [arr[0]]
    for v in arr[1:]:
        if abs(v - group[-1]) / group[-1] <= tol_pct:
            group.append(v)
        else:
            clusters.append(float(np.median(group)))
            group = [v]
    clusters.append(float(np.median(group)))
    # 가장 많이 등장한 클러스터 우선 → 단순히 중간값 n개 선택
    return sorted(clusters)[-n:] if len(clusters) >= n else sorted(clusters)


# ── 낙폭 ──────────────────────────────────────────────────────────────────────

def drawdown(equity: pd.Series) -> dict:
    """
    낙폭(Drawdown) 시리즈와 최대 낙폭(MDD) 반환.

    Returns
    -------
    {
      "dd_series": pd.Series,   # 각 시점의 고점 대비 낙폭 (음수 또는 0)
      "mdd":       float,       # 최대 낙폭 (음수, 예: -0.23 = -23%)
    }
    """
    rolling_max = equity.cummax()
    dd_series = (equity - rolling_max) / rolling_max.replace(0, np.nan)
    mdd = float(dd_series.min())
    return {"dd_series": dd_series, "mdd": mdd}


# ── 샤프 ──────────────────────────────────────────────────────────────────────

def sharpe(
    returns: pd.Series,
    rf: float = 0.03,
    periods_per_year: int = 252,
) -> float:
    """
    샤프 비율 = (연환산 수익률 - 무위험 수익률) / 연환산 표준편차.

    Parameters
    ----------
    returns          : 일간 수익률 시리즈 (소수, 예: 0.012 = 1.2%)
    rf               : 무위험 수익률 (연간, 기본 3%)
    periods_per_year : 연 기간 수 (일봉=252, 분봉=252*390 등)

    Returns
    -------
    float — 소수점 2자리 반올림
    """
    excess = returns - rf / periods_per_year
    std = returns.std(ddof=1)
    if std == 0 or np.isnan(std):
        return float("nan")
    ratio = (excess.mean() / std) * np.sqrt(periods_per_year)
    return round(float(ratio), 2)
