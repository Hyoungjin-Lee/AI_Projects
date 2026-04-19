"""
stock_discovery.py — 23:30 야간 종목 발굴 브리핑

실행 흐름:
  1. 미국 시장 마감 상황 + 섹터 흐름 파악 (data_fetcher 활용)
  2. 관심 종목 리스트 로드 (data/watchlist.json)
  3. KIS API → 관심 종목 + 스크리닝 후보 기술적 분석
  4. 조건 필터링: 시총 1000억 이상 + 거래량 충분 + 매수 시그널
  5. 섹터별 2종목 이내로 압축 추천
  6. 텔레그램으로 종목 발굴 보고서 전송

실행 방법:
  python3 stock_discovery.py           # 전체 실행
  python3 stock_discovery.py --dry-run # 텔레그램 전송 없이 출력만

관심 종목 파일: data/watchlist.json
  형식: [{"code": "005930", "name": "삼성전자", "sector": "반도체"}, ...]
"""

import argparse
import json
import sys
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(_ROOT / ".skills" / "stock-analysis" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from keychain_manager import inject_to_env
inject_to_env()
from state_manager import StateManager

_WATCHLIST_FILE  = _ROOT / "data" / "watchlist.json"
_MIN_MKTCAP_100M = 1000   # 시총 1000억 이상 (단위: 억원)
_MIN_VOL_RATIO   = 0.8    # 거래량이 평균 대비 80% 이상 (너무 거래 없는 종목 제외)
_MAX_PER_SECTOR  = 2      # 섹터당 최대 추천 종목 수

_WEEKDAYS = {0, 1, 2, 3, 4}


def run(dry_run: bool = False):
    now_str = datetime.now().strftime("%H:%M")
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][datetime.now().weekday()]
    today_str  = datetime.now().strftime(f"%Y년 %m월 %d일 ({weekday_kr})")

    print(f"[{now_str}] 종목 발굴 시작...", file=sys.stderr)

    # 주말에는 실행하지 않음 (금요일 밤은 토요일이지만 허용)
    today_weekday = date.today().weekday()
    if today_weekday == 6:  # 일요일만 건너뜀
        print("[발굴] 일요일입니다. 종료.", file=sys.stderr)
        return

    # ── 1. 미국 시장 상황 파악 ─────────────────────────────────────────────────
    print("[1/4] 미국 시장 상황 파악 중...", file=sys.stderr)
    us_data = {}
    try:
        from data_fetcher import fetch_us_market, fetch_usd_krw, fetch_fear_greed
        us_data["market"]     = fetch_us_market()
        us_data["fx"]         = fetch_usd_krw()
        us_data["fear_greed"] = fetch_fear_greed()
        print("  ✅ 미국 시장 데이터 수집 완료", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠️  미국 시장 데이터 수집 실패: {e}", file=sys.stderr)
        us_data = {"market": {}, "fx": {}, "fear_greed": {}}

    us_sentiment = _classify_us_sentiment(us_data)
    print(f"  미국 시장 방향: {us_sentiment}", file=sys.stderr)

    # ── 2. 관심 종목 리스트 로드 ──────────────────────────────────────────────
    print("[2/4] 관심 종목 리스트 로드 중...", file=sys.stderr)
    watchlist = _load_watchlist()
    if not watchlist:
        print("  ⚠️  관심 종목 없음. data/watchlist.json 파일을 확인하세요.", file=sys.stderr)
        # 빈 리스트로 계속 진행 (미국 시장 상황만 전송)

    print(f"  관심 종목 {len(watchlist)}개 로드", file=sys.stderr)

    # ── 3. 종목별 기술적 분석 ─────────────────────────────────────────────────
    print(f"[3/4] 종목 스크리닝 중...", file=sys.stderr)
    client = None
    try:
        from kis_client import KISClient
        client = KISClient()
    except Exception as e:
        print(f"  ⚠️  KIS 클라이언트 초기화 실패: {e}", file=sys.stderr)

    candidates = []
    for stock in watchlist:
        code   = stock["code"]
        name   = stock.get("name", code)
        sector = stock.get("sector", "기타")

        try:
            result = _screen_stock(client, code, name, sector, us_sentiment)
            if result:
                candidates.append(result)
                print(f"  ✅ {name}({code}) — {result['verdict']} (점수: {result['score']:.1f})", file=sys.stderr)
            else:
                print(f"  ─ {name}({code}) — 조건 미달", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️  {name}({code}) 분석 실패: {e}", file=sys.stderr)

    # ── 4. 섹터별 압축 추천 ───────────────────────────────────────────────────
    print("[4/4] 추천 종목 선정 중...", file=sys.stderr)
    recommendations = _select_recommendations(candidates)

    # ── state 기록 ────────────────────────────────────────────────────────────
    try:
        state = StateManager()
        # 미국 시장 방향 기록
        market = us_data.get("market", {})
        state.update("market", {
            "us_sentiment": us_sentiment,
            "usd_krw":      us_data.get("fx", {}).get("usd_krw"),
            "fear_greed":   us_data.get("fear_greed", {}).get("score"),
        }, caller="stock_discovery")
        # 발굴 결과 기록
        state.update("discovery", {
            "candidates": [r["code"] for r in recommendations],
            "top_pick":   recommendations[0]["code"] if recommendations else None,
        }, caller="stock_discovery")
        print("[state] 종목 발굴 상태 기록 완료", file=sys.stderr)
    except Exception as e:
        print(f"[state] 기록 실패 (무시): {e}", file=sys.stderr)

    # ── 5. 보고서 생성 + 전송 ─────────────────────────────────────────────────
    report = _build_discovery_report(today_str, us_data, us_sentiment, recommendations, len(watchlist))

    if dry_run:
        print("\n" + "=" * 50)
        print(report)
        print("=" * 50)
        print("\n[DRY-RUN] 텔레그램 전송 생략")
    else:
        from telegram_sender import send_report
        ok = send_report(report, title="🔍 종목 발굴 브리핑")
        if ok:
            print("[완료] 텔레그램 전송 성공 ✅", file=sys.stderr)
        else:
            print("[오류] 텔레그램 전송 실패 ❌", file=sys.stderr)
            _save_report_fallback(report)


# ── 관심 종목 관리 ────────────────────────────────────────────────────────────

def _load_watchlist() -> list:
    """
    관심 종목 파일 로드.
    파일 없으면 빈 리스트 반환 + 예시 파일 생성.
    """
    if not _WATCHLIST_FILE.exists():
        _create_sample_watchlist()
        print(f"  📝 예시 관심 종목 파일 생성: {_WATCHLIST_FILE}", file=sys.stderr)
        return []

    try:
        data = json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  ⚠️  watchlist.json 로드 실패: {e}", file=sys.stderr)
        return []


def _create_sample_watchlist():
    """관심 종목 예시 파일 생성."""
    _WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    sample = [
        {"code": "005930", "name": "삼성전자",   "sector": "반도체"},
        {"code": "000660", "name": "SK하이닉스", "sector": "반도체"},
        {"code": "035420", "name": "NAVER",       "sector": "인터넷"},
        {"code": "035720", "name": "카카오",      "sector": "인터넷"},
        {"code": "006400", "name": "삼성SDI",     "sector": "2차전지"},
        {"code": "373220", "name": "LG에너지솔루션", "sector": "2차전지"},
        {"code": "207940", "name": "삼성바이오로직스", "sector": "바이오"},
        {"code": "068270", "name": "셀트리온",    "sector": "바이오"},
    ]
    _WATCHLIST_FILE.write_text(
        json.dumps(sample, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ── 미국 시장 방향성 분류 ──────────────────────────────────────────────────────

def _classify_us_sentiment(us_data: dict) -> str:
    """
    미국 지수 + 공포탐욕 지수로 내일 한국 시장 방향성 추정.
    반환: "강세" | "약세" | "혼조" | "중립"
    """
    market = us_data.get("market", {})
    fg     = us_data.get("fear_greed", {})

    sp500_chg  = _parse_chg(market.get("sp500_chg", ""))
    nasdaq_chg = _parse_chg(market.get("nasdaq_chg", ""))
    fg_score   = fg.get("score", 50) or 50

    # 두 지수 평균 변동
    valid_chgs = [c for c in [sp500_chg, nasdaq_chg] if c is not None]
    avg_chg = sum(valid_chgs) / len(valid_chgs) if valid_chgs else 0

    if avg_chg >= 1.0 and fg_score >= 50:
        return "강세 📈"
    elif avg_chg >= 0.5:
        return "소폭 강세 📈"
    elif avg_chg <= -1.0 and fg_score <= 40:
        return "약세 📉"
    elif avg_chg <= -0.5:
        return "소폭 약세 📉"
    else:
        return "혼조 ↔️"


def _parse_chg(chg_str) -> float | None:
    """"+1.23%" 형식 파싱"""
    if not chg_str:
        return None
    try:
        return float(str(chg_str).replace("%", "").replace("+", "").strip())
    except (ValueError, TypeError):
        return None


# ── 종목 스크리닝 ─────────────────────────────────────────────────────────────

def _screen_stock(client, code: str, name: str, sector: str, us_sentiment: str) -> dict | None:
    """
    종목 스크리닝: 조건 미달 시 None 반환, 통과 시 후보 dict 반환.

    조건:
      1. 시총 1000억 이상
      2. 거래량 5일 평균 대비 80% 이상 (거래 소외 종목 제외)
      3. 기술적 매수 시그널 (verdict == BUY 또는 HOLD+RSI 과매도)
    """
    # 일봉 데이터 수집
    if client:
        _fetch_daily_if_needed(client, code)

    # 기술적 분석
    try:
        import analyze_swing as _swing
        analysis = _swing.analyze(code, days=60)
    except Exception:
        return None

    if not analysis:
        return None

    verdict    = analysis.get("verdict", "WATCH")
    confidence = analysis.get("confidence", 0.0)
    stop_loss  = analysis.get("stop_loss")
    target     = analysis.get("target_price")
    cur_price  = analysis.get("current_price", 0)

    # 매수 시그널 필터
    if verdict not in ("BUY", "HOLD"):
        return None
    if verdict == "HOLD" and confidence < 0.5:
        return None

    # 거래량 체크 (캐시 파일에서 읽기)
    vol_ratio = _get_vol_ratio(code)
    if vol_ratio is not None and vol_ratio < _MIN_VOL_RATIO:
        return None

    # 시총 체크 (가격 × 상장주식수 추정 — KIS API 미지원 시 가격으로 대략 판단)
    # 실제 시총은 KIS 종목 마스터 API 필요; 여기서는 confidence 기반으로 대체
    # TODO: KIS 종목 정보 API(CTPF1604R) 연동 후 시총 필터 정밀화

    # 미국 시장 연동 가중
    us_bonus = 0.0
    if "강세" in us_sentiment and sector in ("반도체", "2차전지", "인터넷"):
        us_bonus = 5.0
    elif "약세" in us_sentiment:
        us_bonus = -3.0

    # 최종 점수 (0~100)
    score = confidence * 80 + us_bonus
    if vol_ratio:
        score += min(vol_ratio - 1.0, 1.0) * 10   # 거래량 급증 보너스

    return {
        "code":       code,
        "name":       name,
        "sector":     sector,
        "verdict":    verdict,
        "confidence": confidence,
        "cur_price":  cur_price,
        "stop_loss":  stop_loss,
        "target":     target,
        "vol_ratio":  vol_ratio,
        "score":      score,
        "signals":    analysis.get("key_signals", [])[:2],
    }


def _get_vol_ratio(code: str) -> float | None:
    """캐시된 일봉 파일에서 최근 거래량 비율 계산."""
    try:
        import pandas as pd
        import glob

        cache_dir = _ROOT / "data" / "raw"
        files = sorted(glob.glob(str(cache_dir / f"{code}_daily_*.json")))
        if not files:
            return None

        with open(files[-1], encoding="utf-8") as f:
            bars = json.load(f)

        df = pd.DataFrame(bars)
        col = next((c for c in ["acml_vol", "volume"] if c in df.columns), None)
        if not col:
            return None

        df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=[col])
        if len(df) < 2:
            return None

        avg_vol   = df[col].iloc[1:6].mean()   # 2~6번째 행 = 최근 5일
        today_vol = df[col].iloc[0]             # 첫 행 = 최신
        return round(today_vol / avg_vol, 2) if avg_vol > 0 else None
    except Exception:
        return None


def _fetch_daily_if_needed(client, code: str, days: int = 60):
    cache_dir = _ROOT / "data" / "raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    cache_file = cache_dir / f"{code}_daily_{today}.json"
    if cache_file.exists():
        return
    try:
        bars = client.get_daily_chart(code, days=days)
        if bars:
            cache_file.write_text(
                json.dumps(bars, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
    except Exception as e:
        print(f"  [캐시] {code} 일봉 저장 실패: {e}", file=sys.stderr)


# ── 추천 종목 선정 ────────────────────────────────────────────────────────────

def _select_recommendations(candidates: list) -> list:
    """
    섹터별 최대 2종목, 점수 기준 내림차순 선정.
    전체 최대 6종목으로 제한.
    """
    # 점수 내림차순 정렬
    sorted_c = sorted(candidates, key=lambda x: x["score"], reverse=True)

    sector_count: dict[str, int] = {}
    result = []
    for c in sorted_c:
        if len(result) >= 6:
            break
        sec = c["sector"]
        if sector_count.get(sec, 0) < _MAX_PER_SECTOR:
            result.append(c)
            sector_count[sec] = sector_count.get(sec, 0) + 1

    return result


# ── 발굴 보고서 빌더 ──────────────────────────────────────────────────────────

def _build_discovery_report(today_str, us_data, us_sentiment, recommendations, watchlist_count) -> str:
    lines = []
    lines.append(f"🔍 {today_str} 종목 발굴")
    lines.append(f"⏰ {datetime.now().strftime('%H:%M')} 기준")
    lines.append("=" * 28)

    # 미국 시장 요약
    market = us_data.get("market", {})
    fx     = us_data.get("fx", {})
    fg     = us_data.get("fear_greed", {})

    lines.append(f"\n🌏 미국 시장 마감")
    lines.append(f"  방향: {us_sentiment}")

    sp500  = market.get("sp500")
    nasdaq = market.get("nasdaq")
    if sp500:
        lines.append(f"  S&P500  {sp500:,.0f}  {market.get('sp500_chg', '')}")
    if nasdaq:
        lines.append(f"  나스닥  {nasdaq:,.0f}  {market.get('nasdaq_chg', '')}")

    usd = fx.get("usd_krw")
    if usd:
        lines.append(f"  달러/원 {usd:,.1f}원  {fx.get('usd_krw_chg_pct', '')}")

    if fg.get("score") is not None:
        score = fg["score"]
        rating = fg.get("rating", "")
        fg_emoji = "😱" if score < 25 else ("😰" if score < 45 else ("😐" if score < 55 else ("😊" if score < 75 else "🤩")))
        lines.append(f"  공포탐욕 {fg_emoji} {score} ({rating})")

    # 추천 종목
    lines.append(f"\n💡 관심 종목 스크리닝 결과")
    lines.append(f"  검색 대상: {watchlist_count}개 종목")

    if not recommendations:
        lines.append("  ⚠️  현재 조건 충족 종목 없음")
        lines.append("  → 미국 시장 방향 확인 후 내일 시장 개장 시 재평가 권장")
    else:
        lines.append(f"  ✅ 추천 종목 {len(recommendations)}개\n")

        # 섹터별 그룹핑
        by_sector: dict[str, list] = {}
        for r in recommendations:
            by_sector.setdefault(r["sector"], []).append(r)

        for sector, stocks in by_sector.items():
            lines.append(f"  📂 {sector}")
            for s in stocks:
                code      = s["code"]
                name      = s["name"]
                verdict   = s["verdict"]
                conf      = s["confidence"]
                cur       = s.get("cur_price", 0)
                stop      = s.get("stop_loss")
                target    = s.get("target")
                vol_r     = s.get("vol_ratio")
                v_emoji   = "📗" if verdict == "BUY" else "📘"
                vol_txt   = f" | 거래량 {vol_r:.1f}배" if vol_r else ""

                lines.append(f"    {v_emoji} {name}({code})  {cur:,.0f}원  {verdict} ({conf:.0%}){vol_txt}")
                if stop and target:
                    lines.append(f"       손절: {stop:,.0f}  /  목표: {target:,.0f}원")
                elif stop:
                    lines.append(f"       손절: {stop:,.0f}원")

                # 핵심 시그널
                for sig in s.get("signals", []):
                    lines.append(f"       • {sig.get('name','')}: {sig.get('value','')} — {sig.get('interpretation','')}")

    lines.append(f"\n⚠️ 주의: 이 분석은 기술적 지표 기반입니다.")
    lines.append("투자 결정은 본인의 판단 하에 이루어져야 합니다.")
    lines.append(f"\n※ {datetime.now().strftime('%H:%M')} 기준 | 관심 종목 수정: data/watchlist.json")
    return "\n".join(lines)


# ── 유틸리티 ──────────────────────────────────────────────────────────────────

def _save_report_fallback(report: str):
    fallback_dir = _ROOT / "reports"
    fallback_dir.mkdir(exist_ok=True)
    fname = fallback_dir / f"discovery_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    fname.write_text(report, encoding="utf-8")
    print(f"[저장] 보고서 저장됨: {fname}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="야간 종목 발굴 브리핑")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 출력만")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
