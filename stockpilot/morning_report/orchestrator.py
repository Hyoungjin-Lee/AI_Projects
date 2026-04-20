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
            avg     = sf(h.get("pchs_avg_pric", 0))
            pnl     = sf(h.get("evlu_pfls_amt", 0))
            pnl_pct = sf(h.get("evlu_pfls_rt", 0))
            emoji   = "🔴" if pnl_pct < 0 else "🟢"
            holding_lines.append(
                f"  {emoji} {name}\n"
                f"     현재가: {cur:,.0f}원  |  수량: {qty}주\n"
                f"     평단: {avg:,.0f}원  |  손익: {pnl:+,.0f}원 ({pnl_pct:+.2f}%)"
            )

        pnl_emoji = "🔴" if eval_pnl < 0 else "🟢"
        lines = [
            f"💼 잔고 현황 ({datetime.now().strftime('%H:%M')})",
            "―――――――――――――――",
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
            "―――――――――――――――",
        ]

        # 시장
        us = market.get("us_sentiment", "-")
        usd = market.get("usd_krw")
        fg = market.get("fear_greed")
        lines.append(f"\n🌏 시장")
        lines.append(f"  미국: {us}")
        if usd: lines.append(f"  달러: {usd:,.1f}원")
        if fg:  lines.append(f"  공포탐욕: {fg}")

        # 보유 종목 시그널 — 현재가 실시간 조회
        if holdings:
            _SIG_KR = {"BUY": "매수", "SELL": "매도", "HOLD": "보유", "WATCH": "관망"}
            # KIS 현재가 조회 (실패해도 state 저장값으로 폴백)
            cur_prices = {}
            try:
                from kis_client import KISClient
                _kc = KISClient()
                for code in holdings:
                    try:
                        _p = _kc.get_price(code)
                        cur_prices[code] = (
                            float(str(_p.get("stck_prpr", 0)).replace(",", "")),
                            float(_p.get("prdy_ctrt", 0)),
                        )
                    except Exception:
                        pass
            except Exception:
                pass

            lines.append(f"\n💼 보유 종목 시그널")
            for code, info in holdings.items():
                sig        = info.get("signal", "WATCH")
                name       = info.get("name", code)
                pnl        = info.get("pnl_pct", 0)
                avg        = info.get("avg_price", 0)
                stop       = info.get("stop_loss")
                target     = info.get("target")
                entry_low  = info.get("entry_low")
                entry_high = info.get("entry_high")
                exit_low   = info.get("exit_low")
                exit_high  = info.get("exit_high")

                sig_kr   = _SIG_KR.get(sig, sig)
                emoji    = {"BUY": "📗", "SELL": "📕", "HOLD": "📘", "WATCH": "📒"}.get(sig, "📒")
                pnl_sign = "🔴" if pnl < 0 else "🟢"

                # 현재가 (실시간 우선, 없으면 state 저장값)
                cur, cur_rate = cur_prices.get(code, (info.get("cur_price", 0), 0))
                cur_str = f"{cur:,.0f}원 ({cur_rate:+.2f}%)" if cur else "조회 실패"

                lines.append(f"  {emoji} {name}({code})  [{sig_kr}]  {pnl_sign}{pnl:+.2f}%")
                lines.append(f"     현재가: {cur_str}")
                if avg:
                    lines.append(f"     평단: {avg:,.0f}원")
                if stop and target:
                    lines.append(f"     손절: {stop:,.0f}  /  목표: {target:,.0f}원")

                # 매수/매도 상황별 코멘트
                for comment in _build_action_comment(sig, cur, avg, entry_low, entry_high, exit_low, exit_high):
                    lines.append(f"     {comment}")

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
    """종목 발굴 즉시 실행 — 장중이면 intraday_discovery, 장외이면 stock_discovery."""
    from datetime import time as dtime
    now = datetime.now().time()
    market_open  = dtime(9, 0)
    market_close = dtime(15, 30)
    is_market_hours = market_open <= now <= market_close

    if is_market_hours:
        send_text("🔍 장중 실시간 종목 발굴 시작합니다... (약 30초 소요)")
        _run_intraday_discovery()
    else:
        send_text("🔍 야간 종목 스크리닝 시작합니다... (약 1분 소요)")
        _run_stock_discovery()


