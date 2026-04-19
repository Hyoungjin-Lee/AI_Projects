"""
morning_report.py — 매일 아침 주식 브리핑 메인 스크립트

실행 흐름:
  1. KIS API → 보유 주식 잔고 조회
  2. KIS API → 보유 종목 현재가 + 기술적 분석
  3. 외부 데이터 → 미국 시장, 환율, 뉴스, 커뮤니티
  4. 보고서 생성 → 텔레그램 전송

실행 방법:
  python3 morning_report.py           # 전체 실행
  python3 morning_report.py --dry-run # 텔레그램 전송 없이 보고서만 출력
"""

import argparse
import json
import os
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

# 거래일 여부 체크용 (공휴일은 별도 관리 없이 KIS 응답으로 감지)
_WEEKDAYS = {0, 1, 2, 3, 4}   # 월~금


def is_trading_day() -> bool:
    """오늘이 평일인지 확인 (공휴일은 KIS API 호출 후 빈 데이터로 감지)."""
    return date.today().weekday() in _WEEKDAYS


def run(dry_run: bool = False):
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][datetime.now().weekday()]
    today_str = datetime.now().strftime(f"%Y년 %m월 %d일 ({weekday_kr})")
    now_str   = datetime.now().strftime("%H:%M")

    print(f"[{now_str}] 모닝 브리핑 시작...", file=sys.stderr)

    # ── 거래일 체크 ───────────────────────────────────────────────────────────
    if not is_trading_day():
        print("[브리핑] 오늘은 주말입니다. 종료.", file=sys.stderr)
        return

    # ── 1. KIS 잔고 조회 ──────────────────────────────────────────────────────
    print("[1/4] 보유 잔고 조회 중...", file=sys.stderr)
    client = None
    try:
        from kis_client import KISClient
        client = KISClient()
        balance_raw = client.get_balance()
    except ImportError:
        print("[설정오류] kis_client 모듈을 찾을 수 없습니다. 경로를 확인하세요.", file=sys.stderr)
        return
    except Exception as e:
        err_msg = str(e)
        if "APP_KEY" in err_msg or "환경변수" in err_msg or "config" in err_msg.lower():
            print(f"[설정오류] .env 파일의 KIS_APP_KEY/KIS_APP_SECRET/KIS_ACCOUNT_NO를 확인하세요: {e}", file=sys.stderr)
            return
        print(f"[오류] KIS 잔고 조회 실패: {e}", file=sys.stderr)
        balance_raw = {"output1": []}

    holdings = _parse_holdings(balance_raw)
    cash_info = _parse_cash(balance_raw)

    # 주문가능현금 별도 조회 (TTTC0869R) — 앱과 일치하는 정확한 값
    try:
        orderable_cash = client.get_orderable_cash()
        cash_info["orderable"] = orderable_cash
    except Exception as e:
        print(f"[경고] 주문가능현금 조회 실패 (D+2로 대체): {e}", file=sys.stderr)

    if not holdings:
        msg = (
            f"📈 {today_str} 모닝 브리핑\n\n"
            "현재 보유 중인 주식이 없습니다.\n"
            "오늘도 좋은 하루 되세요! 💪"
        )
        if not dry_run:
            from telegram_sender import send_report
            send_report(msg, title="")
        else:
            print(msg)
        return

    # ── 2. 종목별 기술적 분석 (일봉 + 주봉) ─────────────────────────────────
    print("[2/4] 종목 기술적 분석 중...", file=sys.stderr)
    analysis_results = {}
    weekly_results = {}
    for h in holdings:
        code = h["code"]
        name = h["name"]
        try:
            _fetch_daily_if_needed(client, code)
            import analyze_swing as _swing
            swing = _swing.analyze(code, days=60)
            analysis_results[code] = swing
            print(f"  ✅ {name}({code}) 일봉 분석 완료", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️  {name}({code}) 일봉 분석 실패: {e}", file=sys.stderr)
            analysis_results[code] = None

        try:
            _fetch_weekly_if_needed(client, code)
            weekly_results[code] = _analyze_weekly(code)
            print(f"  ✅ {name}({code}) 주봉 분석 완료", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️  {name}({code}) 주봉 분석 실패: {e}", file=sys.stderr)
            weekly_results[code] = None

    # ── 3. 외부 데이터 수집 ───────────────────────────────────────────────────
    print("[3/4] 외부 데이터 수집 중...", file=sys.stderr)
    try:
        from data_fetcher import fetch_all
        ext_data = fetch_all(holdings)
    except Exception as e:
        print(f"[오류] 외부 데이터 수집 실패: {e}", file=sys.stderr)
        ext_data = {"us_market": {}, "fx": {}, "fear_greed": {}, "stocks": {}}

    # ── 4. 보고서 생성 ────────────────────────────────────────────────────────
    print("[4/4] 보고서 생성 중...", file=sys.stderr)
    report = _build_report(today_str, holdings, analysis_results, weekly_results, cash_info, ext_data, balance_raw)

    # ── state 기록 ───────────────────────────────────────────────────────────
    try:
        state = StateManager()
        state.update("market", {
            "us_sentiment": ext_data.get("us_market", {}).get("sp500_chg", None),
            "usd_krw":      ext_data.get("fx", {}).get("usd_krw"),
            "fear_greed":   ext_data.get("fear_greed", {}).get("score"),
        }, caller="morning_report")
        holdings_signals = {
            h["code"]: {
                "signal":  (analysis_results.get(h["code"]) or {}).get("verdict", "WATCH"),
                "pnl_pct": h.get("pnl_pct", 0.0),
            }
            for h in holdings
        }
        state.update("holdings", holdings_signals, caller="morning_report")
        print("[state] 모닝 브리핑 상태 기록 완료", file=sys.stderr)
    except Exception as e:
        print(f"[state] 기록 실패 (무시): {e}", file=sys.stderr)

    if dry_run:
        print("\n" + "=" * 50)
        print(report)
        print("=" * 50)
        print("\n[DRY-RUN] 텔레그램 전송 생략")
    else:
        from telegram_sender import send_report
        ok = send_report(report)
        if ok:
            print("[완료] 텔레그램 전송 성공 ✅", file=sys.stderr)
        else:
            print("[오류] 텔레그램 전송 실패 ❌", file=sys.stderr)
            # 실패 시 로컬 파일로 저장
            _save_report_fallback(report, today_str)


# ── 보고서 빌더 ───────────────────────────────────────────────────────────────

def _build_report(today_str, holdings, analysis, weekly, cash_info, ext_data, balance_raw) -> str:
    lines = []

    # ── 헤더 ──────────────────────────────────────────────────────────────────
    lines.append(f"📈 {today_str} 모닝 브리핑")
    lines.append("=" * 28)

    # ── 글로벌 시장 ───────────────────────────────────────────────────────────
    us = ext_data.get("us_market", {})
    fx = ext_data.get("fx", {})
    fg = ext_data.get("fear_greed", {})

    lines.append("\n🌏 글로벌 시장")

    sp500  = us.get("sp500")
    nasdaq = us.get("nasdaq")
    dow    = us.get("dow")
    if sp500:
        sp_chg = us.get("sp500_chg", "")
        lines.append(f"  S&P500  {sp500:,.0f}  {sp_chg}")
    if nasdaq:
        nq_chg = us.get("nasdaq_chg", "")
        lines.append(f"  나스닥  {nasdaq:,.0f}  {nq_chg}")
    if dow:
        dj_chg = us.get("dow_chg", "")
        lines.append(f"  다우    {dow:,.0f}  {dj_chg}")

    usd = fx.get("usd_krw")
    usd_chg = fx.get("usd_krw_chg_pct", "")
    if usd:
        lines.append(f"  달러/원 {usd:,.1f}원  {usd_chg}")

    if fg.get("score") is not None:
        fg_emoji = _fg_emoji(fg["score"])
        lines.append(f"  공포탐욕 {fg_emoji} {fg['score']} ({fg['rating']})")

    # ── 보유 종목 현황 ────────────────────────────────────────────────────────
    lines.append("\n💼 보유 종목 현황")

    total_eval   = 0
    total_profit = 0

    for h in holdings:
        code    = h["code"]
        name    = h["name"]
        qty     = h.get("qty", 0)
        avg     = h.get("avg_price", 0)
        cur     = h.get("current_price", 0)
        pnl     = h.get("pnl", 0)
        pnl_pct = h.get("pnl_pct", 0.0)
        eval_amt = cur * qty if cur and qty else 0

        total_eval   += eval_amt
        total_profit += pnl if pnl else 0

        pnl_emoji = "🔴" if pnl_pct < 0 else "🟢"
        lines.append(
            f"\n  {pnl_emoji} {name}({code})"
            f"\n    현재가: {cur:,.0f}원  |  수량: {qty}주"
            f"\n    평균단가: {avg:,.0f}원  |  평가손익: {pnl:+,.0f}원 ({pnl_pct:+.2f}%)"
        )

        # 기술적 분석 시그널 (일봉)
        result = analysis.get(code)
        if result:
            verdict    = result.get("verdict", "WATCH")
            confidence = result.get("confidence", 0.0)
            stop_loss  = result.get("stop_loss")
            target     = result.get("target_price")
            v_emoji = {"BUY": "📗", "HOLD": "📘", "SELL": "📕", "WATCH": "📒"}.get(verdict, "📒")
            lines.append(f"    일봉: {v_emoji} {verdict} (확신도 {confidence:.0%})")
            if stop_loss and target:
                lines.append(f"    손절: {stop_loss:,.0f}  |  목표: {target:,.0f}")
            sigs = result.get("key_signals", [])[:2]
            for s in sigs:
                lines.append(f"    • {s['name']}: {s['value']} — {s['interpretation']}")

        # 주봉 분석
        w = weekly.get(code) if weekly else None
        if w:
            w_trend  = w.get("trend", "중립")
            w_rsi    = w.get("rsi")
            w_signal = w.get("signal", "")
            # 일봉·주봉 방향 일치 여부
            daily_verdict = (result or {}).get("verdict", "WATCH")
            if daily_verdict in ("BUY",) and w_trend == "상승":
                align = "✅ 일·주봉 상승 일치 — 신뢰도 높음"
            elif daily_verdict in ("SELL",) and w_trend == "하락":
                align = "✅ 일·주봉 하락 일치 — 손절 적극 검토"
            elif w_trend == "하락" and daily_verdict == "BUY":
                align = "⚠️ 주봉 하락 중 일봉 반등 — 단기 반등 주의"
            elif w_trend == "상승" and daily_verdict == "SELL":
                align = "⚠️ 주봉 상승 중 일봉 조정 — 중기 추세 유지 확인"
            else:
                align = f"주봉 추세: {w_trend}"
            rsi_txt = f" | 주봉RSI {w_rsi:.1f}" if w_rsi else ""
            lines.append(f"    주봉: {align}{rsi_txt}")

        # 뉴스 헤드라인
        stock_ext = ext_data.get("stocks", {}).get(code, {})
        news_list = stock_ext.get("news", [])[:2]
        sentiment = stock_ext.get("sentiment", {})
        if news_list:
            sent_txt = sentiment.get("sentiment", "")
            lines.append(f"    📰 커뮤니티: {sent_txt}")
            for n in news_list:
                lines.append(f"      - {n['title'][:35]}...")

    # ── 포트폴리오 합계 ───────────────────────────────────────────────────────
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

    # cash_avail: 추가매수 추천에 사용
    cash_avail  = orderable
    total_asset = net_asset if net_asset > 0 else (total_eval + deposit)

    # 표시용 수치 정리
    display_net   = net_asset if net_asset > 0 else (total_eval + deposit)
    display_stock = stock_eval_api if stock_eval_api > 0 else total_eval
    if asset_chg == 0 and prev_net_asset > 0:
        asset_chg = display_net - prev_net_asset
    asset_chg_pct = (asset_chg / prev_net_asset * 100) if prev_net_asset > 0 else 0.0
    display_pnl   = eval_pnl if eval_pnl != 0 else total_profit
    total_invest  = sum(h.get("avg_price", 0) * h.get("qty", 0) for h in holdings)
    invest_return = (display_pnl / total_invest * 100) if total_invest > 0 else 0.0

    pnl_emoji   = "🔴" if display_pnl < 0 else "🟢"
    asset_emoji = "🔴" if asset_chg < 0 else "🟢"

    if total_eval > 0:
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

    # ── 추가 매수 비중 추천 ───────────────────────────────────────────────────
    if cash_avail > 0 and total_asset > 0:
        buy_recs = _build_buy_recommendation(holdings, analysis, cash_avail, total_asset)
        if buy_recs:
            lines.append("\n💰 추가 매수 비중 추천")
            lines.extend(buy_recs)

    # ── 오늘의 대응 전략 ──────────────────────────────────────────────────────
    lines.append("\n🎯 오늘의 대응 포인트")
    action_lines = _build_action_points(holdings, analysis, us, fx)
    lines.extend(action_lines)

    # ── 푸터 ──────────────────────────────────────────────────────────────────
    lines.append(f"\n⏰ 생성: {datetime.now().strftime('%H:%M')}")
    lines.append("※ AI 분석 참고용. 투자 책임은 본인에게 있습니다.")

    return "\n".join(lines)


def _build_action_points(holdings, analysis, us_market, fx) -> list:
    """오늘의 대응 포인트 자동 생성."""
    points = []

    # 미국 시장 방향
    sp_chg_str = us_market.get("sp500_chg", "")
    if sp_chg_str:
        if "+" in str(sp_chg_str):
            points.append("  • 미국 증시 강세 → 코스피 긍정적 출발 예상")
        elif "-" in str(sp_chg_str):
            points.append("  • 미국 증시 약세 → 코스피 약세 출발 가능, 장 초반 주의")

    # 환율 영향
    usd = fx.get("usd_krw")
    usd_chg = fx.get("usd_krw_chg")
    if usd and usd_chg:
        if usd_chg > 10:
            points.append(f"  • 달러 강세(+{usd_chg:.0f}원) → 외국인 매도 압력 가능")
        elif usd_chg < -10:
            points.append(f"  • 달러 약세({usd_chg:.0f}원) → 외국인 매수 우호적 환경")

    # 종목별 액션
    for h in holdings:
        code = h["code"]
        name = h["name"]
        result = analysis.get(code)
        if not result:
            continue

        verdict = result.get("verdict", "WATCH")
        pnl_pct = h.get("pnl_pct", 0.0)
        stop_loss = result.get("stop_loss")
        cur = h.get("current_price", 0)

        if verdict == "SELL":
            points.append(f"  ⚠️  {name}: 매도 시그널 — 청산 검토 필요")
        elif verdict == "BUY" and pnl_pct < -3:
            points.append(f"  📗 {name}: 매수 시그널이나 현재 손실 중 — 추가 분석 필요")
        elif stop_loss and cur and cur < stop_loss * 1.02:
            points.append(f"  🚨 {name}: 손절가({stop_loss:,.0f}) 근접 — 주의")

    if not points:
        points.append("  • 특별한 액션 포인트 없음. 보유 유지 관찰.")

    return points


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _safe_float(val, default=0.0) -> float:
    """KIS는 숫자를 문자열로 반환 — 안전하게 float 변환."""
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
    """KIS 잔고 JSON을 표준 형식으로 변환. KIS는 모든 숫자를 문자열로 반환."""
    if isinstance(balance_raw, list):
        raw_list = balance_raw
    elif isinstance(balance_raw, dict):
        raw_list = (
            balance_raw.get("holdings") or
            balance_raw.get("output1") or
            balance_raw.get("output") or
            []
        )
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
        pnl = _safe_float(item.get("evlu_pfls_amt") or item.get("pnl"))

        # evlu_pfls_rt는 이미 백분율 문자열 (예: "2.35" → 2.35%)
        pnl_pct_raw = item.get("evlu_pfls_rt") or item.get("pnl_pct")
        if pnl_pct_raw is not None and pnl_pct_raw != "":
            try:
                pnl_pct = float(str(pnl_pct_raw).replace(",", "").strip())
            except (ValueError, TypeError):
                pnl_pct = (cur - avg) / avg * 100 if avg else 0.0
        else:
            pnl_pct = (cur - avg) / avg * 100 if avg else 0.0

        result.append({
            "code":          code,
            "name":          str(item.get("prdt_name") or item.get("name") or code),
            "qty":           qty,
            "avg_price":     avg,
            "current_price": cur,
            "pnl":           pnl,
            "pnl_pct":       pnl_pct,
        })

    return result


def _parse_cash(balance_raw: dict) -> dict:
    """KIS 잔고 응답에서 예수금·자산 상세정보 추출 (closing_report와 동일)."""
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

    stock_eval     = _safe_float(row.get("scts_evlu_amt", 0))          # 유가평가금액
    total_eval     = _safe_float(row.get("tot_evlu_amt", 0))           # 총평가금액
    net_asset      = _safe_float(row.get("nass_amt", 0))               # 순자산금액
    prev_net_asset = _safe_float(row.get("bfdy_tot_asst_evlu_amt", 0)) # 전일총자산평가금액
    asset_chg      = _safe_float(row.get("asst_icdc_amt", 0))          # 자산증감액

    today_buy  = _safe_float(row.get("thdt_buy_amt", 0))          # 금일매수금액
    today_sell = _safe_float(row.get("thdt_sll_amt", 0))          # 금일매도금액
    today_fee  = _safe_float(row.get("thdt_tlex_amt", 0))         # 금일제비용금액
    eval_pnl   = _safe_float(row.get("evlu_pfls_smtl_amt", 0))    # 평가손익합계금액

    return {
        "deposit": deposit, "orderable": orderable,
        "d1": d1, "d2": d2,
        "stock_eval": stock_eval, "total_eval": total_eval,
        "net_asset": net_asset, "prev_net_asset": prev_net_asset,
        "asset_chg": asset_chg,
        "today_buy": today_buy, "today_sell": today_sell, "today_fee": today_fee,
        "eval_pnl": eval_pnl,
    }


def _build_buy_recommendation(holdings, analysis, cash_avail, total_asset) -> list:
    """
    현금 15~20% 유지 원칙 하에 BUY 시그널 종목에 추가매수 비중 추천.
    - 리저브 현금: 총자산의 15%
    - 투자 가능 현금: cash_avail - reserve
    - BUY 종목의 confidence 가중치로 배분
    """
    CASH_RESERVE_RATIO = 0.15   # 현금 유지 비율 15%
    reserve = total_asset * CASH_RESERVE_RATIO
    investable = max(0, cash_avail - reserve)

    lines = []
    lines.append(f"  (현금 유지 목표: 총자산의 15% = {reserve:,.0f}원)")

    if investable <= 10_000:
        lines.append(f"  ⚠️ 주문가능금액({cash_avail:,.0f}원)이 유보금 수준 — 추가 매수 비추천")
        return lines

    # BUY 시그널 종목 추려서 confidence 기반 배분
    buy_candidates = []
    for h in holdings:
        code = h["code"]
        result = analysis.get(code)
        if not result:
            continue
        verdict    = result.get("verdict", "WATCH")
        confidence = result.get("confidence", 0.0)
        pnl_pct    = h.get("pnl_pct", 0.0)
        cur        = h.get("current_price", 0)
        if verdict == "BUY" and cur > 0:
            # 이미 큰 손실 중이면 confidence 패널티
            adj_conf = confidence * (0.7 if pnl_pct < -5 else 1.0)
            buy_candidates.append({
                "code": code, "name": h["name"],
                "confidence": adj_conf, "cur": cur, "pnl_pct": pnl_pct
            })

    if not buy_candidates:
        lines.append(f"  현재 BUY 시그널 종목 없음 — 현금 {cash_avail:,.0f}원 유지 권장")
        return lines

    total_conf = sum(c["confidence"] for c in buy_candidates)
    lines.append(f"  투자 가능 금액: {investable:,.0f}원 (총 주문가능 {cash_avail:,.0f}원 - 유보 {reserve:,.0f}원)")
    lines.append("")

    for c in buy_candidates:
        weight   = c["confidence"] / total_conf if total_conf > 0 else 1 / len(buy_candidates)
        amt      = investable * weight
        shares   = int(amt // c["cur"]) if c["cur"] > 0 else 0
        pnl_note = f" (현재 {c['pnl_pct']:+.1f}%)" if c["pnl_pct"] else ""
        if shares > 0:
            lines.append(f"  📗 {c['name']}: {amt:,.0f}원 → 약 {shares}주 추가 매수 추천{pnl_note}")
        else:
            lines.append(f"  📗 {c['name']}: {amt:,.0f}원 권장 (1주 미만 — 매수 보류){pnl_note}")

    return lines


def _fetch_weekly_if_needed(client, code: str, weeks: int = 26):
    """주봉 데이터 수집 (26주 = 약 6개월). 3일 이내 캐시 있으면 재사용."""
    import glob as _glob, os as _os
    raw_dir = _ROOT / "data" / "raw"
    existing = _glob.glob(str(raw_dir / f"{code}_weekly_*.json"))
    if existing:
        newest = max(existing, key=_os.path.getmtime)
        age_days = (datetime.now().timestamp() - _os.path.getmtime(newest)) / 86400
        if age_days < 3:
            return

    try:
        rows = client.get_weekly_chart(code, weeks=weeks)
        if not rows:
            raise ValueError(f"{code} 주봉 데이터 없음")
        raw_dir.mkdir(parents=True, exist_ok=True)
        fname = raw_dir / f"{code}_weekly_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        import json as _json
        fname.write_text(_json.dumps({"output2": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [주봉] {code} 데이터 수집 완료 ({len(rows)}건)", file=sys.stderr)
    except AttributeError:
        # KIS client에 get_weekly_chart 없으면 일봉으로 주봉 합성
        _synthesize_weekly_from_daily(code, weeks)
    except Exception as e:
        print(f"  [주봉] {code} 수집 실패: {e}", file=sys.stderr)
        raise


def _synthesize_weekly_from_daily(code: str, weeks: int = 26):
    """일봉 데이터에서 주봉을 합성해서 저장."""
    import glob as _glob, json as _json, os as _os
    import pandas as pd

    raw_dir = _ROOT / "data" / "raw"
    daily_files = sorted(_glob.glob(str(raw_dir / f"{code}_daily_*.json")), reverse=True)
    if not daily_files:
        raise FileNotFoundError(f"{code} 일봉 캐시 없음 — 주봉 합성 불가")

    with open(daily_files[0], encoding="utf-8") as f:
        data = _json.load(f)
    rows = data.get("output2") or data.get("output") or []
    if not rows:
        raise ValueError(f"{code} 일봉 데이터 비어 있음")

    df = pd.DataFrame(rows)
    # KIS 컬럼명 정규화
    col_map = {
        "stck_bsop_date": "date", "stck_oprc": "open", "stck_hgpr": "high",
        "stck_lwpr": "low",  "stck_clpr": "close", "acml_vol": "volume",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df = df.sort_values("date")
        df.set_index("date", inplace=True)

    weekly = df.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(how="all").tail(weeks)

    weekly_rows = []
    for dt, row in weekly.iterrows():
        weekly_rows.append({
            "stck_bsop_date": dt.strftime("%Y%m%d"),
            "stck_oprc": str(int(row.get("open", 0))),
            "stck_hgpr": str(int(row.get("high", 0))),
            "stck_lwpr": str(int(row.get("low", 0))),
            "stck_clpr": str(int(row.get("close", 0))),
            "acml_vol":  str(int(row.get("volume", 0))),
        })

    fname = raw_dir / f"{code}_weekly_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    fname.write_text(_json.dumps({"output2": weekly_rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [주봉] {code} 일봉→주봉 합성 완료 ({len(weekly_rows)}주)", file=sys.stderr)


def _analyze_weekly(code: str) -> dict:
    """주봉 데이터로 중기 추세 분석 (SMA5/10, RSI14)."""
    import glob as _glob, json as _json, os as _os
    import pandas as pd
    import numpy as np

    raw_dir = _ROOT / "data" / "raw"
    files = sorted(_glob.glob(str(raw_dir / f"{code}_weekly_*.json")), reverse=True)
    if not files:
        raise FileNotFoundError(f"{code} 주봉 캐시 없음")

    with open(files[0], encoding="utf-8") as f:
        data = _json.load(f)
    rows = data.get("output2") or data.get("output") or []
    if not rows:
        raise ValueError("주봉 데이터 비어 있음")

    df = pd.DataFrame(rows)
    col_map = {
        "stck_bsop_date": "date", "stck_oprc": "open", "stck_hgpr": "high",
        "stck_lwpr": "low", "stck_clpr": "close", "acml_vol": "volume",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
    df["close"] = pd.to_numeric(df.get("close", df.get("stck_clpr")), errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("date" if "date" in df.columns else df.columns[0])

    close = df["close"]
    sma5  = close.rolling(5).mean().iloc[-1]
    sma10 = close.rolling(10).mean().iloc[-1]
    cur   = close.iloc[-1]

    # RSI(14) — 주봉 기준
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = (100 - 100 / (1 + rs)).iloc[-1]

    # 추세 판단
    if cur > sma5 > sma10:
        trend = "상승"
    elif cur < sma5 < sma10:
        trend = "하락"
    else:
        trend = "중립"

    signal = ""
    if rsi > 70:
        signal = "주봉 과매수"
    elif rsi < 30:
        signal = "주봉 과매도"

    return {
        "trend":  trend,
        "rsi":    round(float(rsi), 1) if not np.isnan(rsi) else None,
        "sma5":   round(float(sma5), 0) if not np.isnan(sma5) else None,
        "sma10":  round(float(sma10), 0) if not np.isnan(sma10) else None,
        "signal": signal,
    }


def _fetch_daily_if_needed(client, code: str, days: int = 60):
    """오늘 캐시가 없으면 KIS API로 일봉 수집."""
    import glob
    today = datetime.now().strftime("%Y%m%d")
    pattern = str(_ROOT / "data" / "raw" / f"{code}_daily_{today}*.json")
    if glob.glob(pattern):
        return   # 이미 오늘 데이터 있음

    # 어제 데이터도 확인 (오전 일찍 실행 시 오늘 데이터가 없을 수 있음)
    import glob as _glob
    any_pattern = str(_ROOT / "data" / "raw" / f"{code}_daily_*.json")
    existing = _glob.glob(any_pattern)
    if existing:
        # 최근 파일이 3일 이내면 재사용
        import os
        newest = max(existing, key=os.path.getmtime)
        age_days = (datetime.now().timestamp() - os.path.getmtime(newest)) / 86400
        if age_days < 3:
            return

    try:
        rows = client.get_daily_chart(code, days=days)
        if rows:
            # data/raw/에 파일로 저장 (analyze_swing이 이 파일을 읽음)
            raw_dir = _ROOT / "data" / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            fname = raw_dir / f"{code}_daily_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            import json as _json
            fname.write_text(_json.dumps({"output2": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [일봉] {code} 데이터 수집 및 저장 완료 ({len(rows)}건)", file=sys.stderr)
        else:
            raise ValueError(f"{code} 일봉 데이터가 비어 있습니다 (공휴일?)")
    except Exception as e:
        print(f"  [일봉] {code} 수집 실패 (분석 건너뜀): {e}", file=sys.stderr)
        raise  # 상위에서 analysis_results[code] = None 처리됨


def _fg_emoji(score: float) -> str:
    if score >= 75:   return "🤑"
    if score >= 55:   return "😊"
    if score >= 45:   return "😐"
    if score >= 25:   return "😨"
    return "😱"


def _save_report_fallback(report: str, today_str: str):
    """텔레그램 전송 실패 시 로컬 파일 저장."""
    report_dir = _ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    fname = report_dir / f"morning_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    fname.write_text(report, encoding="utf-8")
    print(f"[저장] 보고서 저장됨: {fname}", file=sys.stderr)


# ── 진입점 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="주식 모닝 브리핑")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 보고서 출력만")
    args = parser.parse_args()

    run(dry_run=args.dry_run)
