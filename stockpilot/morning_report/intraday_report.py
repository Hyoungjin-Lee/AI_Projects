"""
intraday_report.py — 9시 10분 장초기 분봉 브리핑

실행 흐름:
  1. KIS API → 보유 잔고 조회
  2. KIS API → 종목별 1분봉 수집 (장 시작 후 ~10분)
  3. 장초기 분석: 갭, VWAP, 초기 거래량, 방향성
  4. 텔레그램으로 장초기 대응 전략 전송

실행 방법:
  python3 intraday_report.py           # 전체 실행
  python3 intraday_report.py --dry-run # 텔레그램 전송 없이 출력만
"""

import argparse
import sys
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from keychain_manager import inject_to_env
inject_to_env()
from state_manager import StateManager

_WEEKDAYS = {0, 1, 2, 3, 4}


def run(dry_run: bool = False):
    now_str = datetime.now().strftime("%H:%M")
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][datetime.now().weekday()]
    today_str = datetime.now().strftime(f"%Y년 %m월 %d일 ({weekday_kr})")

    print(f"[{now_str}] 장초기 브리핑 시작...", file=sys.stderr)

    if date.today().weekday() not in _WEEKDAYS:
        print("[브리핑] 오늘은 주말입니다. 종료.", file=sys.stderr)
        return

    # ── 1. 잔고 조회 ──────────────────────────────────────────────────────────
    print("[1/3] 보유 잔고 조회 중...", file=sys.stderr)
    try:
        from kis_client import KISClient
        client = KISClient()
        balance_raw = client.get_balance()
    except Exception as e:
        print(f"[오류] KIS 잔고 조회 실패: {e}", file=sys.stderr)
        return

    holdings = _parse_holdings(balance_raw)
    cash_info = _parse_cash(balance_raw)

    # 주문가능현금 별도 조회
    try:
        cash_info["orderable"] = client.get_orderable_cash()
    except Exception as e:
        print(f"[경고] 주문가능현금 조회 실패 (D+2로 대체): {e}", file=sys.stderr)

    if not holdings:
        print("[브리핑] 보유 종목 없음. 종료.", file=sys.stderr)
        return

    # ── 2. 분봉 수집 + 장초기 분석 ───────────────────────────────────────────
    print(f"[2/3] 종목 {len(holdings)}개 분봉 수집 중...", file=sys.stderr)
    intraday_results = {}
    for h in holdings:
        code = h["code"]
        name = h["name"]
        try:
            bars = client.get_minute_chart(code, hhmm="091000")
            result = _analyze_intraday(bars, h, client=client, code=code)
            intraday_results[code] = result
            print(f"  ✅ {name}({code}) 분봉 분석 완료", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️  {name}({code}) 분봉 분석 실패: {e}", file=sys.stderr)
            intraday_results[code] = None

    # ── state 기록 ────────────────────────────────────────────────────────────
    try:
        state = StateManager()
        # 하락 출발 종목 알림 기록
        drop_alerts = [
            h["name"] for h in holdings
            if (intraday_results.get(h["code"]) or {}).get("direction") == "하락출발"
        ]
        if drop_alerts:
            state.set_alert("intraday", f"하락출발: {', '.join(drop_alerts)}", caller="intraday_report")
        # 거래량 급증 종목 기록
        for h in holdings:
            r = intraday_results.get(h["code"]) or {}
            if r.get("vol_bars", 0) > 0:
                pass  # vol_ratio는 분봉 집계라 별도 처리
        print("[state] 장초기 상태 기록 완료", file=sys.stderr)
    except Exception as e:
        print(f"[state] 기록 실패 (무시): {e}", file=sys.stderr)

    # ── 3. 보고서 생성 + 전송 ────────────────────────────────────────────────
    print("[3/3] 장초기 보고서 생성 중...", file=sys.stderr)
    report = _build_intraday_report(today_str, holdings, intraday_results, cash_info)

    if dry_run:
        print("\n" + "=" * 50)
        print(report)
        print("=" * 50)
        print("\n[DRY-RUN] 텔레그램 전송 생략")
    else:
        from telegram_sender import send_report
        ok = send_report(report, title="📊 장초기 브리핑")
        if ok:
            print("[완료] 텔레그램 전송 성공 ✅", file=sys.stderr)
        else:
            print("[오류] 텔레그램 전송 실패 ❌", file=sys.stderr)
            # 파일 저장
            report_dir = _ROOT / "reports"
            report_dir.mkdir(exist_ok=True)
            fname = report_dir / f"intraday_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            fname.write_text(report, encoding="utf-8")
            print(f"[저장] {fname}", file=sys.stderr)


def _analyze_intraday(bars: list, holding: dict, client=None, code: str = None) -> dict:
    """
    1분봉 데이터로 장초기 상황 분석.

    반환:
      gap_pct     : 전일 대비 갭 비율 (%)
      direction   : "상승출발" | "하락출발" | "보합출발"
      vwap        : VWAP (거래량 가중 평균가)
      vwap_pos    : "VWAP 위" | "VWAP 아래"
      vol_ratio   : 초기 거래량 강도 (분당 평균 거래량 / 전체 평균)
      action      : 권장 대응
    """
    if not bars:
        return {"direction": "데이터없음", "action": "분봉 데이터 없음 — 수동 확인 필요"}

    import pandas as pd
    df = pd.DataFrame(bars)

    # KIS 컬럼 정규화
    col_map = {
        "stck_cntg_hour": "time",
        "stck_prpr": "close",
        "stck_oprc": "open",
        "stck_hgpr": "high",
        "stck_lwpr": "low",
        "cntg_vol":  "volume",
    }
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("time" if "time" in df.columns else df.columns[0])

    if df.empty:
        return {"direction": "데이터없음", "action": "분봉 파싱 실패 — 수동 확인 필요"}

    # 갭 분석 (첫 봉 시가 vs 전일종가)
    first_open = df["open"].iloc[0] if "open" in df.columns else df["close"].iloc[0]
    avg_price  = holding.get("avg_price", 0)

    # 전일종가: 일봉 API에서 직접 조회 (정확도 우선)
    prev_close = 0
    if client and code:
        try:
            daily = client.get_daily_chart(code, days=5)
            if daily and isinstance(daily, list):
                today_str_compact = datetime.now().strftime("%Y%m%d")
                # 오늘 날짜를 제외한 가장 최근 봉의 종가
                for row in daily:
                    row_date = row.get("stck_bsop_date", "")
                    if row_date and row_date < today_str_compact:
                        prev_close = int(float(row.get("stck_clpr", 0)) or 0)
                        break
                # 오늘 장 중이라 오늘 행이 없을 수도 있으므로 첫 번째도 시도
                if prev_close == 0 and daily:
                    prev_close = int(float(daily[0].get("stck_clpr", 0)) or 0)
        except Exception:
            pass

    # fallback: 일봉 조회 실패 시 분봉 첫 봉 시가 근사 사용
    if not prev_close:
        prev_close = first_open

    gap_pct = (first_open - prev_close) / prev_close * 100 if prev_close else 0

    if gap_pct > 1.0:
        direction = "상승출발"
    elif gap_pct < -1.0:
        direction = "하락출발"
    else:
        direction = "보합출발"

    # VWAP 계산
    if "volume" in df.columns and df["volume"].sum() > 0:
        tp = (df["high"] + df["low"] + df["close"]) / 3 if all(c in df.columns for c in ["high", "low", "close"]) else df["close"]
        vwap = (tp * df["volume"]).sum() / df["volume"].sum()
        last_close = df["close"].iloc[-1]
        vwap_pos = "VWAP 위" if last_close > vwap else "VWAP 아래"
    else:
        vwap = None
        vwap_pos = "VWAP 계산 불가"

    # 거래량 강도 (초기 10분 vs 전체 평균)
    vol_sum = df["volume"].sum() if "volume" in df.columns else 0
    vol_per_bar = vol_sum / len(df) if len(df) > 0 else 0

    # 대응 전략 생성
    pnl_pct = holding.get("pnl_pct", 0.0)
    action = _intraday_action(direction, vwap_pos, gap_pct, pnl_pct, avg_price, first_open)

    return {
        "gap_pct":   round(gap_pct, 2),
        "direction": direction,
        "vwap":      round(float(vwap), 0) if vwap else None,
        "vwap_pos":  vwap_pos,
        "vol_bars":  len(df),
        "first_open": first_open,
        "last_close": df["close"].iloc[-1] if not df.empty else None,
        "action":    action,
    }


def _intraday_action(direction, vwap_pos, gap_pct, pnl_pct, avg_price, first_open) -> str:
    """장초기 상황별 대응 전략."""
    if direction == "상승출발" and vwap_pos == "VWAP 위":
        if gap_pct > 3:
            return "갭 상승 출발 + VWAP 위 → 갭 채움 조정 가능성 주의, 눌림목 확인 후 대응"
        return "상승 출발 + VWAP 위 → 강세 유지 시 보유, 단기 저항선 확인"
    elif direction == "상승출발" and vwap_pos == "VWAP 아래":
        return "갭 상승 출발했으나 VWAP 하회 → 약세 전환 가능성, 관망 추천"
    elif direction == "하락출발" and vwap_pos == "VWAP 아래":
        if pnl_pct < -5:
            return "하락 출발 + VWAP 아래 + 기존 손실 중 → 손절 기준가 재확인 필요"
        return "하락 출발 + VWAP 아래 → 추가 하락 경계, VWAP 회복 여부 모니터링"
    elif direction == "하락출발" and vwap_pos == "VWAP 위":
        return "갭 하락 출발했으나 VWAP 위 → 반등 시도 중, 장 초반 방향 확인 후 대응"
    else:
        return "보합 출발 → 9시 30분까지 방향성 확인 후 대응"


def _build_intraday_report(today_str, holdings, intraday_results, cash_info=None) -> str:
    lines = []
    lines.append(f"📊 {today_str} 장초기 브리핑")
    lines.append(f"⏰ {datetime.now().strftime('%H:%M')} 기준")
    lines.append("=" * 28)

    for h in holdings:
        code    = h["code"]
        name    = h["name"]
        cur     = h.get("current_price", 0)
        pnl_pct = h.get("pnl_pct", 0.0)
        pnl_emoji = "🔴" if pnl_pct < 0 else "🟢"

        result = intraday_results.get(code)
        lines.append(f"\n{pnl_emoji} {name}({code})  현재가 {cur:,.0f}원 ({pnl_pct:+.2f}%)")

        if not result or result.get("direction") == "데이터없음":
            lines.append(f"  ⚠️ 분봉 데이터 없음 — 수동 확인 필요")
            continue

        direction  = result.get("direction", "")
        gap_pct    = result.get("gap_pct", 0)
        vwap       = result.get("vwap")
        vwap_pos   = result.get("vwap_pos", "")
        first_open = result.get("first_open")
        last_close = result.get("last_close")
        action     = result.get("action", "")
        vol_bars   = result.get("vol_bars", 0)

        gap_arrow = "▲" if gap_pct > 0 else ("▼" if gap_pct < 0 else "━")
        lines.append(f"  출발: {direction} {gap_arrow}{abs(gap_pct):.2f}%  (시가 {first_open:,.0f}원)")
        if vwap:
            lines.append(f"  VWAP: {vwap:,.0f}원 ({vwap_pos})")
        if last_close and last_close != first_open:
            chg = (last_close - first_open) / first_open * 100
            lines.append(f"  현재봉: {last_close:,.0f}원 (시가대비 {chg:+.2f}%)")
        lines.append(f"  📌 대응: {action}")

    # ── 예수금 요약 ──────────────────────────────────────────────────────────
    if cash_info:
        deposit   = cash_info.get("deposit", 0)
        orderable = cash_info.get("orderable", 0)
        d1        = cash_info.get("d1", 0)
        net_asset = cash_info.get("net_asset", 0)

        lines.append(f"\n{'=' * 28}")
        lines.append(f"💵 예수금")
        lines.append(f"  예수금(총):   {deposit:>12,.0f}원")
        if d1 > 0:
            lines.append(f"  D+1 정산:     {d1:>12,.0f}원")
        lines.append(f"  주문가능:     {orderable:>12,.0f}원")
        if net_asset > 0:
            lines.append(f"  총평가금액:   {net_asset:>12,.0f}원")

    lines.append(f"\n※ {datetime.now().strftime('%H:%M')} 기준 단기 분석. 투자 책임은 본인에게 있습니다.")
    return "\n".join(lines)


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


def _parse_cash(balance_raw: dict) -> dict:
    """KIS 잔고 응답에서 예수금·자산 상세정보 추출."""
    if not isinstance(balance_raw, dict):
        return {"deposit": 0, "orderable": 0, "d1": 0, "d2": 0, "net_asset": 0}
    output2 = balance_raw.get("output2", [])
    row     = output2[0] if isinstance(output2, list) and output2 else (output2 or {})

    deposit   = _safe_float(row.get("dnca_tot_amt", 0))           # 예수금총금액
    d1        = _safe_float(row.get("nxdy_excc_amt", 0))          # D+1 익일정산금액
    d2        = _safe_float(row.get("prvs_rcdl_excc_amt", 0))     # D+2 가수도정산금액
    orderable = d2

    net_asset      = _safe_float(row.get("nass_amt", 0))               # 순자산금액
    prev_net_asset = _safe_float(row.get("bfdy_tot_asst_evlu_amt", 0)) # 전일총자산

    return {
        "deposit": deposit, "orderable": orderable,
        "d1": d1, "d2": d2,
        "net_asset": net_asset, "prev_net_asset": prev_net_asset,
    }


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
        result.append({
            "code": code,
            "name": str(item.get("prdt_name") or item.get("name") or code),
            "qty": qty, "avg_price": avg, "current_price": cur, "pnl_pct": pnl_pct,
        })
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="장초기 분봉 브리핑")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 출력만")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
