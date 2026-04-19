"""분봉(1분) 차트. 사용법: python get_minute_chart.py <종목코드> [--time 1530]"""
import argparse
import json
import sys
from datetime import datetime

from kis_client import KISClient, KISConfigError, save_raw


def main() -> int:
    p = argparse.ArgumentParser(description="국내주식 1분봉 30개 (지정 시각 기준)")
    p.add_argument("code")
    p.add_argument("--time", default=None,
                   help="HHMM 또는 HHMMSS (기본: 현재시각, 장중이 아니면 153000)")
    p.add_argument("--no-save", action="store_true")
    args = p.parse_args()

    if args.time:
        hhmm = args.time.ljust(6, "0")
    else:
        now = datetime.now()
        # 장 마감 후이거나 장 시작 전이면 종가 시각
        if now.hour < 9 or (now.hour == 15 and now.minute > 30) or now.hour > 15:
            hhmm = "153000"
        else:
            hhmm = now.strftime("%H%M%S")

    try:
        client = KISClient()
    except KISConfigError as e:
        print(f"[설정오류] {e}", file=sys.stderr)
        return 2

    raw = client.get_minute_chart(args.code, hhmm=hhmm)
    rows = []
    for r in raw:
        if not r.get("stck_cntg_hour"):
            continue
        rows.append({
            "time": r["stck_cntg_hour"],
            "open": int(r["stck_oprc"]),
            "high": int(r["stck_hgpr"]),
            "low": int(r["stck_lwpr"]),
            "close": int(r["stck_prpr"]),
            "volume": int(r["cntg_vol"]),
        })
    rows.sort(key=lambda x: x["time"])

    payload = {"code": args.code, "anchor_time": hhmm, "minutes": len(rows), "ohlcv": rows}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not args.no_save:
        path = save_raw("minute", args.code, payload)
        print(f"# saved: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
