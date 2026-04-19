"""현재가 조회. 사용법: python get_quote.py <종목코드>"""
import argparse
import json
import sys

from kis_client import KISClient, KISConfigError, save_raw


def main() -> int:
    p = argparse.ArgumentParser(description="국내주식 현재가 조회")
    p.add_argument("code", help="종목코드 (예: 005930)")
    p.add_argument("--no-save", action="store_true", help="data/raw/에 저장하지 않음")
    args = p.parse_args()

    try:
        client = KISClient()
    except KISConfigError as e:
        print(f"[설정오류] {e}", file=sys.stderr)
        return 2

    out = client.get_price(args.code)
    summary = {
        "code": args.code,
        "name": out.get("hts_kor_isnm"),
        "current_price": int(out["stck_prpr"]),
        "change": int(out["prdy_vrss"]),
        "change_pct": float(out["prdy_ctrt"]),
        "volume": int(out["acml_vol"]),
        "market_cap_억": int(out.get("hts_avls", 0)),
        "high_52w": int(out.get("w52_hgpr", 0)),
        "low_52w": int(out.get("w52_lwpr", 0)),
        "per": float(out.get("per", 0) or 0),
        "pbr": float(out.get("pbr", 0) or 0),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.no_save:
        path = save_raw("quote", args.code, summary)
        print(f"# saved: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
