"""
check_price.py — 종목 현재가 즉시 조회

실행:
  venv/bin/python3 morning_report/check_price.py
"""
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(_ROOT / ".env")
from keychain_manager import inject_to_env
inject_to_env()

from kis_client import KISClient
client = KISClient()

# state에서 발굴 정보 자동 로드
from state_manager import StateManager
_state = StateManager()
_candidates = (_state.get("intraday_discovery.round2.candidates") or [])

# state에 데이터 있으면 자동, 없으면 수동 폴백
if _candidates:
    TARGETS    = [(c["code"], c["name"]) for c in _candidates[:5]]
    DISCOVERY  = {
        c["code"]: {
            "rate":  c.get("flc_2", 0),
            "power": c.get("pow_2", 0),
            "price": c.get("disc_price", 0),
        }
        for c in _candidates
    }
    print(f"[state] 발굴 종목 {len(TARGETS)}개 자동 로드")
else:
    # 수동 폴백 (state 없을 때)
    TARGETS = [
        ("007660", "이수페타시스"),
        ("000660", "SK하이닉스"),
        ("009420", "한올바이오파마"),
    ]
    DISCOVERY = {
        "007660": {"rate": 7.2, "power": 159, "price": 0},
        "000660": {"rate": 3.2, "power": 157, "price": 0},
        "009420": {"rate": 4.7, "power": 273, "price": 0},
    }
    print("[state] 발굴 데이터 없음 — 수동 폴백 사용")

print(f"\n📊 현재가 조회 ({datetime.now().strftime('%H:%M:%S')})")
print("=" * 55)

for code, name in TARGETS:
    try:
        resp = client._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        out = resp.get("output", {})
        price   = int(str(out.get("stck_prpr",   "0")).replace(",", ""))
        rate    = float(out.get("prdy_ctrt", 0))
        vol     = int(str(out.get("acml_vol",    "0")).replace(",", ""))
        high    = int(str(out.get("stck_hgpr",   "0")).replace(",", ""))
        low     = int(str(out.get("stck_lwpr",   "0")).replace(",", ""))
        open_   = int(str(out.get("stck_oprc",   "0")).replace(",", ""))
        wavg    = float(out.get("wghn_avrg_stck_prc", 0) or 0)   # 가중평균가
        per_val = float(out.get("per", 0) or 0)                   # PER
        frgn    = float(out.get("hts_frgn_ehrt", 0) or 0)         # 외국인 보유율

        # 체결강도 현재값 조회 (FHKST01010300)
        cur_power = 0.0
        try:
            ccnl = client.get_ccnl(code)
            cur_power = float(ccnl.get("tday_rltv", 0) or 0)
        except Exception:
            pass

        d              = DISCOVERY.get(code, {})
        disc_rate      = d.get("rate",  rate)
        disc_price     = d.get("price", 0)
        disc_power     = d.get("power", 0)
        rate_delta     = rate - disc_rate
        rate_arrow     = "↑" if rate_delta > 0.05 else ("↓" if rate_delta < -0.05 else "→")
        rate_delta_str = f"{rate_delta:+.2f}%p" if abs(rate_delta) >= 0.05 else "보합"

        price_delta     = price - disc_price if disc_price else 0
        price_delta_str = f"{price_delta:+,}원 ({price_delta/disc_price*100:+.2f}%)" if disc_price else ""

        # 현재가 vs 가중평균가 비교 (현재가가 가중평균 위면 오후 강세)
        wavg_diff     = ((price - wavg) / wavg * 100) if wavg else 0
        wavg_sign     = "▲" if wavg_diff > 0 else "▼"

        # 체결강도 변화 표시
        if disc_power and cur_power:
            power_delta = cur_power - disc_power
            power_arrow = "↑" if power_delta > 1 else ("↓" if power_delta < -1 else "→")
            power_str   = f"발굴 시 {disc_power:.1f}  →  현재 {cur_power:.1f}  ({power_delta:+.1f}) {power_arrow}"
        elif cur_power:
            power_str = f"현재 {cur_power:.1f}"
        elif disc_power:
            power_str = f"발굴 시 {disc_power:.1f}  (현재 조회 실패)"
        else:
            power_str = None

        print(f"\n  {'🔥' if rate >= 10 else '📈'} {name} ({code})")
        print(f"     현재가:  {price:>9,}원  |  시가: {open_:,}원")
        if disc_price:
            print(f"     발굴가:  {disc_price:>9,}원  →  {price_delta_str}")
        print(f"     고가:    {high:>9,}원  |  저가: {low:,}원")
        if wavg:
            print(f"     가중평균: {wavg:>8,.0f}원  ({wavg_sign}{abs(wavg_diff):.2f}% {'현재가 위 — 오후 강세' if wavg_diff > 0 else '현재가 아래 — 오후 약세'})")
        print(f"     거래량:  {vol:,}주  |  외인보유 {frgn:.1f}%")
        print(f"")
        print(f"     등락률:  현재 {rate:+.2f}%  /  발굴 시 {disc_rate:+.1f}%  →  {rate_delta_str} {rate_arrow}")
        if power_str:
            print(f"     체결강도: {power_str}")
    except Exception as e:
        print(f"\n  ❌ {name} ({code}) 조회 실패: {e}")

print("\n" + "=" * 55)
