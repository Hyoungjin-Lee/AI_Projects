"""
data_fetcher.py — 외부 데이터 수집 모듈

수집 항목:
  1. 미국 시장 지수 (S&P500, 나스닥, 다우) — Yahoo Finance
  2. 달러/원 환율
  3. 보유 종목별 뉴스 헤드라인 (네이버 금융)
  4. 공포탐욕지수 (CNN Fear & Greed)
  5. 종목 커뮤니티 분위기 (네이버 종토방)

변경 이력:
  - Opus 검증 반영: UTF-8 인코딩 수정, 재시도 로직 추가, 병렬 처리 적용
"""

import json
import sys
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

_ROOT = Path(__file__).parent.parent
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── 재시도 데코레이터 ─────────────────────────────────────────────────────────

def retry(max_attempts=3, delay=2, exceptions=(requests.Timeout, requests.ConnectionError)):
    """네트워크 일시 실패 시 지수 백오프로 재시도."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        raise
                    wait = delay * (2 ** attempt)
                    print(f"[재시도] {func.__name__} — {attempt+1}번째 재시도 ({wait}초 후): {e}", file=sys.stderr)
                    time.sleep(wait)
        return wrapper
    return decorator


# ── 미국 시장 지수 ────────────────────────────────────────────────────────────

def fetch_us_market() -> dict:
    """yfinance로 미국 주요 지수 수집."""
    result = {
        "sp500": None, "sp500_chg": None,
        "nasdaq": None, "nasdaq_chg": None,
        "dow": None, "dow_chg": None,
        "vix": None,
        "fetched_at": datetime.now().isoformat(),
    }

    symbols = {
        "^GSPC": ("sp500",  "sp500_chg"),
        "^IXIC": ("nasdaq", "nasdaq_chg"),
        "^DJI":  ("dow",    "dow_chg"),
        "^VIX":  ("vix",    None),
    }

    try:
        import yfinance as yf
        tickers = yf.Tickers(" ".join(symbols.keys()))
        for symbol, (val_key, chg_key) in symbols.items():
            try:
                info = tickers.tickers[symbol].fast_info
                curr = round(float(info.last_price), 2)
                prev = float(info.previous_close or 0)
                result[val_key] = curr
                if chg_key and prev:
                    chg_pct = (curr - prev) / prev * 100
                    result[chg_key] = f"{chg_pct:+.2f}%"
            except Exception as e:
                print(f"[미국지수] {symbol} 수집 실패: {e}", file=sys.stderr)
    except ImportError:
        print("[미국지수] yfinance 미설치 — 지수 수집 생략", file=sys.stderr)
    except Exception as e:
        print(f"[미국지수] 전체 수집 실패: {e}", file=sys.stderr)

    return result


# ── 달러/원 환율 ──────────────────────────────────────────────────────────────

def fetch_usd_krw() -> dict:
    """달러/원 환율 수집 (yfinance)."""
    try:
        import yfinance as yf
        fx = yf.Ticker("USDKRW=X")
        info = fx.fast_info
        curr = round(float(info.last_price), 1)
        prev = float(info.previous_close or 0)
        chg  = curr - prev
        return {
            "usd_krw":         curr,
            "usd_krw_chg":     round(chg, 1),
            "usd_krw_chg_pct": f"{chg/prev*100:+.2f}%" if prev else "N/A",
        }
    except ImportError:
        print("[환율] yfinance 미설치", file=sys.stderr)
    except Exception as e:
        print(f"[환율] 수집 실패: {e}", file=sys.stderr)
    return {"usd_krw": None, "usd_krw_chg": None, "usd_krw_chg_pct": None}


# ── 종목 뉴스 ─────────────────────────────────────────────────────────────────

@retry(max_attempts=2, delay=1)
def fetch_stock_news(code: str, name: str, max_news: int = 5) -> list:
    """
    네이버 금융 종목 뉴스 수집.
    여러 CSS 선택자를 순서대로 시도해 HTML 구조 변경에 대응.
    """
    news_list = []
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.encoding = "utf-8"  # 네이버 금융은 UTF-8
        soup = BeautifulSoup(resp.text, "html.parser")

        # 여러 선택자 시도 (HTML 구조 변경 대응)
        selectors = [
            ("table.type5 tr", "td.title a"),
            ("div.news_list li", "a.tltle"),
            ("ul.newsList li", "a"),
            ("table tr", "td a"),
        ]

        for table_sel, link_sel in selectors:
            rows = soup.select(table_sel)
            if not rows:
                continue
            for row in rows:
                title_tag = row.select_one(link_sel)
                if not title_tag or not title_tag.get_text(strip=True):
                    continue
                info_tag = row.select_one("td.info, span.press")
                date_tag = row.select_one("td.date, span.date")
                news_list.append({
                    "title": title_tag.get_text(strip=True),
                    "press": info_tag.get_text(strip=True) if info_tag else "",
                    "time":  date_tag.get_text(strip=True) if date_tag else "",
                    "url":   "https://finance.naver.com" + (title_tag.get("href") or ""),
                })
                if len(news_list) >= max_news:
                    break
            if news_list:
                break  # 성공한 선택자 있으면 중단

    except Exception as e:
        print(f"[뉴스] {code} 수집 실패: {e}", file=sys.stderr)

    return news_list


# ── 커뮤니티 분위기 (네이버 종토방) ──────────────────────────────────────────

@retry(max_attempts=2, delay=1)
def fetch_community_sentiment(code: str, max_posts: int = 10) -> dict:
    """
    네이버 종목토론방 최근 글 감성 분석.
    긍정/부정 키워드 카운팅으로 분위기 파악.
    """
    positive_kw = ["급등", "상승", "매수", "강세", "돌파", "목표가", "호재", "신고가", "기대", "좋아"]
    negative_kw = ["급락", "하락", "매도", "약세", "손절", "악재", "신저가", "우려", "위험", "떨어"]

    titles = []
    try:
        url = f"https://finance.naver.com/item/board.naver?code={code}&page=1"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # 여러 선택자 시도
        for selector in ["table.type2 tr", "table tr", "ul.boardList li"]:
            rows = soup.select(selector)
            for row in rows:
                title_tag = row.select_one("td.title a, a.title")
                if title_tag and title_tag.get_text(strip=True):
                    titles.append(title_tag.get_text(strip=True))
                if len(titles) >= max_posts:
                    break
            if titles:
                break

    except Exception as e:
        print(f"[커뮤니티] {code} 수집 실패: {e}", file=sys.stderr)

    if not titles:
        return {"sentiment": "알수없음", "score": 0.0, "pos_count": 0, "neg_count": 0, "sample_titles": []}

    pos_count = sum(1 for t in titles for kw in positive_kw if kw in t)
    neg_count = sum(1 for t in titles for kw in negative_kw if kw in t)
    total = pos_count + neg_count

    if total == 0:
        sentiment, score = "중립", 0.0
    else:
        score = (pos_count - neg_count) / total
        sentiment = "긍정적" if score > 0.3 else ("부정적" if score < -0.3 else "중립")

    return {
        "sentiment":     sentiment,
        "score":         round(score, 2),
        "pos_count":     pos_count,
        "neg_count":     neg_count,
        "sample_titles": titles[:3],
    }


# ── 공포탐욕지수 ──────────────────────────────────────────────────────────────

@retry(max_attempts=2, delay=2)
def fetch_fear_greed() -> dict:
    """CNN Fear & Greed Index."""
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        data = resp.json()
        fg = data.get("fear_and_greed", {})
        return {"score": round(fg.get("score", 0), 1), "rating": fg.get("rating", "N/A")}
    except Exception as e:
        print(f"[공포탐욕] 수집 실패: {e}", file=sys.stderr)
        return {"score": None, "rating": None}


# ── 종목별 병렬 수집 ──────────────────────────────────────────────────────────

def _fetch_single_stock(code: str, name: str) -> dict:
    """단일 종목의 뉴스 + 커뮤니티를 수집 (병렬 호출용)."""
    news = fetch_stock_news(code, name, max_news=5)
    time.sleep(0.3)  # 요청 간격
    sentiment = fetch_community_sentiment(code)
    return {"name": name, "news": news, "sentiment": sentiment}


# ── 통합 수집 ─────────────────────────────────────────────────────────────────

def fetch_all(holdings: list) -> dict:
    """
    모든 외부 데이터 통합 수집.

    Parameters
    ----------
    holdings : list of dict — [{"code": "005930", "name": "삼성전자"}, ...]

    Returns
    -------
    dict : 전체 수집 결과
    """
    print("[데이터수집] 미국 시장 지수...", file=sys.stderr)
    us_market = fetch_us_market()

    print("[데이터수집] 달러/원 환율...", file=sys.stderr)
    fx = fetch_usd_krw()

    print("[데이터수집] 공포탐욕지수...", file=sys.stderr)
    fear_greed = fetch_fear_greed()

    # 종목별 뉴스+커뮤니티 병렬 수집 (최대 3개 동시)
    stock_data = {}
    valid_holdings = [
        h for h in holdings
        if (h.get("code") or h.get("pdno", ""))
    ]

    if valid_holdings:
        print(f"[데이터수집] 종목 {len(valid_holdings)}개 뉴스/커뮤니티 병렬 수집...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            for h in valid_holdings:
                code = h.get("code") or h.get("pdno", "")
                name = h.get("name") or h.get("prdt_name", code)
                future = executor.submit(_fetch_single_stock, code, name)
                futures[future] = code

            for future in as_completed(futures):
                code = futures[future]
                try:
                    stock_data[code] = future.result()
                    print(f"  ✅ {code} 수집 완료", file=sys.stderr)
                except Exception as e:
                    print(f"  ⚠️  {code} 수집 실패: {e}", file=sys.stderr)
                    stock_data[code] = {"name": code, "news": [], "sentiment": {"sentiment": "알수없음", "score": 0.0}}

    return {
        "us_market":  us_market,
        "fx":         fx,
        "fear_greed": fear_greed,
        "stocks":     stock_data,
        "fetched_at": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    test_holdings = [
        {"code": "005930", "name": "삼성전자"},
        {"code": "000660", "name": "SK하이닉스"},
    ]
    result = fetch_all(test_holdings)
    print(json.dumps(result, ensure_ascii=False, indent=2))
