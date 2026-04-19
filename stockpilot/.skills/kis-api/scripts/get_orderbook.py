"""호가 조회 (10단계). 사용법: python get_orderbook.py <종목코드>"""
import argparse
import json
import sys

from kis_client import KISClient, KISConfigError, save_raw


def main() -> int:
    p = argparse.ArgumentParser(description="10단계 호가 + 잔량")
    p.add_argument("code")
    p.add_argument("--no-save", action="store_true")
    args = p.parse_args()

    try:
        client = KISClient()
    except KISConfigError as e:
        print(f"[설정오류] {e}", file=sys.stderr)
        return 2

    data = client.get_orderbook(args.code)
    out1 = data.get("output1", {})
    asks, bids = [], []
    for i in range(1, 11):
        ask_p = out1.get(f"askp{i}")
        ask_q = out1.get(f"askp_rsqn{i}")
        bid_p = out1.get(f"bidp{i}")
        bid_q = out1.get(f"bidp_rsqn{i}")
        if ask_p:
            asks.append({"level": i, "price": int(ask_p), "qty": int(ask_q or 0)})
        if bid_p:
            bids.append({"level": i, "price": int(bid_p), "qty": int(bid_q or 0)})

    payload = {
        "code": args.code,
        "total_ask_qty": int(out1.get("total_askp_rsqn", 0)),
        "total_bid_qty": int(out1.get("total_bidp_rsqn", 0)),
        "asks": asks,   # 매도 호가 (낮은 가격부터)
        "bids": bids,   # 매수 호가 (높은 가격부터)
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not args.no_save:
        path = save_raw("orderbook", args.code, payload)
        print(f"# saved: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
