"""계좌 잔고 조회. 사용법: python get_balance.py"""
import argparse
import json
import sys

from kis_client import KISClient, KISConfigError, save_raw


def main() -> int:
    p = argparse.ArgumentParser(description="계좌 보유 종목 + 평가손익 + 예수금")
    p.add_argument("--no-save", action="store_true")
    args = p.parse_args()

    try:
        client = KISClient()
    except KISConfigError as e:
        print(f"[설정오류] {e}", file=sys.stderr)
        return 2

    data = client.get_balance()
    holdings = []
    for h in data.get("output1", []):
        qty = int(h.get("hldg_qty", 0))
        if qty == 0:
            continue
        holdings.append({
            "code": h["pdno"],
            "name": h["prdt_name"],
            "qty": qty,
            "avg_price": int(float(h["pchs_avg_pric"])),
            "current_price": int(h["prpr"]),
            "eval_amount": int(h["evlu_amt"]),
            "pnl": int(h["evlu_pfls_amt"]),
            "pnl_pct": float(h.get("evlu_pfls_rt", 0) or 0),
        })

    summary = data.get("output2", [{}])[0]
    payload = {
        "holdings": holdings,
        "deposit": int(summary.get("dnca_tot_amt", 0)),         # 예수금
        "available_cash": int(summary.get("ord_psbl_cash", 0)),  # 주문가능
        "total_eval": int(summary.get("tot_evlu_amt", 0)),       # 총평가
        "total_pnl": int(summary.get("evlu_pfls_smtl_amt", 0)),  # 평가손익 합계
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not args.no_save:
        path = save_raw("balance", "ACCT", payload)
        print(f"# saved: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
