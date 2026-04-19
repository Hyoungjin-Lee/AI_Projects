"""
intraday_discovery.py — 장초기 실시간 종목 발굴

실행 방법:
  venv/bin/python3 morning_report/intraday_discovery.py --round 1
  venv/bin/python3 morning_report/intraday_discovery.py --round 2
  venv/bin/python3 morning_report/intraday_discovery.py --round 2 --dry-run
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(_ROOT / ".env")

from keychain_manager import inject_to_env
inject_to_env()
from state_manager import StateManager

_WEEKDAYS = {0, 1, 2, 3, 4}
_TOP_N = 30
_HTS_TOP_N = 10

_VOLUME_PATH = "/uapi/domestic-stock/v1/quotations/volume-rank"
_POWER_PATH = "/uapi/domestic-stock/v1/ranking/volume-power"
_FLUCT_PATH = "/uapi/domestic-stock/v1/ranking/fluctuation"
_DISPARITY_PATH = "/uapi/domestic-stock/v1/ranking/disparity"
_HTS_PATH = "/uapi/domestic-stock/v1/quotations/capture-uplmt"

_MEDALS = ["🥇", "🥈", "🥉"]


def run(round_no: int, dry_run: bool = False) -> int:
    now = datetime.now()
    now_str = now.strftime("%H:%M")
    print(f"[{now_str}] 장초기 종목 발굴 시작 (round {round_no})...", file=sys.stderr)

    if date.today().weekday() not in _WEEKDAYS:
        print("[발굴] 오늘은 주말입니다. 종료.", file=sys.stderr)
        return 0

    try:
        from kis_client import KISClient
        client = KISClient()
    except Exception as exc:
        print(f"[오류] KIS 클라이언트 초기화 실패: {exc}", file=sys.stderr)
        return 1

    state = StateManager()

    if round_no == 1:
        return _run_round1(client, state)
    return _run_round2(client, state, dry_run=dry_run)


def _run_round1(client, state: StateManager) -> int:
    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)

    round1 = {
        "time": datetime.now().strftime("%H:%M"),
        "vol": _extract_codes(volume_rows),
        "pow": _extract_metric_map(power_rows, "cttr"),
        "flc": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "acml_vol": _extract_metric_map(volume_rows, "acml_vol"),
        "names": _extract_name_map(volume_rows, power_rows, fluct_rows),
    }

    state.update("intraday_discovery", {"round1": round1}, caller="intraday_discovery")
    print(
        f"[완료] round1 저장 완료 "
        f"(거래량 {len(round1['vol'])} / 체결강도 {len(round1['pow'])} / 등락률 {len(round1['flc'])})",
        file=sys.stderr,
    )
    return 0


def _run_round2(client, state: StateManager, dry_run: bool = False) -> int:
    round1 = state.get("intraday_discovery.round1")
    if not isinstance(round1, dict):
        print("[오류] round1 데이터가 없습니다. 먼저 --round 1 을 실행하세요.", file=sys.stderr)
        return 1

    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)
    disparity_rows = _fetch_disparity_rank(client)
    hts_rows = _fetch_hts_rank(client)

    vol_1 = set(round1.get("vol", []))
    vol_2 = set(_extract_codes(volume_rows))
    pow_1 = set((round1.get("pow") or {}).keys())
    pow_2 = set(_extract_metric_map(power_rows, "cttr").keys())
    flc_1 = set((round1.get("flc") or {}).keys())
    flc_2 = set(_extract_metric_map(fluct_rows, "prdy_ctrt").keys())

    candidates = vol_1 & vol_2 & pow_1 & pow_2 & flc_1 & flc_2

    overheated = {
        code for code, value in _extract_metric_map(disparity_rows, "d20_dsrt").items()
        if value >= 120
    }
    filtered = sorted(code for code in candidates if code not in overheated)

    hts_top = _extract_codes(hts_rows)[:_HTS_TOP_N]
    hts_ranks = {code: idx + 1 for idx, code in enumerate(hts_top)}

    names = {}
    names.update(round1.get("names") or {})
    names.update(_extract_name_map(volume_rows, power_rows, fluct_rows, disparity_rows, hts_rows))

    metrics = {
        "pow_1": round1.get("pow", {}) or {},
        "pow_2": _extract_metric_map(power_rows, "cttr"),
        "flc_1": round1.get("flc", {}) or {},
        "flc_2": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "vol_1": round1.get("acml_vol", {}) or {},
        "vol_2": _extract_metric_map(volume_rows, "acml_vol"),
        "disparity": _extract_metric_map(disparity_rows, "d20_dsrt"),
    }

    scored = []
    for code in filtered:
        item = _score_candidate(code, names, metrics, hts_ranks)
        if item is not None:
            scored.append(item)

    scored.sort(key=lambda item: (-item["score"], -item["pow_2"], -item["flc_2"], item["code"]))
    top_picks = scored[:3]

    round2 = {
        "time": datetime.now().strftime("%H:%M"),
        "candidate_count": len(scored),
        "overheated_count": len(candidates & overheated),
        "candidates": [
            {
                "code": item["code"],
                "name": item["name"],
                "score": item["score"],
                "pow_2": item["pow_2"],
                "pow_delta": item["pow_delta"],
                "flc_2": item["flc_2"],
                "flc_delta": item["flc_delta"],
                "vol_delta": item["vol_delta"],
                "hts_rank": item["hts_rank"],
            }
            for item in scored
        ],
        "top_picks": [item["code"] for item in top_picks],
    }
    state.update("intraday_discovery", {"round2": round2}, caller="intraday_discovery")

    message = _build_message(round2["time"], top_picks, len(scored))
    if dry_run:
        print("\n" + "=" * 50)
        print(message)
        print("=" * 50)
        print("\n[DRY-RUN] 텔레그램 전송 생략")
        return 0

    try:
        from telegram_sender import send_text
        ok = send_text(message)
    except Exception as exc:
        print(f"[오류] 텔레그램 전송 실패: {exc}", file=sys.stderr)
        return 1

    if ok:
        print(f"[완료] 텔레그램 전송 성공 ({len(scored)}개 후보)", file=sys.stderr)
        return 0

    print("[오류] 텔레그램 전송 실패", file=sys.stderr)
    return 1


def _fetch_volume_rank(client) -> list[dict[str, Any]]:
    return _fetch_rank(
        client,
        path=_VOLUME_PATH,
        tr_id="FHPST01710000",
        params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "2001",
            "FID_DIV_CLS_CODE": "1",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "0000001100",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": "",
        },
        fallback_params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "1",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "0000001100",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": "",
        },
    )


def _fetch_power_rank(client) -> list[dict[str, Any]]:
    return _fetch_rank(
        client,
        path=_POWER_PATH,
        tr_id="FHPST01680000",
        params={
            "fid_trgt_exls_cls_code": "0000001100",
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20168",
            "fid_input_iscd": "2001",
            "fid_div_cls_code": "1",
            "fid_input_price_1": "",
            "fid_input_price_2": "",
            "fid_vol_cnt": "",
            "fid_trgt_cls_code": "0",
        },
        fallback_params={
            "fid_trgt_exls_cls_code": "0000001100",
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20168",
            "fid_input_iscd": "0000",
            "fid_div_cls_code": "1",
            "fid_input_price_1": "",
            "fid_input_price_2": "",
            "fid_vol_cnt": "",
            "fid_trgt_cls_code": "0",
        },
    )


def _fetch_fluctuation_rank(client) -> list[dict[str, Any]]:
    return _fetch_rank(
        client,
        path=_FLUCT_PATH,
        tr_id="FHPST01700000",
        params={
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20170",
            "fid_input_iscd": "2001",
            "fid_rank_sort_cls_code": "0",
            "fid_input_cnt_1": "0",
            "fid_prc_cls_code": "1",
            "fid_input_price_1": "",
            "fid_input_price_2": "",
            "fid_vol_cnt": "",
            "fid_trgt_cls_code": "0",
            "fid_trgt_exls_cls_code": "0000001100",
            "fid_div_cls_code": "0",
            "fid_rsfl_rate1": "",
            "fid_rsfl_rate2": "",
        },
        fallback_params={
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20170",
            "fid_input_iscd": "0000",
            "fid_rank_sort_cls_code": "0",
            "fid_input_cnt_1": "0",
            "fid_prc_cls_code": "1",
            "fid_input_price_1": "",
            "fid_input_price_2": "",
            "fid_vol_cnt": "",
            "fid_trgt_cls_code": "0",
            "fid_trgt_exls_cls_code": "0000001100",
            "fid_div_cls_code": "0",
            "fid_rsfl_rate1": "",
            "fid_rsfl_rate2": "",
        },
    )


def _fetch_disparity_rank(client) -> list[dict[str, Any]]:
    return _fetch_rank(
        client,
        path=_DISPARITY_PATH,
        tr_id="FHPST01780000",
        params={
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20178",
            "fid_input_iscd": "2001",
            "fid_rank_sort_cls_code": "0",
            "fid_hour_cls_code": "20",
            "fid_div_cls_code": "0",
            "fid_trgt_cls_code": "0",
            "fid_trgt_exls_cls_code": "0",
            "fid_input_price_1": "",
            "fid_input_price_2": "",
            "fid_vol_cnt": "",
        },
        fallback_params={
            "fid_cond_mrkt_div_code": "J",
            "fid_cond_scr_div_code": "20178",
            "fid_input_iscd": "0000",
            "fid_rank_sort_cls_code": "0",
            "fid_hour_cls_code": "20",
            "fid_div_cls_code": "0",
            "fid_trgt_cls_code": "0",
            "fid_trgt_exls_cls_code": "0",
            "fid_input_price_1": "",
            "fid_input_price_2": "",
            "fid_vol_cnt": "",
        },
    )


def _fetch_hts_rank(client) -> list[dict[str, Any]]:
    try:
        response = client._get(_HTS_PATH, "FHPST01830000", {})
        return _normalize_output(response)[:_TOP_N]
    except Exception as exc:
        print(f"[경고] HTS조회상위 API 실패, 관심도 가산점 생략: {exc}", file=sys.stderr)
        return []


def _fetch_rank(
    client,
    path: str,
    tr_id: str,
    params: dict[str, Any],
    fallback_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        response = client._get(path, tr_id, params)
        return _normalize_output(response)[:_TOP_N]
    except Exception as exc:
        print(f"[경고] {tr_id} 1차 조회 실패: {exc}", file=sys.stderr)

    if fallback_params is None:
        return []

    try:
        response = client._get(path, tr_id, fallback_params)
        print(f"[경고] {tr_id} 전체시장 fallback(0000) 사용", file=sys.stderr)
        return _normalize_output(response)[:_TOP_N]
    except Exception as exc:
        print(f"[오류] {tr_id} fallback 조회 실패: {exc}", file=sys.stderr)
        return []


def _normalize_output(response: dict[str, Any]) -> list[dict[str, Any]]:
    output = response.get("output", [])
    return output if isinstance(output, list) else []


def _extract_codes(rows: list[dict[str, Any]]) -> list[str]:
    codes = []
    for row in rows:
        code = str(row.get("mksc_shrn_iscd", "")).strip()
        if code:
            codes.append(code)
    return codes


def _extract_metric_map(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    metrics = {}
    for row in rows:
        code = str(row.get("mksc_shrn_iscd", "")).strip()
        if not code:
            continue
        value = _safe_float(row.get(field))
        if value is None:
            continue
        metrics[code] = value
    return metrics


def _extract_name_map(*groups: list[dict[str, Any]]) -> dict[str, str]:
    names = {}
    for rows in groups:
        for row in rows:
            code = str(row.get("mksc_shrn_iscd", "")).strip()
            name = str(row.get("hts_kor_isnm", "")).strip()
            if code and name:
                names[code] = name
    return names


def _safe_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _score_candidate(
    code: str,
    names: dict[str, str],
    metrics: dict[str, dict[str, float]],
    hts_ranks: dict[str, int],
) -> dict[str, Any] | None:
    pow_1 = metrics["pow_1"].get(code)
    pow_2 = metrics["pow_2"].get(code)
    flc_1 = metrics["flc_1"].get(code)
    flc_2 = metrics["flc_2"].get(code)
    vol_1 = metrics["vol_1"].get(code)
    vol_2 = metrics["vol_2"].get(code)

    if None in (pow_1, pow_2, flc_1, flc_2, vol_1, vol_2):
        return None

    score = 0
    reasons = []

    if pow_2 >= 130:
        score += 3
    elif pow_2 >= 110:
        score += 2
    elif pow_2 >= 100:
        score += 1
    elif pow_2 > pow_1:
        score += 1
    else:
        return None

    flc_delta = flc_2 - flc_1
    if flc_delta > 0:
        score += 1
        reasons.append("등락률상승")

    vol_delta = vol_2 - vol_1
    if vol_delta > 0:
        score += 1
        reasons.append("거래량증가")

    hts_rank = hts_ranks.get(code)
    if hts_rank is not None:
        score += 1
        reasons.append("온라인관심")

    return {
        "code": code,
        "name": names.get(code, code),
        "score": score,
        "pow_1": pow_1,
        "pow_2": pow_2,
        "pow_delta": pow_2 - pow_1,
        "flc_1": flc_1,
        "flc_2": flc_2,
        "flc_delta": flc_delta,
        "vol_1": vol_1,
        "vol_2": vol_2,
        "vol_delta": vol_delta,
        "hts_rank": hts_rank,
        "reasons": reasons,
    }


def _build_message(time_str: str, top_picks: list[dict[str, Any]], candidate_count: int) -> str:
    lines = [
        f"🔍 장초기 종목 발굴 ({time_str})",
        "―――――――――――――――",
        "코스피200 실시간 분석",
        "",
    ]

    if candidate_count == 0:
        lines.append("교집합 종목 없음 — 오늘은 뚜렷한 신호 없음")
        return "\n".join(lines)

    for idx, item in enumerate(top_picks):
        medal = _MEDALS[idx] if idx < len(_MEDALS) else f"{idx + 1}."
        lines.append(f"{medal} {item['name']} ({item['code']})  {item['score']}점")
        lines.append(
            "   "
            f"체결강도: {item['pow_2']:.0f}{_format_delta(item['pow_delta'], no_sign_if_zero=True)} "
            f"| 등락률: {item['flc_2']:+.1f}%{_trend_mark(item['flc_delta'])} "
            f"| {'거래량↑' if item['vol_delta'] > 0 else '거래량→'}"
        )
        if item["hts_rank"] is not None:
            lines.append(f"   🌐 온라인 관심 {item['hts_rank']}위")
        lines.append("")

    if lines[-1] == "":
        lines.pop()

    lines.extend(
        [
            "―――――――――――――――",
            f"후보 {candidate_count}종목 → 상위 {min(3, len(top_picks))}종목 선정",
        ]
    )
    return "\n".join(lines)


def _format_delta(delta: float, no_sign_if_zero: bool = False) -> str:
    if abs(delta) < 0.05:
        return "" if no_sign_if_zero else " (0)"
    arrow = "↑" if delta > 0 else "↓"
    return f" ({delta:+.0f}{arrow})"


def _trend_mark(delta: float) -> str:
    if delta > 0:
        return "↑"
    if delta < 0:
        return "↓"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="장초기 실시간 종목 발굴")
    parser.add_argument("--round", dest="round_no", type=int, choices=[1, 2], required=True)
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 출력만 수행")
    args = parser.parse_args()
    return run(round_no=args.round_no, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
