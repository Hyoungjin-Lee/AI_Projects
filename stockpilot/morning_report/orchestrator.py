"""
orchestrator.py — 텔레그램 명령 라우팅 및 실행

명령어:
  /잔고    KIS 잔고 즉시 조회
  /상태    오늘 daily_state 요약
  /발굴    stock_discovery 즉시 실행
  /도움말  명령어 목록

보안:
  - TELEGRAM_CHAT_ID 일치 여부 확인 → 본인만 명령 가능
  - 실주문 명령 없음 (Phase 2로 분리)
"""

import sys
import os
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

from keychain_manager import inject_to_env
inject_to_env()
from state_manager import StateManager
from telegram_sender import send_text


def handle_command(text: str, chat_id: str) -> bool:
    """
    텔레그램 명령 처리.
    chat_id 검증 후 명령 라우팅.
    반환: 처리 성공 여부
    """
    allowed_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if str(chat_id) != str(allowed_chat_id):
        print(f"[bot] 허용되지 않은 chat_id: {chat_id}", file=sys.stderr)
        return False

    text = text.strip()
    print(f"[bot] 명령 수신: {text}", file=sys.stderr)

    cmd_map = {
        "/잔고":   cmd_balance,
        "/상태":   cmd_state,
        "/발굴":   cmd_discovery,
        "/도움말": cmd_help,
        "/help":   cmd_help,
    }

    # 명령어 매칭 (앞부분만 비교 — 인수 포함 가능성)
    handler = None
    for key, func in cmd_map.items():
        if text == key or text.startswith(key + " "):
            handler = func
            break

    if handler:
        try:
            handler()
        except Exception as e:
            send_text(f"❌ 명령 실행 중 오류 발생\n{e}")
            print(f"[bot] 명령 오류: {e}", file=sys.stderr)
        return True
    else:
        send_text(f"❓ 알 수 없는 명령어: {text}\n/도움말 을 입력해 보세요.")
        return False


# ── 명령 핸들러 ───────────────────────────────────────────────────────────────

def cmd_balance():
    """KIS 잔고 즉시 조회."""
    send_text("⏳ 잔고 조회 중...")
    try:
        from kis_client import KISClient
        client = KISClient()
        balance_raw = client.get_balance()

        output2 = balance_raw.get("output2", [])
        row = output2[0] if isinstance(output2, list) and output2 else {}

        def sf(v):
            try: return float(str(v).replace(",", "").strip())
            except: return 0.0

        net_asset  = sf(row.get("nass_amt", 0))
        stock_eval = sf(row.get("scts_evlu_amt", 0))
        deposit    = sf(row.get("dnca_tot_amt", 0))
        eval_pnl   = sf(row.get("evlu_pfls_smtl_amt", 0))

        try:
            orderable = client.get_orderable_cash()
        except Exception:
            orderable = sf(row.get("prvs_rcdl_excc_amt", 0))

        holdings = balance_raw.get("output1", [])
        holding_lines = []
        for h in holdings:
            qty = int(str(h.get("hldg_qty", "0")).replace(",", "") or 0)
            if qty == 0:
                continue
            name    = h.get("prdt_name", h.get("pdno", ""))
            cur     = sf(h.get("prpr", 0))
            pnl_pct = sf(h.get("evlu_pfls_rt", 0))
            emoji   = "🔴" if pnl_pct < 0 else "🟢"
            holding_lines.append(f"  {emoji} {name}: {cur:,.0f}원 ({pnl_pct:+.2f}%)")

        pnl_emoji = "🔴" if eval_pnl < 0 else "🟢"
        lines = [
            f"💼 잔고 현황 ({datetime.now().strftime('%H:%M')})",
            "=" * 24,
            f"💰 총평가금액: {net_asset:,.0f}원",
            f"📈 유가평가:   {stock_eval:,.0f}원",
            f"{pnl_emoji} 평가손익:   {eval_pnl:+,.0f}원",
            f"💵 예수금:     {deposit:,.0f}원",
            f"🔑 주문가능:   {orderable:,.0f}원",
        ]
        if holding_lines:
            lines.append("\n📋 보유 종목")
            lines.extend(holding_lines)

        send_text("\n".join(lines))
    except Exception as e:
        send_text(f"❌ 잔고 조회 실패: {e}")


