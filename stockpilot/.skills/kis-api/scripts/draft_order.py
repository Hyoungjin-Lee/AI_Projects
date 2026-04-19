"""
주문 초안 생성기. 절대 실제 주문을 전송하지 않는다.

사용법:
    python draft_order.py BUY 005930 10                # 시장가 매수 10주
    python draft_order.py BUY 005930 10 --price 70000  # 지정가 매수
    python draft_order.py SELL 005930 5 --price 75000
"""
import argparse
import json
import sys

from kis_client import KISClient, KISConfigError, save_raw


def main() -> int:
    p = argparse.ArgumentParser(
        description="주문 JSON 초안 생성 — 절대 전송하지 않음"
    )
    p.add_argument("side", choices=["BUY", "SELL", "buy", "sell"])
    p.add_argument("code")
    p.add_argument("qty", type=int)
    p.add_argument("--price", type=int, default=None,
                   help="지정가 (생략 시 시장가)")
    args = p.parse_args()

    try:
        client = KISClient()
    except KISConfigError as e:
        print(f"[설정오류] {e}", file=sys.stderr)
        return 2

    draft = client.build_order_payload(args.side, args.code, args.qty, args.price)

    out = {
        "STATUS": "DRAFT_ONLY — 실제 주문 전송되지 않음",
        "summary": draft["human_summary"],
        "request": {
            "method": draft["method"],
            "url": f"https://openapi.koreainvestment.com:9443{draft['endpoint']}",
            "tr_id": draft["tr_id"],
            "body": draft["body"],
        },
        "next_step": (
            "이 초안이 맞으면 사용자에게 명시적으로 '이대로 전송' 확인을 받은 뒤, "
            "환경변수 KIS_ALLOW_LIVE_ORDER=1 을 설정하고 "
            "client.place_order(...) 를 호출하세요."
        ),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    save_raw("order_draft", args.code, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
