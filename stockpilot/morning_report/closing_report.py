"""
closing_report.py — 16:00 장마감 결산 브리핑

실행 흐름:
  1. KIS API → 오늘 최종 잔고·수익률 조회
  2. KIS API → 종목별 당일 OHLCV + 체결내역 분석
  3. 거래량 이상 감지, 장중 고저 분석
  4. 내일 대응 전략 생성
  5. 매매일지 파일 자동 저장 (reports/journal/journal_YYYYMMDD.md)
  6. 텔레그램으로 장마감 결산 전송 (20:30 — 넥스트장 포함)

실행 방법:
  python3 closing_report.py           # 전체 실행
  python3 closing_report.py --dry-run # 텔레그램 전송 없이 출력만
"""

import argparse
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

_WEEKDAYS = {0, 1, 2, 3, 4}
_JOURNAL_DIR = _ROOT / "reports" / "journal"


def run(dry_run: bool = False):
    now_str = datetime.now().strftime("%H:%M")
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][datetime.now().weekday()]
    today_str = datetime.now().strftime(f"%Y년 %m월 %d일 ({weekday_kr})")
    today_date = datetime.now().strftime("%Y%m%d")

    print(f"[{now_str}] 장마감 결산 시작...", file=sys.stderr)

    if date.today().weekday() not in _WEEKDAYS:
        print("[결산] 오늘은 주말입니다. 종료.", file=sys.stderr)
        return

    # ── 1. 잔고 + 오늘 수익 조회 ──────────────────────────────────────────────
    print("[1/4] 잔고 및 수익 조회 중...", file=sys.stderr)
    client = None
    try:
        from kis_client import KISClient
        client = KISClient()
        balance_raw = client.get_balance()
    except Exception as e:
        print(f"[오류] KIS 잔고 조회 실패: {e}", file=sys.stderr)
        return

    holdings = _parse_holdings(balance_raw)
    cash_info = _parse_cash(balance_raw)

    # 주문가능현금 별도 조회 (TTTC8908R)
    try:
        orderable_cash = client.get_orderable_cash()
        cash_info["orderable"] = orderable_cash
    except Exception as e:
        print(f"[경고] 주문가능현금 조회 실패 (D+2로 대체): {e}", file=sys.stderr)

    if not holdings:
        print("[결산] 보유 종목 없음. 종료.", file=sys.stderr)
        msg = (
            f"📊 {today_str} 장마감 결산\n\n"
            "오늘 보유 종목이 없습니다.\n"
            "내일도 좋은 기회를 찾아봐요! 💪"
        )
        if dry_run:
            print(msg)
        else:
            from telegram_sender import send_report
            send_report(msg, title="")
        return

    # ── 2. 당일 일봉 + 기술적 분석 수집 ──────────────────────────────────────
    print(f"[2/4] 종목 {len(holdings)}개 당일 분석 중...", file=sys.stderr)
    daily_data = {}
    analysis_results = {}

    for h in holdings:
        code = h["code"]
        name = h["name"]

        # 당일 일봉 데이터 (시가·고가·저가·종가·거래량)
        try:
            ohlcv = _fetch_today_ohlcv(client, code)
            daily_data[code] = ohlcv
            print(f"  ✅ {name}({code}) 일봉 수집 완료", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️  {name}({code}) 일봉 수집 실패: {e}", file=sys.stderr)
            daily_data[code] = None

        # 기술적 분석 (손절/목표가 재확인)
        try:
            _fetch_daily_if_needed(client, code)
            import analyze_swing as _swing
            analysis_results[code] = _swing.analyze(code, days=60)
        except Exception as e:
            print(f"  ⚠️  {name}({code}) 기술분석 실패: {e}", file=sys.stderr)
            analysis_results[code] = None

    # ── 3. 거래량 이상 감지 + 내일 대응 전략 ─────────────────────────────────
    print("[3/4] 거래량 분석 및 내일 전략 생성 중...", file=sys.stderr)
    stock_strategies = {}
    for h in holdings:
        code = h["code"]
        ohlcv = daily_data.get(code)
        analysis = analysis_results.get(code)
        stock_strategies[code] = _build_stock_strategy(h, ohlcv, analysis)

    # ── state 기록 ────────────────────────────────────────────────────────────
    try:
        state = StateManager()
        # 장마감 기준 시그널 업데이트
        holdings_signals = {
            h["code"]: {
                "signal":  (analysis_results.get(h["code"]) or {}).get("verdict", "WATCH"),
                "pnl_pct": h.get("pnl_pct", 0.0),
            }
            for h in holdings
        }
        state.update("holdings", holdings_signals, caller="closing_report")
        # 거래량 급등 종목 기록
        for h in holdings:
            ohlcv = daily_data.get(h["code"]) or {}
            if ohlcv.get("vol_ratio", 0) >= 2.5:
                state.set_alert("vol_spike", h["code"], caller="closing_report")
        print("[state] 장마감 상태 기록 완료", file=sys.stderr)
    except Exception as e:
        print(f"[state] 기록 실패 (무시): {e}", file=sys.stderr)

    # ── 4. 보고서 생성 + 일지 저장 + 텔레그램 전송 ───────────────────────────
    print("[4/4] 결산 보고서 생성 중...", file=sys.stderr)
    report = _build_closing_report(today_str, holdings, daily_data, stock_strategies, cash_info)

    # 매매일지 파일 저장 (dry-run 여부 무관하게 항상 저장)
    journal_path = _save_journal(today_date, today_str, holdings, daily_data, stock_strategies, cash_info)
    print(f"[일지] 저장 완료: {journal_path}", file=sys.stderr)

    if dry_run:
        print("\n" + "=" * 50)
        print(report)
        print("=" * 50)
        print(f"\n[DRY-RUN] 텔레그램 전송 생략 (일지는 저장됨: {journal_path})")
    else:
        from telegram_sender import send_report
        ok = send_report(report, title="📊 장마감 결산")
        if ok:
            print("[완료] 텔레그램 전송 성공 ✅", file=sys.stderr)
        else:
            print("[오류] 텔레그램 전송 실패 ❌", file=sys.stderr)
            # 실패 시 reports/ 폴더에 텍스트로 저장
            _save_report_fallback(report, today_date)


# ── 당일 OHLCV 수집 ───────────────────────────────────────────────────────────

def _fetch_today_ohlcv(client, code: str) -> dict:
    """당일 일봉 데이터 수집. KIS 일봉차트에서 오늘 행만 추출."""
    bars = client.get_daily_chart(code, days=5)  # 최근 5일치 요청
    if not bars:
        return {}

    import pandas as pd
    df = pd.DataFrame(bars)

    # KIS 컬럼 정규화
    col_map = {
        "stck_bsop_date": "date",
        "stck_oprc": "open",
        "stck_hgpr": "high",
        "stck_lwpr": "low",
        "stck_clpr": "close",
        "acml_vol":  "volume",
        "prdy_vrss": "change",
        "prdy_ctrt": "change_pct",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
    for col in ["open", "high", "low", "close", "volume", "change", "change_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    today_yyyymmdd = datetime.now().strftime("%Y%m%d")
    if "date" in df.columns:
        today_row = df[df["date"] == today_yyyymmdd]
        if today_row.empty:
            today_row = df.iloc[[0]]  # KIS는 최신이 첫 행
    else:
        today_row = df.iloc[[0]]

    if today_row.empty:
        return {}

    row = today_row.iloc[0]

    # 거래량 이상치: 최근 5일 평균 대비
    avg_vol = df["volume"].mean() if "volume" in df.columns else 0
    today_vol = _safe_float(row.get("volume"))
    vol_ratio = today_vol / avg_vol if avg_vol > 0 else 1.0

    return {
        "open":       _safe_float(row.get("open")),
        "high":       _safe_float(row.get("high")),
        "low":        _safe_float(row.get("low")),
        "close":      _safe_float(row.get("close")),
        "volume":     _safe_int(row.get("volume")),
        "change":     _safe_float(row.get("change")),
        "change_pct": _safe_float(row.get("change_pct")),
        "vol_ratio":  round(vol_ratio, 2),
        "avg_vol_5d": round(avg_vol, 0),
    }


def _fetch_daily_if_needed(client, code: str, days: int = 60):
    """일봉 캐시가 없으면 KIS에서 받아 저장."""
    cache_dir = _ROOT / "data" / "raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    cache_file = cache_dir / f"{code}_daily_{today}.json"
    if cache_file.exists():
        return
    try:
        bars = client.get_daily_chart(code, days=days)
        if bars:
            import json
            cache_file.write_text(
                json.dumps(bars, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
    except Exception as e:
        print(f"  [캐시] {code} 일봉 저장 실패: {e}", file=sys.stderr)


# ── 종목별 내일 전략 생성 ─────────────────────────────────────────────────────

def _build_stock_strategy(holding: dict, ohlcv: dict | None, analysis: dict | None) -> dict:
    """
    당일 OHLCV + 기술적 분석을 종합해 내일 대응 전략을 반환.

    반환 키:
      vol_alert   : 거래량 이상 여부 및 설명
      candle_note : 캔들 해석 (양봉/음봉/장대, 윗꼬리 등)
      tomorrow    : 내일 대응 전략 문자열
    """
    pnl_pct = holding.get("pnl_pct", 0.0)
    avg_price = holding.get("avg_price", 0.0)

    result = {"vol_alert": None, "candle_note": None, "tomorrow": "내일 시장 상황 확인 후 대응"}

    if not ohlcv:
        result["tomorrow"] = "오늘 데이터 없음 — 내일 장 시작 전 수동 확인 필요"
        return result

    o = ohlcv.get("open", 0)
    h = ohlcv.get("high", 0)
    l = ohlcv.get("low", 0)
    c = ohlcv.get("close", 0)
    vol_ratio = ohlcv.get("vol_ratio", 1.0)
    chg_pct   = ohlcv.get("change_pct", 0.0)

    # 거래량 이상 감지
    if vol_ratio >= 2.5:
        result["vol_alert"] = f"🚨 거래량 급증 (평균 대비 {vol_ratio:.1f}배) — 세력 유입 또는 재료 발생 주의"
    elif vol_ratio >= 1.5:
        result["vol_alert"] = f"⚡ 거래량 증가 (평균 대비 {vol_ratio:.1f}배)"
    elif vol_ratio < 0.5:
        result["vol_alert"] = f"💤 거래량 급감 (평균 대비 {vol_ratio:.1f}배) — 관망세"

    # 캔들 해석
    if o and h and l and c:
        body = abs(c - o)
        total_range = h - l if h != l else 1
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        body_ratio = body / total_range

        if chg_pct > 3:
            result["candle_note"] = f"강한 양봉 (+{chg_pct:.1f}%) — 상승 모멘텀"
        elif chg_pct > 0.5:
            note = "양봉"
            if upper_wick > body * 1.5:
                note += " + 긴 윗꼬리 (고점 매도 압력 주의)"
            result["candle_note"] = note
        elif chg_pct < -3:
            result["candle_note"] = f"강한 음봉 ({chg_pct:.1f}%) — 하락 압력"
        elif chg_pct < -0.5:
            note = "음봉"
            if lower_wick > body * 1.5:
                note += " + 긴 아랫꼬리 (저점 매수세 유입)"
            result["candle_note"] = note
        else:
            result["candle_note"] = "도지 (방향성 불명확)"

    # 내일 대응 전략
    verdict   = (analysis or {}).get("verdict", "WATCH")
    stop_loss = (analysis or {}).get("stop_loss")
    target    = (analysis or {}).get("target_price")
    confidence = (analysis or {}).get("confidence", 0.0)

    strategies = []

    # 수익 상황별
    if pnl_pct >= 10:
        strategies.append(f"수익 {pnl_pct:.1f}% — 분할 익절 검토 (1/3 이상)")
    elif pnl_pct <= -7:
        if stop_loss and avg_price and avg_price > 0:
            strategies.append(f"손실 {pnl_pct:.1f}% — 손절 기준가 {stop_loss:,.0f}원 재확인 필수")
        else:
            strategies.append(f"손실 {pnl_pct:.1f}% — 추가 하락 시 손절 판단 필요")

    # 시그널 기반
    if verdict == "BUY" and confidence >= 0.6:
        strategies.append(f"기술적 매수 시그널 (확신도 {confidence:.0%}) — 내일 추가 매수 검토 가능")
    elif verdict == "SELL":
        strategies.append("매도 시그널 — 내일 추가 하락 시 비중 축소 고려")

    # 거래량 이상
    if vol_ratio >= 2.5:
        strategies.append("거래량 급증 — 내일 갭 상승 출발 가능성, 고점 매도 준비")

    # 손절/목표가
    if stop_loss:
        strategies.append(f"손절가: {stop_loss:,.0f}원")
    if target and chg_pct < 5:
        strategies.append(f"목표가: {target:,.0f}원")

    if not strategies:
        strategies.append("특이사항 없음 — 내일 시장 흐름 확인 후 대응")

    result["tomorrow"] = " | ".join(strategies)
    return result


# ── 결산 보고서 빌더 ──────────────────────────────────────────────────────────

def _build_closing_report(today_str, holdings, daily_data, strategies, cash_info) -> str:
    lines = []
    lines.append(f"📊 {today_str} 장마감 결산")
    lines.append(f"⏰ {datetime.now().strftime('%H:%M')} 기준")
    lines.append("=" * 28)

    total_eval   = 0
    total_profit = 0
    total_invest = 0

    for h in holdings:
        code     = h["code"]
        name     = h["name"]
        qty      = h.get("qty", 0)
        avg      = h.get("avg_price", 0)
        cur      = h.get("current_price", 0)
        pnl      = h.get("pnl", 0) or ((cur - avg) * qty if avg and cur else 0)
        pnl_pct  = h.get("pnl_pct", 0.0)
        eval_amt = cur * qty if cur and qty else 0
        invest   = avg * qty if avg and qty else 0

        total_eval   += eval_amt
        total_profit += pnl
        total_invest += invest

        pnl_emoji = "🔴" if pnl_pct < 0 else "🟢"
        ohlcv = daily_data.get(code) or {}
        strat = strategies.get(code, {})

        chg_pct   = ohlcv.get("change_pct", 0.0)
        chg_arrow = "▲" if chg_pct > 0 else ("▼" if chg_pct < 0 else "━")
        hi  = ohlcv.get("high", 0)
        lo  = ohlcv.get("low", 0)
        vol = ohlcv.get("volume", 0)
        vol_ratio = ohlcv.get("vol_ratio", 0)

        lines.append(f"\n{pnl_emoji} {name}({code})")
        lines.append(f"  종가: {cur:,.0f}원  {chg_arrow}{abs(chg_pct):.2f}%  |  평가손익: {pnl:+,.0f}원 ({pnl_pct:+.2f}%)")

        if hi and lo:
            lines.append(f"  고가: {hi:,.0f}  /  저가: {lo:,.0f}  |  거래량: {vol:,}주")

        candle = strat.get("candle_note")
        if candle:
            lines.append(f"  📊 {candle}")

        vol_alert = strat.get("vol_alert")
        if vol_alert:
            lines.append(f"  {vol_alert}")

        tomorrow = strat.get("tomorrow", "")
        if tomorrow:
            lines.append(f"  📌 내일 전략: {tomorrow}")

    # ── 포트폴리오 총계 ───────────────────────────────────────────────────────
    lines.append(f"\n{'=' * 28}")
    lines.append("📋 오늘 결산 요약")

    deposit        = cash_info.get("deposit", 0)
    orderable      = cash_info.get("orderable", 0)
    d1             = cash_info.get("d1", 0)
    d2             = cash_info.get("d2", 0)
    stock_eval_api = cash_info.get("stock_eval", 0)
    net_asset      = cash_info.get("net_asset", 0)
    prev_net_asset = cash_info.get("prev_net_asset", 0)
    asset_chg      = cash_info.get("asset_chg", 0)
    today_buy      = cash_info.get("today_buy", 0)
    today_sell     = cash_info.get("today_sell", 0)
    today_fee      = cash_info.get("today_fee", 0)
    eval_pnl       = cash_info.get("eval_pnl", 0)

    # 총자산: API 순자산 우선, 없으면 주식+예수금 합산
    display_net   = net_asset if net_asset > 0 else (total_eval + deposit)
    # 유가평가: API 값 우선, 없으면 보유종목 합산
    display_stock = stock_eval_api if stock_eval_api > 0 else total_eval
    # 자산증감: API 직접 제공, 없으면 계산
    if asset_chg == 0 and prev_net_asset > 0:
        asset_chg = display_net - prev_net_asset
    asset_chg_pct = (asset_chg / prev_net_asset * 100) if prev_net_asset > 0 else 0.0
    # 평가손익: API 값 우선, 없으면 종목 합산
    display_pnl   = eval_pnl if eval_pnl != 0 else total_profit
    invest_return = (display_pnl / total_invest * 100) if total_invest > 0 else 0.0

    pnl_emoji   = "🔴" if display_pnl < 0 else "🟢"
    asset_emoji = "🔴" if asset_chg < 0 else "🟢"

    # 총자산
    lines.append(f"\n💰 총자산")
    lines.append(f"  총평가금액:   {display_net:>12,.0f}원")
    lines.append(f"  유가평가금액: {display_stock:>12,.0f}원")
    if prev_net_asset > 0:
        lines.append(f"  전일순자산:   {prev_net_asset:>12,.0f}원")
        lines.append(f"  {asset_emoji} 자산증감:   {asset_chg:>+12,.0f}원 ({asset_chg_pct:+.2f}%)")

    # 정산현황
    lines.append(f"\n📊 정산현황")
    if today_buy > 0:
        lines.append(f"  금일매수:     {today_buy:>12,.0f}원")
    if today_sell > 0:
        lines.append(f"  금일매도:     {today_sell:>12,.0f}원")
    if today_fee > 0:
        lines.append(f"  금일제비용:   {today_fee:>12,.0f}원")
    lines.append(f"  {pnl_emoji} 평가손익합계: {display_pnl:>+12,.0f}원 ({invest_return:+.2f}%)")

    # 예수금
    lines.append(f"\n💵 예수금")
    lines.append(f"  예수금(총):   {deposit:>12,.0f}원")
    if d1 > 0:
        lines.append(f"  D+1 정산:     {d1:>12,.0f}원")
    if d2 > 0:
        lines.append(f"  D+2 정산:     {d2:>12,.0f}원")
    lines.append(f"  주문가능:     {orderable:>12,.0f}원")

    lines.append(f"\n※ {datetime.now().strftime('%H:%M')} 정규장 마감 기준. 실현손익은 체결내역을 확인하세요.")
    return "\n".join(lines)


# ── 매매일지 저장 ─────────────────────────────────────────────────────────────

def _save_journal(today_date, today_str, holdings, daily_data, strategies, cash_info) -> Path:
    """
    오늘 매매일지를 Markdown 파일로 저장.
    경로: reports/journal/journal_YYYYMMDD.md
    """
    _JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    path = _JOURNAL_DIR / f"journal_{today_date}.md"

    deposit        = cash_info.get("deposit", 0)
    orderable      = cash_info.get("orderable", 0)
    d1             = cash_info.get("d1", 0)
    d2             = cash_info.get("d2", 0)
    stock_eval_api = cash_info.get("stock_eval", 0)
    net_asset      = cash_info.get("net_asset", 0)
    prev_net_asset = cash_info.get("prev_net_asset", 0)
    asset_chg      = cash_info.get("asset_chg", 0)
    today_buy      = cash_info.get("today_buy", 0)
    today_sell     = cash_info.get("today_sell", 0)
    today_fee      = cash_info.get("today_fee", 0)
    eval_pnl       = cash_info.get("eval_pnl", 0)

    total_eval   = sum(
        (h.get("current_price", 0) * h.get("qty", 0)) for h in holdings
    )
    total_profit = sum(
        h.get("pnl", 0) or (
            (h.get("current_price", 0) - h.get("avg_price", 0)) * h.get("qty", 0)
        )
        for h in holdings
    )
    display_net   = net_asset if net_asset > 0 else (total_eval + deposit)
    display_stock = stock_eval_api if stock_eval_api > 0 else total_eval
    display_pnl   = eval_pnl if eval_pnl != 0 else total_profit
    if asset_chg == 0 and prev_net_asset > 0:
        asset_chg = display_net - prev_net_asset

    md = [
        f"# 📊 매매일지 — {today_str}",
        f"",
        f"> 작성: {datetime.now().strftime('%Y-%m-%d %H:%M')} (자동 생성)",
        f"",
        f"## 💰 총자산",
        f"",
        f"| 항목 | 금액 |",
        f"|------|------|",
        f"| 총평가금액 | {display_net:,.0f}원 |",
        f"| 유가평가금액 | {display_stock:,.0f}원 |",
        f"| 전일순자산 | {prev_net_asset:,.0f}원 |",
        f"| 자산증감 | {asset_chg:+,.0f}원 |",
        f"",
        f"## 📊 정산현황",
        f"",
        f"| 항목 | 금액 |",
        f"|------|------|",
        f"| 금일매수 | {today_buy:,.0f}원 |",
        f"| 금일매도 | {today_sell:,.0f}원 |",
        f"| 금일제비용 | {today_fee:,.0f}원 |",
        f"| 평가손익합계 | {display_pnl:+,.0f}원 |",
        f"",
        f"## 💵 예수금",
        f"",
        f"| 항목 | 금액 |",
        f"|------|------|",
        f"| 예수금(총) | {deposit:,.0f}원 |",
        f"| D+1 정산 | {d1:,.0f}원 |",
        f"| D+2 정산 | {d2:,.0f}원 |",
        f"| 주문가능 | {orderable:,.0f}원 |",
        f"",
        f"## 💼 종목별 현황",
        f"",
    ]

    for h in holdings:
        code    = h["code"]
        name    = h["name"]
        qty     = h.get("qty", 0)
        avg     = h.get("avg_price", 0)
        cur     = h.get("current_price", 0)
        pnl     = h.get("pnl", 0) or ((cur - avg) * qty)
        pnl_pct = h.get("pnl_pct", 0.0)
        ohlcv   = daily_data.get(code) or {}
        strat   = strategies.get(code, {})

        chg_pct   = ohlcv.get("change_pct", 0.0)
        hi        = ohlcv.get("high", 0)
        lo        = ohlcv.get("low", 0)
        vol       = ohlcv.get("volume", 0)
        vol_ratio = ohlcv.get("vol_ratio", 1.0)
        candle    = strat.get("candle_note", "")
        vol_alert = strat.get("vol_alert", "")
        tomorrow  = strat.get("tomorrow", "")

        md.extend([
            f"### {'🔴' if pnl_pct < 0 else '🟢'} {name} ({code})",
            f"",
            f"| 항목 | 값 |",
            f"|------|-----|",
            f"| 현재가 | {cur:,.0f}원 |",
            f"| 평균단가 | {avg:,.0f}원 |",
            f"| 보유수량 | {qty}주 |",
            f"| 평가손익 | {pnl:+,.0f}원 ({pnl_pct:+.2f}%) |",
            f"| 당일 등락 | {chg_pct:+.2f}% |",
            f"| 고가 / 저가 | {hi:,.0f} / {lo:,.0f}원 |",
            f"| 거래량 | {vol:,}주 (5일 평균 대비 {vol_ratio:.1f}배) |",
            f"",
        ])

        if candle:
            md.append(f"- **캔들**: {candle}")
        if vol_alert:
            md.append(f"- **거래량**: {vol_alert}")
        if tomorrow:
            md.append(f"- **내일 전략**: {tomorrow}")
        md.append("")

        # 메모 섹션 (사용자가 직접 작성)
        md.extend([
            f"#### 📝 메모 (직접 작성)",
            f"",
            f"> (오늘 특이사항, 매매 이유 등 기록)",
            f"",
            f"---",
            f"",
        ])

    md.extend([
        f"## 🗓️ 내일 주요 체크리스트",
        f"",
        f"- [ ] 프리마켓 / 미국 시장 마감 확인",
        f"- [ ] 보유 종목 손절가 재확인",
        f"- [ ] 모닝 브리핑 수신 (08:30) 확인",
        f"",
        f"---",
        f"*자동 생성 | AI 주식 매매 시스템*",
    ])

    path.write_text("\n".join(md), encoding="utf-8")
    return path


# ── 유틸리티 ──────────────────────────────────────────────────────────────────

def _safe_float(val, default=0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=0) -> int:
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def _parse_holdings(balance_raw) -> list:
    if isinstance(balance_raw, list):
        raw_list = balance_raw
    elif isinstance(balance_raw, dict):
        raw_list = balance_raw.get("output1") or balance_raw.get("holdings") or []
    else:
        return []

    result = []
    for item in raw_list:
        if not item:
            continue
        code = str(item.get("pdno") or item.get("code") or "").strip()
        if not code:
            continue
        qty = _safe_int(item.get("hldg_qty") or item.get("qty"))
        if qty == 0:
            continue
        avg = _safe_float(item.get("pchs_avg_pric") or item.get("avg_price"))
        cur = _safe_float(item.get("prpr") or item.get("current_price"))
        pnl_pct_raw = item.get("evlu_pfls_rt") or item.get("pnl_pct")
        try:
            pnl_pct = float(str(pnl_pct_raw).replace(",", "").strip()) if pnl_pct_raw else (
                (cur - avg) / avg * 100 if avg else 0.0
            )
        except (ValueError, TypeError):
            pnl_pct = 0.0

        pnl_raw = item.get("evlu_pfls_amt") or item.get("pnl")
        pnl = _safe_float(pnl_raw) if pnl_raw else (cur - avg) * qty

        result.append({
            "code":          code,
            "name":          str(item.get("prdt_name") or item.get("name") or code),
            "qty":           qty,
            "avg_price":     avg,
            "current_price": cur,
            "pnl_pct":       pnl_pct,
            "pnl":           pnl,
        })
    return result


def _parse_cash(balance_raw) -> dict:
    if not isinstance(balance_raw, dict):
        return {"deposit": 0, "orderable": 0, "d1": 0, "d2": 0,
                "stock_eval": 0, "total_eval": 0, "net_asset": 0,
                "prev_net_asset": 0, "asset_chg": 0,
                "today_buy": 0, "today_sell": 0, "today_fee": 0,
                "eval_pnl": 0}
    output2 = balance_raw.get("output2", [])
    row     = output2[0] if isinstance(output2, list) and output2 else (output2 or {})

    deposit   = _safe_float(row.get("dnca_tot_amt", 0))           # 예수금총금액
    d1        = _safe_float(row.get("nxdy_excc_amt", 0))          # D+1 익일정산금액
    d2        = _safe_float(row.get("prvs_rcdl_excc_amt", 0))     # D+2 가수도정산금액
    orderable = d2    # 주문가능 ≈ D+2 (잔고조회 API에 ord_psbl_cash 미제공)

    stock_eval     = _safe_float(row.get("scts_evlu_amt", 0))         # 유가평가금액
    total_eval     = _safe_float(row.get("tot_evlu_amt", 0))          # 총평가금액
    net_asset      = _safe_float(row.get("nass_amt", 0))              # 순자산금액
    prev_net_asset = _safe_float(row.get("bfdy_tot_asst_evlu_amt", 0))  # 전일총자산평가금액
    asset_chg      = _safe_float(row.get("asst_icdc_amt", 0))         # 자산증감액 (API 직접 제공)

    today_buy  = _safe_float(row.get("thdt_buy_amt", 0))          # 금일매수금액
    today_sell = _safe_float(row.get("thdt_sll_amt", 0))          # 금일매도금액
    today_fee  = _safe_float(row.get("thdt_tlex_amt", 0))         # 금일제비용금액
    eval_pnl   = _safe_float(row.get("evlu_pfls_smtl_amt", 0))    # 평가손익합계금액

    return {
        "deposit": deposit,
        "orderable": orderable,
        "d1": d1,
        "d2": d2,
        "stock_eval": stock_eval,
        "total_eval": total_eval,
        "net_asset": net_asset,
        "prev_net_asset": prev_net_asset,
        "asset_chg": asset_chg,
        "today_buy": today_buy,
        "today_sell": today_sell,
        "today_fee": today_fee,
        "eval_pnl": eval_pnl,
    }


def _save_report_fallback(report: str, today_date: str):
    fallback_dir = _ROOT / "reports"
    fallback_dir.mkdir(exist_ok=True)
    fname = fallback_dir / f"closing_{today_date}.txt"
    fname.write_text(report, encoding="utf-8")
    print(f"[저장] 보고서 저장됨: {fname}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="장마감 결산 브리핑")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 출력만")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