def _run_intraday_discovery():
    """장중 — intraday_discovery round1 → round2 순차 실행."""
    import subprocess
    python = str(_ROOT / "venv" / "bin" / "python3")
    script = str(_ROOT / "morning_report" / "intraday_discovery.py")

    try:
        # round1
        r1 = subprocess.run(
            [python, script, "--round", "1"],
            capture_output=True, text=True, timeout=60
        )
        if r1.returncode != 0:
            send_text(f"❌ 발굴 1차 실패\n{r1.stderr[-400:]}")
            return

        # round2 (결과 텔레그램 전송 포함)
        r2 = subprocess.run(
            [python, script, "--round", "2"],
            capture_output=True, text=True, timeout=60
        )
        if r2.returncode != 0:
            send_text(f"❌ 발굴 2차 실패\n{r2.stderr[-400:]}")
        else:
            send_text("✅ 장중 발굴 완료 — 위 결과를 확인하세요.")
    except subprocess.TimeoutExpired:
        send_text("⏱️ 발굴 시간 초과 (60초) — 잠시 후 다시 시도해주세요.")
    except Exception as e:
        send_text(f"❌ 발굴 실행 오류: {e}")


def _run_stock_discovery():
    """장외 — stock_discovery (관심종목 야간 스크리닝)."""
    import subprocess
    python = str(_ROOT / "venv" / "bin" / "python3")
    script = str(_ROOT / "morning_report" / "stock_discovery.py")

    try:
        result = subprocess.run(
            [python, script, "--force"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            send_text(f"❌ 발굴 실패\n{result.stderr[-500:]}")
        else:
            send_text("✅ 야간 발굴 완료 — 위 결과를 확인하세요.")
    except subprocess.TimeoutExpired:
        send_text("⏱️ 발굴 시간 초과 (120초) — 잠시 후 다시 시도해주세요.")
    except Exception as e:
        send_text(f"❌ 발굴 실행 오류: {e}")


def _build_action_comment(
    sig: str,
    cur: float,
    avg: float,
    entry_low: float | None,   # SMA20 × 1.005  (눌림 하단)
    entry_high: float | None,  # 5일고가 × 1.005 (돌파 상단)
    exit_low: float | None,    # 평단 × 0.97     (하드스탑)
    exit_high: float | None,   # 평단 × 1.05     (목표가)
) -> list[str]:
    """
    현재가와 기준값을 비교해 상황별 매수/매도 코멘트 반환.
    반환: 텔레그램에 출력할 줄 목록 (각 줄 앞에 들여쓰기 없음 — 호출자가 붙임)
    """
    comments = []

    # ── 매수 시그널 ──────────────────────────────────────────────────────────────
    if sig in ("BUY", "HOLD"):
        if not cur or not entry_low:
            comments.append("💡 타점 데이터 없음 — 장마감 후 재확인")
            return comments

        # 1) 추세 이탈 — SMA20 아래로 내려온 경우
        if entry_low and cur < entry_low * 0.995:   # SMA20 아래 ~0.5% 여유
            comments.append(f"🚫 현재 단가 추가매수 금지 — SMA20({entry_low:,.0f}원) 하회")
            if exit_low:
                comments.append(f"   손절가({exit_low:,.0f}원) 이탈 시 즉시 손절")

        # 2) 눌림지지 구간 — SMA20 ~ SMA20×1.02
        elif entry_low and entry_high and cur <= entry_low * 1.02:
            buy_top = round(entry_low * 1.02, 0)
            comments.append(f"✅ 눌림지지 확인됨 — {entry_low:,.0f}원 ~ {buy_top:,.0f}원 매수")
            comments.append(f"   (SMA20 지지 구간, 분할매수 1~2차 적정)")

        # 3) 추세 유지 / 돌파 대기 — SMA20×1.02 ~ 5일고가
        elif entry_high and cur < entry_high:
            comments.append(f"⏳ 돌파 대기 구간 — 현재 추세 유지 중")
            comments.append(f"   돌파 확인 시({entry_high:,.0f}원↑) 추가 매수 검토")
            comments.append(f"🚫 현재 단가 추가매수 금지 — 돌파 전 고점 추격 리스크")

        # 4) 돌파 추세 구간 — 5일고가 이상
        elif entry_high and cur >= entry_high:
            buy_bot = entry_high
            buy_top = round(entry_high * 1.01, 0)   # 돌파가 +1% 이내
            if cur <= buy_top:
                comments.append(f"✅ 돌파추세 확인됨 — {buy_bot:,.0f}원 ~ {buy_top:,.0f}원 매수")
                comments.append(f"   (돌파 직후 구간, 추격 과열 주의)")
            else:
                comments.append(f"🚫 현재 단가 추가매수 금지 — 돌파 후 과열 구간")
                comments.append(f"   눌림 시({entry_low:,.0f}원 ~ {entry_high:,.0f}원) 재진입 대기")

    # ── 매도 시그널 ──────────────────────────────────────────────────────────────
    elif sig == "SELL":
        if not cur:
            comments.append("💡 타점 데이터 없음 — 장마감 후 재확인")
            return comments

        # 1) 하드스탑 발동 — 손절가 이탈
        if exit_low and cur <= exit_low:
            comments.append(f"🚨 하드스탑 발동 — 즉시 전량 손절")
            comments.append(f"   현재가({cur:,.0f}원) ≤ 손절가({exit_low:,.0f}원)")

        # 2) 손실 구간 — 손절가 위, 평단 아래
        elif avg and cur < avg:
            loss_pct = (cur - avg) / avg * 100
            comments.append(f"⚠️ 손실 구간 ({loss_pct:.1f}%) — 추가매수 금지")
            if exit_low:
                sell_bot = exit_low
                sell_top = round(avg * 0.995, 0)
                comments.append(f"✅ 매도 추천: {sell_bot:,.0f}원 ~ {sell_top:,.0f}원 대 분할 정리")

        # 3) 수익 구간 — 평단 이상, 목표가 미달
        elif avg and exit_high and cur < exit_high:
            gain_pct = (cur - avg) / avg * 100
            sell_bot = round(avg * 1.02, 0)   # 트레일링 활성화 기준
            comments.append(f"📊 수익 구간 (+{gain_pct:.1f}%) — 트레일링 스탑 대기")
            if cur >= sell_bot:
                comments.append(f"✅ 매도 추천: {sell_bot:,.0f}원 ~ {exit_high:,.0f}원 대 분할 익절")
            else:
                comments.append(f"   트레일링 활성화까지 {sell_bot:,.0f}원↑ 대기")

        # 4) 목표가 도달
        elif exit_high and cur >= exit_high:
            sell_top = round(exit_high * 1.02, 0)
            comments.append(f"🎯 목표가 도달 — {exit_high:,.0f}원 ~ {sell_top:,.0f}원 대 익절")
            comments.append(f"   분할 매도 권장 (1/3씩 단계적 정리)")

    # ── WATCH ───────────────────────────────────────────────────────────────────
    else:
        comments.append("📊 관망 — 매수/매도 조건 미충족")

    return comments


def cmd_help():
    """명령어 목록."""
    msg = (
        "📋 사용 가능한 명령어\n"
        "\n"
        "/잔고    — KIS 잔고 즉시 조회\n"
        "/상태    — 오늘 시장/시그널 요약\n"
        "/발굴    — 종목 발굴 즉시 실행\n"
        "          (장중 09:00~15:30 → 실시간 발굴)\n"
        "          (장외 → 관심종목 스크리닝)\n"
        "/도움말  — 이 메시지\n"
        "\n"
        "⏰ 자동 브리핑\n"
        "  08:30 모닝 브리핑\n"
        "  09:03 장초기 실시간 발굴 (1차)\n"
        "  09:05 장초기 실시간 발굴 (2차)\n"
        "  09:10 장초기 브리핑\n"
        "  20:30 장마감 결산\n"
        "  23:30 야간 종목 발굴"
    )
    send_text(msg)
