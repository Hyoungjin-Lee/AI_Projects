"""일봉 차트. 사용법: python get_daily_chart.py <종목코드> [--days 60]"""
import argparse
import json
import sys

from kis_client import KISClient, KISConfigError, save_raw


def main() -> int:
    p = argparse.ArgumentParser(description="국내주식 일봉 OHLCV 조회 (최대 100일)")
    p.add_argument("code")
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--no-save", action="store_true")
    args = p.parse_args()

    try:
        client = KISClient()
    except KISConfigError as e:
        print(f"[설정오류] {e}", file=sys.stderr)
        return 2

    raw = client.get_daily_chart(args.code, days=args.days)
    rows = []
    for r in raw:
        if not r.get("stck_bsop_date"):
            continue
        rows.append({
            "date": r["stck_bsop_date"],
            "open": int(r["stck_oprc"]),
            "high": int(r["stck_hgpr"]),
            "low": int(r["stck_lwpr"]),
            "close": int(r["stck_clpr"]),
            "volume": int(r["acml_vol"]),
            "value_백만": int(r.get("acml_tr_pbmn", 0)) // 1_000_000,
        })
    rows.sort(key=lambda x: x["date"])  # 오래된 순

    payload = {"code": args.code, "days": len(rows), "ohlcv": rows}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not args.no_save:
        path = save_raw("daily", args.code, payload)
        print(f"# saved: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