def cmd_state():
    """오늘 daily_state 요약."""
    try:
        state = StateManager()
        s = state.get_today_state()
        today = s.get("date", "")
        market = s.get("market", {})
        holdings = s.get("holdings", {})
        alerts = s.get("alerts", {})
        discovery = s.get("discovery", {})
        updated_by = s.get("last_updated_by", "-")
        updated_at = s.get("last_updated_at", "-")

        lines = [
            f"📊 오늘의 상태 ({today})",
            "=" * 24,
        ]

        # 시장
        us = market.get("us_sentiment", "-")
        usd = market.get("usd_krw")
        fg = market.get("fear_greed")
        lines.append(f"\n🌏 시장")
        lines.append(f"  미국: {us}")
        if usd: lines.append(f"  달러: {usd:,.1f}원")
        if fg:  lines.append(f"  공포탐욕: {fg}")

        # 보유 종목 시그널
        if holdings:
            lines.append(f"\n💼 보유 종목 시그널")
            for code, info in holdings.items():
                sig = info.get("signal", "?")
                pnl = info.get("pnl_pct", 0)
                emoji = {"BUY": "📗", "SELL": "📕", "HOLD": "📘"}.get(sig, "📒")
                lines.append(f"  {emoji} {code}: {sig} ({pnl:+.2f}%)")

        # 알림
        intraday_alert = alerts.get("intraday")
        vol_spikes = alerts.get("vol_spike", [])
        if intraday_alert or vol_spikes:
            lines.append(f"\n⚠️ 알림")
            if intraday_alert: lines.append(f"  장초기: {intraday_alert}")
            if vol_spikes: lines.append(f"  거래량 급등: {', '.join(vol_spikes)}")

        # 발굴
        candidates = discovery.get("candidates", [])
        top_pick = discovery.get("top_pick")
        if candidates:
            lines.append(f"\n🔍 종목 발굴")
            lines.append(f"  추천: {', '.join(candidates)}")
            if top_pick: lines.append(f"  TOP: {top_pick}")

        lines.append(f"\n⏰ 마지막 업데이트: {updated_by} ({updated_at})")
        send_text("\n".join(lines))
    except Exception as e:
        send_text(f"❌ 상태 조회 실패: {e}")


def cmd_discovery():
    """stock_discovery 즉시 실행."""
    send_text("🔍 종목 발굴 시작합니다... (잠시 기다려 주세요)")
    try:
        import importlib.util, subprocess
        script = _ROOT / "morning_report" / "stock_discovery.py"
        result = subprocess.run(
            [str(_ROOT / "venv" / "bin" / "python3"), str(script)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            send_text(f"❌ 발굴 실패\n{result.stderr[-500:]}")
        else:
            send_text("✅ 종목 발굴 완료 — 결과를 위에서 확인하세요.")
    except Exception as e:
        send_text(f"❌ 발굴 실행 오류: {e}")


def cmd_help():
    """명령어 목록."""
    msg = (
        "📋 사용 가능한 명령어\n"
        "=" * 24 + "\n"
        "/잔고    — KIS 잔고 즉시 조회\n"
        "/상태    — 오늘 시장/시그널 요약\n"
        "/발굴    — 종목 발굴 즉시 실행\n"
        "/도움말  — 이 메시지\n"
        "\n"
        "⏰ 자동 브리핑\n"
        "  08:30 모닝 브리핑\n"
        "  09:10 장초기 브리핑\n"
        "  20:30 장마감 결산\n"
        "  23:30 종목 발굴"
    )
    send_text(msg)
