"""
intraday_discovery.py — 장초기 실시간 종목 발굴

실행 방법:
  venv/bin/python3 morning_report/intraday_discovery.py --round 1
  venv/bin/python3 morning_report/intraday_discovery.py --round 2
  venv/bin/python3 morning_report/intraday_discovery.py --round 3
  venv/bin/python3 morning_report/intraday_discovery.py --round 4
  venv/bin/python3 morning_report/intraday_discovery.py --round 5
  venv/bin/python3 morning_report/intraday_discovery.py --round 6
  venv/bin/python3 morning_report/intraday_discovery.py --round 7
  venv/bin/python3 morning_report/intraday_discovery.py --round 8
  venv/bin/python3 morning_report/intraday_discovery.py --round 9
  ...
  venv/bin/python3 morning_report/intraday_discovery.py --round 26
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
_TOP_N = 50
_HTS_TOP_N = 10
# 이격도 과열 컷 — SMA20 대비 +30% 초과 종목 제외 (v2.8.0 완화: 120 → 130)
_DISPARITY_OVERHEATED_THRESHOLD = 130
# 등락률 상한 컷 — 이미 +15% 이상 상승한 종목은 발굴 의미 없음 (v2.8.3)
_MAX_FLC_PCT = 15.0

_VOLUME_PATH = "/uapi/domestic-stock/v1/quotations/volume-rank"
_POWER_PATH = "/uapi/domestic-stock/v1/ranking/volume-power"
_FLUCT_PATH = "/uapi/domestic-stock/v1/ranking/fluctuation"
_DISPARITY_PATH = "/uapi/domestic-stock/v1/ranking/disparity"
# [v2.7.3 핫픽스] 아래 엔드포인트/TR은 KIS API에 존재하지 않아 항상 404.
# 복구 시 후보 1 (의미 정합): /uapi/domestic-stock/v1/ranking/top-interest-stock (TR: FHPST01800000)
# 복구 시 후보 2 (단순):       /uapi/domestic-stock/v1/ranking/hts-top-view     (TR: HHMCM000100C0)
_HTS_PATH = "/uapi/domestic-stock/v1/quotations/capture-uplmt"  # DEPRECATED — _fetch_hts_rank 참조

_MEDALS = ["🥇", "🥈", "🥉"]


def _korean_hm(time_str: str) -> str:
    """'09:05' → '9시 5분', '14:33' → '2시 33분'. 12시 이상은 오후 변환."""
    if ":" not in time_str:
        return time_str
    h, m = time_str.split(":", 1)
    try:
        h_int = int(h)
        m_int = int(m)
    except ValueError:
        return time_str
    if h_int >= 13:
        h_int -= 12
    return f"{h_int}시 {m_int}분"


def _time_header(time_str: str, kind: str) -> str:
    """발굴/재발굴 헤더 라벨. 12시 발굴은 신뢰도 주석 포함."""
    label = f"{_korean_hm(time_str)} {kind}"
    if ":" in time_str:
        try:
            h = int(time_str.split(":", 1)[0])
            if h == 12:
                return f"{label} (점심 신뢰도 ↓)"
        except ValueError:
            pass
    return label


def _load_today_other_period_discoveries(current_time_str: str) -> dict[str, str]:
    """
    오늘 날짜의 발굴 기록 중 '다른 시간대'에 발굴된 종목 매핑.
    동일 시간대(예: 9시 5분 / 9시 33분 = 같은 9시대)는 ⭐재확인 로직으로 처리되므로 제외.

    반환: {code: '가장 빠른 발굴 시각'}
    """
    from datetime import date as _date
    import json as _json
    log_file = _ROOT / "data" / "discovery_log.json"
    if not log_file.exists() or ":" not in current_time_str:
        return {}
    try:
        data = _json.loads(log_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}

    try:
        cur_h = int(current_time_str.split(":", 1)[0])
    except ValueError:
        return {}

    today = _date.today().isoformat()
    result: dict[str, str] = {}
    for r in data:
        if r.get("date") != today:
            continue
        code = r.get("code")
        disc_t = r.get("disc_time", "")
        if not code or ":" not in disc_t:
            continue
        try:
            h = int(disc_t.split(":", 1)[0])
        except ValueError:
            continue
        # 동일 시간대(같은 시) 발굴은 제외 (재확인 로직과 분리)
        if h == cur_h:
            continue
        # 미래 시점 발굴 제외 (정상 운영에선 불가능, dry-run/재시뮬 안전장치)
        if disc_t > current_time_str:
            continue
        # 같은 종목이 여러 번 발굴된 경우 가장 빠른 시각 보존
        if code not in result or disc_t < result[code]:
            result[code] = disc_t
    return result


def _split_new_and_repeat(
    scored: list[dict[str, Any]],
    current_time_str: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    오늘 다른 시간대에 이미 발굴된 종목과 신규 종목 분리.
    반환: (new_picks, repeat_picks). repeat_picks 항목에는 'prev_disc_time' 필드 추가.
    """
    other = _load_today_other_period_discoveries(current_time_str)
    if not other:
        return list(scored), []
    new_picks: list[dict[str, Any]] = []
    repeat_picks: list[dict[str, Any]] = []
    for item in scored:
        code = item.get("code")
        if code in other:
            item_copy = dict(item)
            item_copy["prev_disc_time"] = other[code]
            repeat_picks.append(item_copy)
        else:
            new_picks.append(item)
    return new_picks, repeat_picks


def run(round_no: int, dry_run: bool = False, debug: bool = False) -> int:
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
        return _run_round1(client, state, dry_run=dry_run)
    if round_no == 2:
        return _run_round2(client, state, dry_run=dry_run, debug=debug)
    if round_no == 3:
        return _run_round3(client, state, dry_run=dry_run)
    if round_no == 4:
        return _run_round4(client, state, dry_run=dry_run, debug=debug)
    if round_no == 5:
        return _run_round5(client, state, dry_run=dry_run)
    if round_no == 6:
        return _run_round6(client, state, dry_run=dry_run, debug=debug)
    if round_no == 7:
        return _run_round7(client, state, dry_run=dry_run)
    if round_no == 8:
        return _run_round8(client, state, dry_run=dry_run, debug=debug)
    if round_no == 9:
        return _run_round9(client, state, dry_run=dry_run)
    if round_no == 10:
        return _run_round10(client, state, dry_run=dry_run, debug=debug)
    if round_no == 11:
        return _run_round11(client, state, dry_run=dry_run)
    if round_no == 12:
        return _run_round12(client, state, dry_run=dry_run, debug=debug)
    if round_no == 13:
        return _run_round13(client, state, dry_run=dry_run)
    if round_no == 14:
        return _run_round14(client, state, dry_run=dry_run, debug=debug)
    if round_no == 15:
        return _run_round15(client, state, dry_run=dry_run)
    if round_no == 16:
        return _run_round16(client, state, dry_run=dry_run, debug=debug)
    if round_no == 17:
        return _run_round17(client, state, dry_run=dry_run)
    if round_no == 18:
        return _run_round18(client, state, dry_run=dry_run, debug=debug)
    if round_no == 19:
        return _run_round19(client, state, dry_run=dry_run)
    if round_no == 20:
        return _run_round20(client, state, dry_run=dry_run, debug=debug)
    if round_no == 21:
        return _run_round21(client, state, dry_run=dry_run)
    if round_no == 22:
        return _run_round22(client, state, dry_run=dry_run, debug=debug)
    if round_no == 23:
        return _run_round23(client, state, dry_run=dry_run)
    if round_no == 24:
        return _run_round24(client, state, dry_run=dry_run, debug=debug)
    if round_no == 25:
        return _run_round25(client, state, dry_run=dry_run)
    if round_no == 26:
        return _run_round26(client, state, dry_run=dry_run, debug=debug)
    raise ValueError(f"unknown round_no: {round_no}")


def _run_round1(client, state: StateManager, dry_run: bool = False) -> int:
    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)

    round1 = {
        "time": datetime.now().strftime("%H:%M"),
        "vol": _extract_codes(volume_rows),
        "pow": _extract_metric_map(power_rows, "tday_rltv"),
        "flc": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "acml_vol": _extract_metric_map(volume_rows, "acml_vol"),
        "names": _extract_name_map(volume_rows, power_rows, fluct_rows),
    }

    # [v2.7.3 핫픽스] dry-run 시 state 저장 스킵 (운영 데이터 오염 방지)
    if dry_run:
        print(
            f"[dry-run] round1 state 저장 스킵 "
            f"(거래량 {len(round1['vol'])} / 체결강도 {len(round1['pow'])} / 등락률 {len(round1['flc'])})",
            file=sys.stderr,
        )
        return 0

    state.update("intraday_discovery", {"round1": round1}, caller="intraday_discovery")
    print(
        f"[완료] round1 저장 완료 "
        f"(거래량 {len(round1['vol'])} / 체결강도 {len(round1['pow'])} / 등락률 {len(round1['flc'])})",
        file=sys.stderr,
    )
    return 0


def _run_round3(client, state: StateManager, dry_run: bool = False) -> int:
    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)

    round3 = {
        "time": datetime.now().strftime("%H:%M"),
        "vol": _extract_codes(volume_rows),
        "pow": _extract_metric_map(power_rows, "tday_rltv"),
        "flc": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "acml_vol": _extract_metric_map(volume_rows, "acml_vol"),
        "names": _extract_name_map(volume_rows, power_rows, fluct_rows),
    }

    # [v2.7.3 핫픽스] dry-run 시 state 저장 스킵
    if dry_run:
        print(
            f"[dry-run] round3 state 저장 스킵 "
            f"(거래량 {len(round3['vol'])} / 체결강도 {len(round3['pow'])} / 등락률 {len(round3['flc'])})",
            file=sys.stderr,
        )
        return 0

    state.update("intraday_discovery", {"round3": round3}, caller="intraday_discovery")
    print(
        f"[완료] round3 저장 완료 "
        f"(거래량 {len(round3['vol'])} / 체결강도 {len(round3['pow'])} / 등락률 {len(round3['flc'])})",
        file=sys.stderr,
    )
    return 0


def _run_round5(client, state: StateManager, dry_run: bool = False) -> int:
    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)

    round5 = {
        "time": datetime.now().strftime("%H:%M"),
        "vol": _extract_codes(volume_rows),
        "pow": _extract_metric_map(power_rows, "tday_rltv"),
        "flc": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "acml_vol": _extract_metric_map(volume_rows, "acml_vol"),
        "names": _extract_name_map(volume_rows, power_rows, fluct_rows),
    }

    # [v2.7.3 핫픽스] dry-run 시 state 저장 스킵
    if dry_run:
        print(
            f"[dry-run] round5 state 저장 스킵 "
            f"(거래량 {len(round5['vol'])} / 체결강도 {len(round5['pow'])} / 등락률 {len(round5['flc'])})",
            file=sys.stderr,
        )
        return 0

    state.update("intraday_discovery", {"round5": round5}, caller="intraday_discovery")
    print(
        f"[완료] round5 저장 완료 "
        f"(거래량 {len(round5['vol'])} / 체결강도 {len(round5['pow'])} / 등락률 {len(round5['flc'])})",
        file=sys.stderr,
    )
    return 0


def _run_round7(client, state: StateManager, dry_run: bool = False) -> int:
    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)

    round7 = {
        "time": datetime.now().strftime("%H:%M"),
        "vol": _extract_codes(volume_rows),
        "pow": _extract_metric_map(power_rows, "tday_rltv"),
        "flc": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "acml_vol": _extract_metric_map(volume_rows, "acml_vol"),
        "names": _extract_name_map(volume_rows, power_rows, fluct_rows),
    }

    # [v2.7.3 핫픽스] dry-run 시 state 저장 스킵
    if dry_run:
        print(
            f"[dry-run] round7 state 저장 스킵 "
            f"(거래량 {len(round7['vol'])} / 체결강도 {len(round7['pow'])} / 등락률 {len(round7['flc'])})",
            file=sys.stderr,
        )
        return 0

    state.update("intraday_discovery", {"round7": round7}, caller="intraday_discovery")
    print(
        f"[완료] round7 저장 완료 "
        f"(거래량 {len(round7['vol'])} / 체결강도 {len(round7['pow'])} / 등락률 {len(round7['flc'])})",
        file=sys.stderr,
    )
    return 0


def _run_round2(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
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
    pow_2 = set(_extract_metric_map(power_rows, "tday_rltv").keys())
    flc_1 = set((round1.get("flc") or {}).keys())
    flc_2 = set(_extract_metric_map(fluct_rows, "prdy_ctrt").keys())

    if debug:
        print("\n" + "=" * 55, file=sys.stderr)
        print("🔬 [DEBUG] 단계별 필터 진단", file=sys.stderr)
        print("=" * 55, file=sys.stderr)
        print(f"  [R1] 거래량 상위:   {len(vol_1)}종목  {sorted(vol_1)[:5]}...", file=sys.stderr)
        print(f"  [R2] 거래량 상위:   {len(vol_2)}종목", file=sys.stderr)
        print(f"  [R1] 체결강도 상위: {len(pow_1)}종목", file=sys.stderr)
        print(f"  [R2] 체결강도 상위: {len(pow_2)}종목", file=sys.stderr)
        print(f"  [R1] 등락률 상위:   {len(flc_1)}종목", file=sys.stderr)
        print(f"  [R2] 등락률 상위:   {len(flc_2)}종목", file=sys.stderr)
        # 단계별 교집합
        step1 = vol_1 & vol_2
        step2 = step1 & pow_1 & pow_2
        step3 = step2 & flc_1 & flc_2
        print(f"\n  ① 거래량 R1∩R2:              {len(step1)}종목  {sorted(step1)}", file=sys.stderr)
        print(f"  ② ①∩체결강도R1∩R2:          {len(step2)}종목  {sorted(step2)}", file=sys.stderr)
        print(f"  ③ ②∩등락률R1∩R2 (교집합):   {len(step3)}종목  {sorted(step3)}", file=sys.stderr)

    candidates = vol_1 & vol_2 & pow_1 & pow_2 & flc_1 & flc_2

    overheated = {
        code for code, value in _extract_metric_map(disparity_rows, "d20_dsrt").items()
        if value >= _DISPARITY_OVERHEATED_THRESHOLD
    }

    if debug:
        print(f"\n  ④ 과열 제외 (이격도≥120):    {len(candidates & overheated)}종목 제외  {sorted(candidates & overheated)}", file=sys.stderr)

    filtered = sorted(code for code in candidates if code not in overheated)

    if debug:
        print(f"  ⑤ 최종 후보 (필터 후):       {len(filtered)}종목  {filtered}", file=sys.stderr)

    hts_top = _extract_codes(hts_rows)[:_HTS_TOP_N]
    hts_ranks = {code: idx + 1 for idx, code in enumerate(hts_top)}

    names = {}
    names.update(round1.get("names") or {})
    names.update(_extract_name_map(volume_rows, power_rows, fluct_rows, disparity_rows, hts_rows))

    metrics = {
        "pow_1": round1.get("pow", {}) or {},
        "pow_2": _extract_metric_map(power_rows, "tday_rltv"),
        "flc_1": round1.get("flc", {}) or {},
        "flc_2": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "vol_1": round1.get("acml_vol", {}) or {},
        "vol_2": _extract_metric_map(volume_rows, "acml_vol"),
        "disparity": _extract_metric_map(disparity_rows, "d20_dsrt"),
    }

    scored = []
    skipped_score = []
    for code in filtered:
        item = _score_candidate(code, names, metrics, hts_ranks)
        if item is not None:
            scored.append(item)
        else:
            skipped_score.append(code)

    if debug:
        print(f"\n  ⑥ 점수 산정 탈락 (체결강도 미상승): {len(skipped_score)}종목  {skipped_score}", file=sys.stderr)
        print(f"  ⑦ 최종 점수 통과:                 {len(scored)}종목", file=sys.stderr)
        for item in sorted(scored, key=lambda x: -x["score"]):
            print(
                f"     {item['name']}({item['code']})  "
                f"점수:{item['score']}  "
                f"체결강도:{item['pow_2']:.0f}(R1:{item['pow_1']:.0f})  "
                f"등락률:{item['flc_2']:+.1f}%(R1:{item['flc_1']:+.1f}%)",
                file=sys.stderr,
            )
        print("=" * 55 + "\n", file=sys.stderr)

    scored.sort(key=lambda item: (-item["score"], -item["pow_2"], -item["flc_2"], item["code"]))
    top_picks = scored[:3]

    round2 = {
        "time": datetime.now().strftime("%H:%M"),
        "candidate_count": len(scored),
        "overheated_count": len(candidates & overheated),
        "candidates": [
            {
                "code":      item["code"],
                "name":      item["name"],
                "score":     item["score"],
                "pow_2":     item["pow_2"],
                "pow_delta": item["pow_delta"],
                "flc_2":     item["flc_2"],
                "flc_delta": item["flc_delta"],
                "vol_delta": item["vol_delta"],
                "hts_rank":  item["hts_rank"],
                "disc_price": _extract_metric_map(volume_rows, "stck_prpr").get(item["code"], 0),
            }
            for item in scored
        ],
        "top_picks": [item["code"] for item in top_picks],
    }

    # [v2.7.3 핫픽스] dry-run 시 state 저장 및 discovery_log 스킵
    if not dry_run:
        state.update("intraday_discovery", {"round2": round2}, caller="intraday_discovery")
        _save_discovery_log(scored, volume_rows)
    else:
        print(f"[dry-run] round2 state/discovery_log 저장 스킵 ({len(scored)}종목)", file=sys.stderr)

    message = _build_message(round2["time"], top_picks, len(scored), all_scored=scored)
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


def _run_round4(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    round3 = state.get("intraday_discovery.round3")
    if not isinstance(round3, dict):
        print("[오류] round3 데이터가 없습니다. 먼저 --round 3 을 실행하세요.", file=sys.stderr)
        return 1

    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)
    disparity_rows = _fetch_disparity_rank(client)
    hts_rows = _fetch_hts_rank(client)

    vol_3 = set(round3.get("vol", []))
    vol_4 = set(_extract_codes(volume_rows))
    pow_3 = set((round3.get("pow") or {}).keys())
    pow_4 = set(_extract_metric_map(power_rows, "tday_rltv").keys())
    flc_3 = set((round3.get("flc") or {}).keys())
    flc_4 = set(_extract_metric_map(fluct_rows, "prdy_ctrt").keys())

    if debug:
        print("\n" + "=" * 55, file=sys.stderr)
        print("🔬 [DEBUG] round4 단계별 필터 진단", file=sys.stderr)
        print("=" * 55, file=sys.stderr)
        print(f"  [R3] 거래량 상위:   {len(vol_3)}종목  {sorted(vol_3)[:5]}...", file=sys.stderr)
        print(f"  [R4] 거래량 상위:   {len(vol_4)}종목", file=sys.stderr)
        print(f"  [R3] 체결강도 상위: {len(pow_3)}종목", file=sys.stderr)
        print(f"  [R4] 체결강도 상위: {len(pow_4)}종목", file=sys.stderr)
        print(f"  [R3] 등락률 상위:   {len(flc_3)}종목", file=sys.stderr)
        print(f"  [R4] 등락률 상위:   {len(flc_4)}종목", file=sys.stderr)
        step1 = vol_3 & vol_4
        step2 = step1 & pow_3 & pow_4
        step3 = step2 & flc_3 & flc_4
        print(f"\n  ① 거래량 R3∩R4:              {len(step1)}종목  {sorted(step1)}", file=sys.stderr)
        print(f"  ② ①∩체결강도R3∩R4:          {len(step2)}종목  {sorted(step2)}", file=sys.stderr)
        print(f"  ③ ②∩등락률R3∩R4 (교집합):   {len(step3)}종목  {sorted(step3)}", file=sys.stderr)

    candidates = vol_3 & vol_4 & pow_3 & pow_4 & flc_3 & flc_4
    overheated = {
        code for code, value in _extract_metric_map(disparity_rows, "d20_dsrt").items()
        if value >= _DISPARITY_OVERHEATED_THRESHOLD
    }

    if debug:
        print(f"\n  ④ 과열 제외 (이격도≥120):    {len(candidates & overheated)}종목 제외  {sorted(candidates & overheated)}", file=sys.stderr)

    filtered = sorted(code for code in candidates if code not in overheated)

    if debug:
        print(f"  ⑤ 최종 후보 (필터 후):       {len(filtered)}종목  {filtered}", file=sys.stderr)

    hts_top = _extract_codes(hts_rows)[:_HTS_TOP_N]
    hts_ranks = {code: idx + 1 for idx, code in enumerate(hts_top)}

    names = {}
    names.update(round3.get("names") or {})
    names.update(_extract_name_map(volume_rows, power_rows, fluct_rows, disparity_rows, hts_rows))

    metrics = {
        "pow_1": round3.get("pow", {}) or {},
        "pow_2": _extract_metric_map(power_rows, "tday_rltv"),
        "flc_1": round3.get("flc", {}) or {},
        "flc_2": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "vol_1": round3.get("acml_vol", {}) or {},
        "vol_2": _extract_metric_map(volume_rows, "acml_vol"),
        "disparity": _extract_metric_map(disparity_rows, "d20_dsrt"),
    }

    scored = []
    skipped_score = []
    for code in filtered:
        item = _score_candidate(code, names, metrics, hts_ranks)
        if item is not None:
            scored.append(item)
        else:
            skipped_score.append(code)

    round2 = state.get("intraday_discovery.round2") or {}
    if not isinstance(round2, dict) or not round2:
        print("[경고] round2 데이터 없음 — 오전 발굴 추적 및 재확인 태그 생략", file=sys.stderr)
    morning_candidates = round2.get("candidates", []) if isinstance(round2, dict) else []
    morning_codes = {item.get("code") for item in morning_candidates if item.get("code")}
    for item in scored:
        item["is_reconfirmed"] = item["code"] in morning_codes

    if debug:
        print(f"\n  ⑥ 점수 산정 탈락:                 {len(skipped_score)}종목  {skipped_score}", file=sys.stderr)
        print(f"  ⑦ 최종 점수 통과:                 {len(scored)}종목", file=sys.stderr)
        for item in sorted(scored, key=lambda x: -x["score"]):
            reconfirmed = " ⭐재확인" if item.get("is_reconfirmed") else ""
            print(
                f"     {item['name']}({item['code']}){reconfirmed}  "
                f"점수:{item['score']}  "
                f"체결강도:{item['pow_2']:.0f}(R3:{item['pow_1']:.0f})  "
                f"등락률:{item['flc_2']:+.1f}%(R3:{item['flc_1']:+.1f}%)",
                file=sys.stderr,
            )
        print("=" * 55 + "\n", file=sys.stderr)

    scored.sort(key=lambda item: (-item["score"], -(1 if item.get("is_reconfirmed") else 0), -item["pow_2"], -item["flc_2"], item["code"]))
    top_picks = scored[:3]
    tracking = _fetch_morning_tracking(client, state)

    round4 = {
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
                "is_reconfirmed": item.get("is_reconfirmed", False),
            }
            for item in scored
        ],
        "top_picks": [item["code"] for item in top_picks],
        "tracking": tracking,
    }

    # [v2.7.3 핫픽스] dry-run 시 state 저장 스킵
    if not dry_run:
        state.update("intraday_discovery", {"round4": round4}, caller="intraday_discovery")
    else:
        print(f"[dry-run] round4 state 저장 스킵 ({len(scored)}종목)", file=sys.stderr)

    message = _build_message_round4(round4["time"], top_picks, len(scored), tracking=tracking, all_scored=scored)
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


def _run_round6(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    round5 = state.get("intraday_discovery.round5")
    if not isinstance(round5, dict):
        print("[오류] round5 데이터가 없습니다. 먼저 --round 5 를 실행하세요.", file=sys.stderr)
        return 1

    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)
    disparity_rows = _fetch_disparity_rank(client)
    hts_rows = _fetch_hts_rank(client)

    vol_5 = set(round5.get("vol", []))
    vol_6 = set(_extract_codes(volume_rows))
    pow_5 = set((round5.get("pow") or {}).keys())
    pow_6 = set(_extract_metric_map(power_rows, "tday_rltv").keys())
    flc_5 = set((round5.get("flc") or {}).keys())
    flc_6 = set(_extract_metric_map(fluct_rows, "prdy_ctrt").keys())

    if debug:
        print("\n" + "=" * 55, file=sys.stderr)
        print("🔬 [DEBUG] round6 단계별 필터 진단", file=sys.stderr)
        print("=" * 55, file=sys.stderr)
        print(f"  [R5] 거래량 상위:   {len(vol_5)}종목  {sorted(vol_5)[:5]}...", file=sys.stderr)
        print(f"  [R6] 거래량 상위:   {len(vol_6)}종목", file=sys.stderr)
        print(f"  [R5] 체결강도 상위: {len(pow_5)}종목", file=sys.stderr)
        print(f"  [R6] 체결강도 상위: {len(pow_6)}종목", file=sys.stderr)
        print(f"  [R5] 등락률 상위:   {len(flc_5)}종목", file=sys.stderr)
        print(f"  [R6] 등락률 상위:   {len(flc_6)}종목", file=sys.stderr)
        step1 = vol_5 & vol_6
        step2 = step1 & pow_5 & pow_6
        step3 = step2 & flc_5 & flc_6
        print(f"\n  ① 거래량 R5∩R6:              {len(step1)}종목  {sorted(step1)}", file=sys.stderr)
        print(f"  ② ①∩체결강도R5∩R6:          {len(step2)}종목  {sorted(step2)}", file=sys.stderr)
        print(f"  ③ ②∩등락률R5∩R6 (교집합):   {len(step3)}종목  {sorted(step3)}", file=sys.stderr)

    candidates = vol_5 & vol_6 & pow_5 & pow_6 & flc_5 & flc_6
    overheated = {
        code for code, value in _extract_metric_map(disparity_rows, "d20_dsrt").items()
        if value >= _DISPARITY_OVERHEATED_THRESHOLD
    }

    if debug:
        print(f"\n  ④ 과열 제외 (이격도≥120):    {len(candidates & overheated)}종목 제외  {sorted(candidates & overheated)}", file=sys.stderr)

    filtered = sorted(code for code in candidates if code not in overheated)

    if debug:
        print(f"  ⑤ 최종 후보 (필터 후):       {len(filtered)}종목  {filtered}", file=sys.stderr)

    hts_top = _extract_codes(hts_rows)[:_HTS_TOP_N]
    hts_ranks = {code: idx + 1 for idx, code in enumerate(hts_top)}

    names = {}
    names.update(round5.get("names") or {})
    names.update(_extract_name_map(volume_rows, power_rows, fluct_rows, disparity_rows, hts_rows))

    metrics = {
        "pow_1": round5.get("pow", {}) or {},
        "pow_2": _extract_metric_map(power_rows, "tday_rltv"),
        "flc_1": round5.get("flc", {}) or {},
        "flc_2": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "vol_1": round5.get("acml_vol", {}) or {},
        "vol_2": _extract_metric_map(volume_rows, "acml_vol"),
        "disparity": _extract_metric_map(disparity_rows, "d20_dsrt"),
    }

    scored = []
    skipped_score = []
    for code in filtered:
        item = _score_candidate(code, names, metrics, hts_ranks)
        if item is not None:
            scored.append(item)
        else:
            skipped_score.append(code)

    if debug:
        print(f"\n  ⑥ 점수 산정 탈락:                 {len(skipped_score)}종목  {skipped_score}", file=sys.stderr)
        print(f"  ⑦ 최종 점수 통과:                 {len(scored)}종목", file=sys.stderr)
        for item in sorted(scored, key=lambda x: -x["score"]):
            print(
                f"     {item['name']}({item['code']})  "
                f"점수:{item['score']}  "
                f"체결강도:{item['pow_2']:.0f}(R5:{item['pow_1']:.0f})  "
                f"등락률:{item['flc_2']:+.1f}%(R5:{item['flc_1']:+.1f}%)",
                file=sys.stderr,
            )
        print("=" * 55 + "\n", file=sys.stderr)

    scored.sort(key=lambda item: (-item["score"], -item["pow_2"], -item["flc_2"], item["code"]))
    top_picks = scored[:3]

    round6 = {
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
                "disc_price": _extract_metric_map(volume_rows, "stck_prpr").get(item["code"], 0),
            }
            for item in scored
        ],
        "top_picks": [item["code"] for item in top_picks],
    }

    # [v2.7.3 핫픽스] dry-run 시 state 저장 및 discovery_log 스킵
    if not dry_run:
        state.update("intraday_discovery", {"round6": round6}, caller="intraday_discovery")
        _save_discovery_log(scored, volume_rows, session="afternoon")
    else:
        print(f"[dry-run] round6 state/discovery_log 저장 스킵 ({len(scored)}종목)", file=sys.stderr)

    message = _build_message_afternoon(round6["time"], top_picks, len(scored), all_scored=scored)
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


def _run_round8(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    round7 = state.get("intraday_discovery.round7")
    if not isinstance(round7, dict):
        print("[오류] round7 데이터가 없습니다. 먼저 --round 7 을 실행하세요.", file=sys.stderr)
        return 1

    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)
    disparity_rows = _fetch_disparity_rank(client)
    hts_rows = _fetch_hts_rank(client)

    vol_7 = set(round7.get("vol", []))
    vol_8 = set(_extract_codes(volume_rows))
    pow_7 = set((round7.get("pow") or {}).keys())
    pow_8 = set(_extract_metric_map(power_rows, "tday_rltv").keys())
    flc_7 = set((round7.get("flc") or {}).keys())
    flc_8 = set(_extract_metric_map(fluct_rows, "prdy_ctrt").keys())

    if debug:
        print("\n" + "=" * 55, file=sys.stderr)
        print("🔬 [DEBUG] round8 단계별 필터 진단", file=sys.stderr)
        print("=" * 55, file=sys.stderr)
        print(f"  [R7] 거래량 상위:   {len(vol_7)}종목  {sorted(vol_7)[:5]}...", file=sys.stderr)
        print(f"  [R8] 거래량 상위:   {len(vol_8)}종목", file=sys.stderr)
        print(f"  [R7] 체결강도 상위: {len(pow_7)}종목", file=sys.stderr)
        print(f"  [R8] 체결강도 상위: {len(pow_8)}종목", file=sys.stderr)
        print(f"  [R7] 등락률 상위:   {len(flc_7)}종목", file=sys.stderr)
        print(f"  [R8] 등락률 상위:   {len(flc_8)}종목", file=sys.stderr)
        step1 = vol_7 & vol_8
        step2 = step1 & pow_7 & pow_8
        step3 = step2 & flc_7 & flc_8
        print(f"\n  ① 거래량 R7∩R8:              {len(step1)}종목  {sorted(step1)}", file=sys.stderr)
        print(f"  ② ①∩체결강도R7∩R8:          {len(step2)}종목  {sorted(step2)}", file=sys.stderr)
        print(f"  ③ ②∩등락률R7∩R8 (교집합):   {len(step3)}종목  {sorted(step3)}", file=sys.stderr)

    candidates = vol_7 & vol_8 & pow_7 & pow_8 & flc_7 & flc_8
    overheated = {
        code for code, value in _extract_metric_map(disparity_rows, "d20_dsrt").items()
        if value >= _DISPARITY_OVERHEATED_THRESHOLD
    }

    if debug:
        print(f"\n  ④ 과열 제외 (이격도≥120):    {len(candidates & overheated)}종목 제외  {sorted(candidates & overheated)}", file=sys.stderr)

    filtered = sorted(code for code in candidates if code not in overheated)

    if debug:
        print(f"  ⑤ 최종 후보 (필터 후):       {len(filtered)}종목  {filtered}", file=sys.stderr)

    hts_top = _extract_codes(hts_rows)[:_HTS_TOP_N]
    hts_ranks = {code: idx + 1 for idx, code in enumerate(hts_top)}

    names = {}
    names.update(round7.get("names") or {})
    names.update(_extract_name_map(volume_rows, power_rows, fluct_rows, disparity_rows, hts_rows))

    metrics = {
        "pow_1": round7.get("pow", {}) or {},
        "pow_2": _extract_metric_map(power_rows, "tday_rltv"),
        "flc_1": round7.get("flc", {}) or {},
        "flc_2": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "vol_1": round7.get("acml_vol", {}) or {},
        "vol_2": _extract_metric_map(volume_rows, "acml_vol"),
        "disparity": _extract_metric_map(disparity_rows, "d20_dsrt"),
    }

    scored = []
    skipped_score = []
    for code in filtered:
        item = _score_candidate(code, names, metrics, hts_ranks)
        if item is not None:
            scored.append(item)
        else:
            skipped_score.append(code)

    round6 = state.get("intraday_discovery.round6") or {}
    if not isinstance(round6, dict) or not round6:
        print("[경고] round6 데이터 없음 — 오후 발굴 추적 및 재확인 태그 생략", file=sys.stderr)
    afternoon_candidates = round6.get("candidates", []) if isinstance(round6, dict) else []
    afternoon_codes = {item.get("code") for item in afternoon_candidates if item.get("code")}
    for item in scored:
        item["is_reconfirmed"] = item["code"] in afternoon_codes

    if debug:
        print(f"\n  ⑥ 점수 산정 탈락:                 {len(skipped_score)}종목  {skipped_score}", file=sys.stderr)
        print(f"  ⑦ 최종 점수 통과:                 {len(scored)}종목", file=sys.stderr)
        for item in sorted(scored, key=lambda x: -x["score"]):
            reconfirmed = " ⭐재확인" if item.get("is_reconfirmed") else ""
            print(
                f"     {item['name']}({item['code']}){reconfirmed}  "
                f"점수:{item['score']}  "
                f"체결강도:{item['pow_2']:.0f}(R7:{item['pow_1']:.0f})  "
                f"등락률:{item['flc_2']:+.1f}%(R7:{item['flc_1']:+.1f}%)",
                file=sys.stderr,
            )
        print("=" * 55 + "\n", file=sys.stderr)

    scored.sort(key=lambda item: (-item["score"], -(1 if item.get("is_reconfirmed") else 0), -item["pow_2"], -item["flc_2"], item["code"]))
    top_picks = scored[:3]
    tracking = _fetch_afternoon_tracking(client, state)

    round8 = {
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
                "is_reconfirmed": item.get("is_reconfirmed", False),
            }
            for item in scored
        ],
        "top_picks": [item["code"] for item in top_picks],
        "tracking": tracking,
    }

    # [v2.7.3 핫픽스] dry-run 시 state 저장 스킵
    if not dry_run:
        state.update("intraday_discovery", {"round8": round8}, caller="intraday_discovery")
    else:
        print(f"[dry-run] round8 state 저장 스킵 ({len(scored)}종목)", file=sys.stderr)

    message = _build_message_round8(round8["time"], top_picks, len(scored), tracking=tracking, all_scored=scored)
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


def _run_collection_round(client, state: StateManager, round_no: int, dry_run: bool = False) -> int:
    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)

    round_data = {
        "time": datetime.now().strftime("%H:%M"),
        "vol": _extract_codes(volume_rows),
        "pow": _extract_metric_map(power_rows, "tday_rltv"),
        "flc": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "acml_vol": _extract_metric_map(volume_rows, "acml_vol"),
        "names": _extract_name_map(volume_rows, power_rows, fluct_rows),
    }

    if dry_run:
        print(
            f"[dry-run] round{round_no} state 저장 스킵 "
            f"(거래량 {len(round_data['vol'])} / 체결강도 {len(round_data['pow'])} / 등락률 {len(round_data['flc'])})",
            file=sys.stderr,
        )
        return 0

    state.update("intraday_discovery", {f"round{round_no}": round_data}, caller="intraday_discovery")
    print(
        f"[완료] round{round_no} 저장 완료 "
        f"(거래량 {len(round_data['vol'])} / 체결강도 {len(round_data['pow'])} / 등락률 {len(round_data['flc'])})",
        file=sys.stderr,
    )
    return 0


def _run_discovery_round(
    client,
    state: StateManager,
    first_round_no: int,
    round_no: int,
    session: str,
    dry_run: bool = False,
    debug: bool = False,
) -> int:
    round1 = state.get(f"intraday_discovery.round{first_round_no}")
    if not isinstance(round1, dict):
        print(f"[오류] round{first_round_no} 데이터가 없습니다. 먼저 --round {first_round_no} 을 실행하세요.", file=sys.stderr)
        return 1

    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)
    disparity_rows = _fetch_disparity_rank(client)
    hts_rows = _fetch_hts_rank(client)

    vol_1 = set(round1.get("vol", []))
    vol_2 = set(_extract_codes(volume_rows))
    pow_1 = set((round1.get("pow") or {}).keys())
    pow_2 = set(_extract_metric_map(power_rows, "tday_rltv").keys())
    flc_1 = set((round1.get("flc") or {}).keys())
    flc_2 = set(_extract_metric_map(fluct_rows, "prdy_ctrt").keys())

    if debug:
        print("\n" + "=" * 55, file=sys.stderr)
        print(f"🔬 [DEBUG] round{round_no} 단계별 필터 진단", file=sys.stderr)
        print("=" * 55, file=sys.stderr)
        print(f"  [R{first_round_no}] 거래량 상위:   {len(vol_1)}종목  {sorted(vol_1)[:5]}...", file=sys.stderr)
        print(f"  [R{round_no}] 거래량 상위:   {len(vol_2)}종목", file=sys.stderr)
        print(f"  [R{first_round_no}] 체결강도 상위: {len(pow_1)}종목", file=sys.stderr)
        print(f"  [R{round_no}] 체결강도 상위: {len(pow_2)}종목", file=sys.stderr)
        print(f"  [R{first_round_no}] 등락률 상위:   {len(flc_1)}종목", file=sys.stderr)
        print(f"  [R{round_no}] 등락률 상위:   {len(flc_2)}종목", file=sys.stderr)
        step1 = vol_1 & vol_2
        step2 = step1 & pow_1 & pow_2
        step3 = step2 & flc_1 & flc_2
        print(f"\n  ① 거래량 R{first_round_no}∩R{round_no}:              {len(step1)}종목  {sorted(step1)}", file=sys.stderr)
        print(f"  ② ①∩체결강도R{first_round_no}∩R{round_no}:          {len(step2)}종목  {sorted(step2)}", file=sys.stderr)
        print(f"  ③ ②∩등락률R{first_round_no}∩R{round_no} (교집합):   {len(step3)}종목  {sorted(step3)}", file=sys.stderr)

    candidates = vol_1 & vol_2 & pow_1 & pow_2 & flc_1 & flc_2

    overheated = {
        code for code, value in _extract_metric_map(disparity_rows, "d20_dsrt").items()
        if value >= _DISPARITY_OVERHEATED_THRESHOLD
    }

    if debug:
        print(
            f"\n  ④ 과열 제외 (이격도≥{_DISPARITY_OVERHEATED_THRESHOLD}):    "
            f"{len(candidates & overheated)}종목 제외  {sorted(candidates & overheated)}",
            file=sys.stderr,
        )

    filtered = sorted(code for code in candidates if code not in overheated)

    if debug:
        print(f"  ⑤ 최종 후보 (필터 후):       {len(filtered)}종목  {filtered}", file=sys.stderr)

    hts_top = _extract_codes(hts_rows)[:_HTS_TOP_N]
    hts_ranks = {code: idx + 1 for idx, code in enumerate(hts_top)}

    names = {}
    names.update(round1.get("names") or {})
    names.update(_extract_name_map(volume_rows, power_rows, fluct_rows, disparity_rows, hts_rows))

    metrics = {
        "pow_1": round1.get("pow", {}) or {},
        "pow_2": _extract_metric_map(power_rows, "tday_rltv"),
        "flc_1": round1.get("flc", {}) or {},
        "flc_2": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "vol_1": round1.get("acml_vol", {}) or {},
        "vol_2": _extract_metric_map(volume_rows, "acml_vol"),
        "disparity": _extract_metric_map(disparity_rows, "d20_dsrt"),
    }

    scored = []
    skipped_score = []
    for code in filtered:
        item = _score_candidate(code, names, metrics, hts_ranks)
        if item is not None:
            scored.append(item)
        else:
            skipped_score.append(code)

    if debug:
        print(f"\n  ⑥ 점수 산정 탈락 (체결강도 미상승): {len(skipped_score)}종목  {skipped_score}", file=sys.stderr)
        print(f"  ⑦ 최종 점수 통과:                 {len(scored)}종목", file=sys.stderr)
        for item in sorted(scored, key=lambda x: -x["score"]):
            print(
                f"     {item['name']}({item['code']})  "
                f"점수:{item['score']}  "
                f"체결강도:{item['pow_2']:.0f}(R{first_round_no}:{item['pow_1']:.0f})  "
                f"등락률:{item['flc_2']:+.1f}%(R{first_round_no}:{item['flc_1']:+.1f}%)",
                file=sys.stderr,
            )
        print("=" * 55 + "\n", file=sys.stderr)

    scored.sort(key=lambda item: (-item["score"], -item["pow_2"], -item["flc_2"], item["code"]))
    top_picks = scored[:3]

    round_data = {
        "time": datetime.now().strftime("%H:%M"),
        "candidate_count": len(scored),
        "overheated_count": len(candidates & overheated),
        "candidates": [
            {
                "code":      item["code"],
                "name":      item["name"],
                "score":     item["score"],
                "pow_2":     item["pow_2"],
                "pow_delta": item["pow_delta"],
                "flc_2":     item["flc_2"],
                "flc_delta": item["flc_delta"],
                "vol_delta": item["vol_delta"],
                "hts_rank":  item["hts_rank"],
                "disc_price": _extract_metric_map(volume_rows, "stck_prpr").get(item["code"], 0),
            }
            for item in scored
        ],
        "top_picks": [item["code"] for item in top_picks],
    }

    if not dry_run:
        state.update("intraday_discovery", {f"round{round_no}": round_data}, caller="intraday_discovery")
        _save_discovery_log(scored, volume_rows, session=session)
    else:
        print(f"[dry-run] round{round_no} state/discovery_log 저장 스킵 ({len(scored)}종목)", file=sys.stderr)

    message = _build_message(round_data["time"], top_picks, len(scored), all_scored=scored)
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


def _run_rediscovery_round(
    client,
    state: StateManager,
    first_round_no: int,
    source_round_no: int,
    round_no: int,
    dry_run: bool = False,
    debug: bool = False,
) -> int:
    round1 = state.get(f"intraday_discovery.round{first_round_no}")
    if not isinstance(round1, dict):
        print(f"[오류] round{first_round_no} 데이터가 없습니다. 먼저 --round {first_round_no} 을 실행하세요.", file=sys.stderr)
        return 1

    volume_rows = _fetch_volume_rank(client)
    power_rows = _fetch_power_rank(client)
    fluct_rows = _fetch_fluctuation_rank(client)
    disparity_rows = _fetch_disparity_rank(client)
    hts_rows = _fetch_hts_rank(client)

    vol_1 = set(round1.get("vol", []))
    vol_2 = set(_extract_codes(volume_rows))
    pow_1 = set((round1.get("pow") or {}).keys())
    pow_2 = set(_extract_metric_map(power_rows, "tday_rltv").keys())
    flc_1 = set((round1.get("flc") or {}).keys())
    flc_2 = set(_extract_metric_map(fluct_rows, "prdy_ctrt").keys())

    if debug:
        print("\n" + "=" * 55, file=sys.stderr)
        print(f"🔬 [DEBUG] round{round_no} 단계별 필터 진단", file=sys.stderr)
        print("=" * 55, file=sys.stderr)
        print(f"  [R{first_round_no}] 거래량 상위:   {len(vol_1)}종목  {sorted(vol_1)[:5]}...", file=sys.stderr)
        print(f"  [R{round_no}] 거래량 상위:   {len(vol_2)}종목", file=sys.stderr)
        print(f"  [R{first_round_no}] 체결강도 상위: {len(pow_1)}종목", file=sys.stderr)
        print(f"  [R{round_no}] 체결강도 상위: {len(pow_2)}종목", file=sys.stderr)
        print(f"  [R{first_round_no}] 등락률 상위:   {len(flc_1)}종목", file=sys.stderr)
        print(f"  [R{round_no}] 등락률 상위:   {len(flc_2)}종목", file=sys.stderr)
        step1 = vol_1 & vol_2
        step2 = step1 & pow_1 & pow_2
        step3 = step2 & flc_1 & flc_2
        print(f"\n  ① 거래량 R{first_round_no}∩R{round_no}:              {len(step1)}종목  {sorted(step1)}", file=sys.stderr)
        print(f"  ② ①∩체결강도R{first_round_no}∩R{round_no}:          {len(step2)}종목  {sorted(step2)}", file=sys.stderr)
        print(f"  ③ ②∩등락률R{first_round_no}∩R{round_no} (교집합):   {len(step3)}종목  {sorted(step3)}", file=sys.stderr)

    candidates = vol_1 & vol_2 & pow_1 & pow_2 & flc_1 & flc_2
    overheated = {
        code for code, value in _extract_metric_map(disparity_rows, "d20_dsrt").items()
        if value >= _DISPARITY_OVERHEATED_THRESHOLD
    }

    if debug:
        print(
            f"\n  ④ 과열 제외 (이격도≥{_DISPARITY_OVERHEATED_THRESHOLD}):    "
            f"{len(candidates & overheated)}종목 제외  {sorted(candidates & overheated)}",
            file=sys.stderr,
        )

    filtered = sorted(code for code in candidates if code not in overheated)

    if debug:
        print(f"  ⑤ 최종 후보 (필터 후):       {len(filtered)}종목  {filtered}", file=sys.stderr)

    hts_top = _extract_codes(hts_rows)[:_HTS_TOP_N]
    hts_ranks = {code: idx + 1 for idx, code in enumerate(hts_top)}

    names = {}
    names.update(round1.get("names") or {})
    names.update(_extract_name_map(volume_rows, power_rows, fluct_rows, disparity_rows, hts_rows))

    metrics = {
        "pow_1": round1.get("pow", {}) or {},
        "pow_2": _extract_metric_map(power_rows, "tday_rltv"),
        "flc_1": round1.get("flc", {}) or {},
        "flc_2": _extract_metric_map(fluct_rows, "prdy_ctrt"),
        "vol_1": round1.get("acml_vol", {}) or {},
        "vol_2": _extract_metric_map(volume_rows, "acml_vol"),
        "disparity": _extract_metric_map(disparity_rows, "d20_dsrt"),
    }

    scored = []
    skipped_score = []
    for code in filtered:
        item = _score_candidate(code, names, metrics, hts_ranks)
        if item is not None:
            scored.append(item)
        else:
            skipped_score.append(code)

    source_round = state.get(f"intraday_discovery.round{source_round_no}") or {}
    if not isinstance(source_round, dict) or not source_round:
        print(f"[경고] round{source_round_no} 데이터 없음 — 발굴 추적 및 재확인 태그 생략", file=sys.stderr)
    source_candidates = source_round.get("candidates", []) if isinstance(source_round, dict) else []
    source_codes = {item.get("code") for item in source_candidates if item.get("code")}
    for item in scored:
        item["is_reconfirmed"] = item["code"] in source_codes

    if debug:
        print(f"\n  ⑥ 점수 산정 탈락:                 {len(skipped_score)}종목  {skipped_score}", file=sys.stderr)
        print(f"  ⑦ 최종 점수 통과:                 {len(scored)}종목", file=sys.stderr)
        for item in sorted(scored, key=lambda x: -x["score"]):
            reconfirmed = " ⭐재확인" if item.get("is_reconfirmed") else ""
            print(
                f"     {item['name']}({item['code']}){reconfirmed}  "
                f"점수:{item['score']}  "
                f"체결강도:{item['pow_2']:.0f}(R{first_round_no}:{item['pow_1']:.0f})  "
                f"등락률:{item['flc_2']:+.1f}%(R{first_round_no}:{item['flc_1']:+.1f}%)",
                file=sys.stderr,
            )
        print("=" * 55 + "\n", file=sys.stderr)

    scored.sort(key=lambda item: (-item["score"], -(1 if item.get("is_reconfirmed") else 0), -item["pow_2"], -item["flc_2"], item["code"]))
    top_picks = scored[:3]
    tracking = _track_recent_picks(client, source_round) if isinstance(source_round, dict) and source_round else None

    round_data = {
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
                "is_reconfirmed": item.get("is_reconfirmed", False),
            }
            for item in scored
        ],
        "top_picks": [item["code"] for item in top_picks],
        "tracking": tracking,
    }

    if not dry_run:
        state.update("intraday_discovery", {f"round{round_no}": round_data}, caller="intraday_discovery")
    else:
        print(f"[dry-run] round{round_no} state 저장 스킵 ({len(scored)}종목)", file=sys.stderr)

    message = _build_message_round4(round_data["time"], top_picks, len(scored), tracking=tracking, all_scored=scored)
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


def _run_round9(client, state: StateManager, dry_run: bool = False) -> int:
    return _run_collection_round(client, state, 9, dry_run=dry_run)


def _run_round10(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """10시 발굴 2차 — round9 데이터 + 현재 데이터 교집합."""
    return _run_discovery_round(client, state, 9, 10, "morning_10", dry_run=dry_run, debug=debug)


def _run_round11(client, state: StateManager, dry_run: bool = False) -> int:
    return _run_collection_round(client, state, 11, dry_run=dry_run)


def _run_round12(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """10시 재발굴 — round11 데이터 + 현재 + round10 결과 추적."""
    return _run_rediscovery_round(client, state, 11, 10, 12, dry_run=dry_run, debug=debug)


def _run_round13(client, state: StateManager, dry_run: bool = False) -> int:
    return _run_collection_round(client, state, 13, dry_run=dry_run)


def _run_round14(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """11시 발굴 2차 — round13 데이터 + 현재 데이터 교집합."""
    return _run_discovery_round(client, state, 13, 14, "morning_11", dry_run=dry_run, debug=debug)


def _run_round15(client, state: StateManager, dry_run: bool = False) -> int:
    return _run_collection_round(client, state, 15, dry_run=dry_run)


def _run_round16(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """11시 재발굴 — round15 데이터 + 현재 + round14 결과 추적."""
    return _run_rediscovery_round(client, state, 15, 14, 16, dry_run=dry_run, debug=debug)


def _run_round17(client, state: StateManager, dry_run: bool = False) -> int:
    return _run_collection_round(client, state, 17, dry_run=dry_run)


def _run_round18(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """12시 발굴 2차 — round17 데이터 + 현재 데이터 교집합."""
    return _run_discovery_round(client, state, 17, 18, "lunch_12", dry_run=dry_run, debug=debug)


def _run_round19(client, state: StateManager, dry_run: bool = False) -> int:
    return _run_collection_round(client, state, 19, dry_run=dry_run)


def _run_round20(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """12시 재발굴 — round19 데이터 + 현재 + round18 결과 추적."""
    return _run_rediscovery_round(client, state, 19, 18, 20, dry_run=dry_run, debug=debug)


def _run_round21(client, state: StateManager, dry_run: bool = False) -> int:
    return _run_collection_round(client, state, 21, dry_run=dry_run)


def _run_round22(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """13시 발굴 2차 — round21 데이터 + 현재 데이터 교집합."""
    return _run_discovery_round(client, state, 21, 22, "afternoon_13", dry_run=dry_run, debug=debug)


def _run_round23(client, state: StateManager, dry_run: bool = False) -> int:
    return _run_collection_round(client, state, 23, dry_run=dry_run)


def _run_round24(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """13시 재발굴 — round23 데이터 + 현재 + round22 결과 추적."""
    return _run_rediscovery_round(client, state, 23, 22, 24, dry_run=dry_run, debug=debug)


def _run_round25(client, state: StateManager, dry_run: bool = False) -> int:
    return _run_collection_round(client, state, 25, dry_run=dry_run)


def _run_round26(client, state: StateManager, dry_run: bool = False, debug: bool = False) -> int:
    """15시 발굴 2차 — round25 데이터 + 현재 데이터 교집합."""
    return _run_discovery_round(client, state, 25, 26, "afternoon_15", dry_run=dry_run, debug=debug)


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
    # [v2.7.3 핫픽스] capture-uplmt/FHPST01830000 은 KIS API에 존재하지 않아 항상 404.
    # 향후 [0180] 관심종목등록상위 API (FHPST01800000,
    # /uapi/domestic-stock/v1/ranking/top-interest-stock) 로 마이그레이션 예정.
    # 그 전까지는 온라인관심 가산점을 비활성화 (빈 리스트 반환).
    _ = client  # 인자 보존 (향후 복구 시 사용 예정)
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


_CODE_FIELDS = ("mksc_shrn_iscd", "stck_shrn_iscd")


def _get_code(row: dict[str, Any]) -> str:
    """거래량/체결강도/등락률 API 모두 대응 — 종목코드 필드명이 다름."""
    for field in _CODE_FIELDS:
        val = str(row.get(field, "")).strip()
        if val:
            return val
    return ""


def _extract_codes(rows: list[dict[str, Any]]) -> list[str]:
    codes = []
    for row in rows:
        code = _get_code(row)
        if code:
            codes.append(code)
    return codes


def _extract_metric_map(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    metrics = {}
    for row in rows:
        code = _get_code(row)
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
            code = _get_code(row)
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


def _get_time_thresholds(hour: int) -> tuple[float, float]:
    """
    시간대별 발굴 임계값 (체결강도, 등락률).
    9시/14시 = 모멘텀 강함, 12시 = 점심 자연 거래량 감소.
    """
    if hour in (9, 14):
        return (110.0, 2.0)   # 기존 (모멘텀 강한 시간)
    if hour in (10, 13):
        return (115.0, 2.0)   # 약간 보수
    if hour in (11, 15):
        return (115.0, 2.5)   # 보수
    if hour == 12:
        return (125.0, 3.0)   # 점심 — 가장 보수
    return (110.0, 2.0)       # 안전 fallback


def _score_candidate(
    code: str,
    names: dict[str, str],
    metrics: dict[str, dict[str, float]],
    hts_ranks: dict[str, int],
    hour: int | None = None,
) -> dict[str, Any] | None:
    pow_1 = metrics["pow_1"].get(code)
    pow_2 = metrics["pow_2"].get(code)
    flc_1 = metrics["flc_1"].get(code)
    flc_2 = metrics["flc_2"].get(code)
    vol_1 = metrics["vol_1"].get(code)
    vol_2 = metrics["vol_2"].get(code)

    if None in (pow_1, pow_2, flc_1, flc_2, vol_1, vol_2):
        return None

    # 시간대별 임계값 적용 (hour=None 시 기본값)
    pow_threshold, flc_threshold = _get_time_thresholds(hour if hour is not None else datetime.now().hour)

    # 체결강도 절대값 필터 — 시간대별 차등
    if pow_2 < pow_threshold:
        return None

    # 등락률 최소값 필터 — 시간대별 차등
    if flc_2 < flc_threshold:
        return None

    # 등락률 상한 필터 — 이미 큰 폭 상승한 종목 제외 (발굴 의미 없음)
    if flc_2 >= _MAX_FLC_PCT:
        return None

    score = 0
    reasons = []

    if pow_2 >= 130:
        score += 3
    elif pow_2 >= 120:
        score += 2
    else:  # 110 ~ 119
        score += 1

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


def _build_message(
    time_str: str,
    top_picks: list[dict[str, Any]],
    candidate_count: int,
    all_scored: list[dict[str, Any]] | None = None,
) -> str:
    # 시간대간 분리: 다른 시간대 발굴 종목과 신규 분리 (v2.8.3)
    new_scored, repeat_picks = (
        _split_new_and_repeat(all_scored, time_str) if all_scored else ([], [])
    )
    if all_scored:
        # 메인 표시는 신규만
        top_picks = new_scored[:3]

    lines = [
        f"🔍 {_time_header(time_str, '발굴')}",
        "―――――――――――――――",
        "코스피200 실시간 분석",
        "",
    ]

    if candidate_count == 0:
        lines.append("교집합 종목 없음 — 오늘은 뚜렷한 신호 없음")
        return "\n".join(lines)

    if not top_picks:
        if repeat_picks:
            lines.append("신규 발굴 없음 — 오늘 다른 시간대 발굴 종목만 등장")
        else:
            lines.append("교집합 종목 없음 — 오늘은 뚜렷한 신호 없음")

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

    if lines and lines[-1] == "":
        lines.pop()

    # 추가 관심 후보 (4위 이상인 경우) — 신규 종목만 기준
    extra_pool = new_scored if all_scored else (all_scored or [])
    if extra_pool and len(extra_pool) >= 4:
        extra = extra_pool[3:5]  # 4위, 5위 (최대 2개)
        lines.append("―――――――――――――――")
        lines.append("📋 추가 관심 후보")
        for rank, item in enumerate(extra, start=4):
            lines.append(
                f"  {rank}위 {item['name']} ({item['code']}) "
                f"— 체결강도: {item['pow_2']:.0f} | {item['flc_2']:+.1f}%"
            )

    # 이전 시간대 발굴 재등장 (v2.8.3)
    if repeat_picks:
        lines.append("―――――――――――――――")
        lines.append("🔁 이전 발굴 재등장")
        for item in repeat_picks[:5]:
            prev_t = item.get("prev_disc_time", "")
            prev_label = _korean_hm(prev_t) if prev_t else "이전"
            lines.append(
                f"  {item['name']}({item['code']}) {item['score']}점 "
                f"— {prev_label}에 발굴됨 (현재 {item['flc_2']:+.1f}%)"
            )

    new_count = len(new_scored) if all_scored else len(top_picks)
    summary = f"후보 {candidate_count}종목 → 신규 {new_count} + 재등장 {len(repeat_picks)}"
    lines.extend(["―――――――――――――――", summary])
    return "\n".join(lines)


def _format_delta(delta: float, no_sign_if_zero: bool = False) -> str:
    rounded = round(delta)
    if rounded == 0:
        return "" if no_sign_if_zero else " (0)"
    arrow = "↑" if rounded > 0 else "↓"
    return f" ({rounded:+d}{arrow})"


def _trend_mark(delta: float) -> str:
    if delta > 0:
        return "↑"
    if delta < 0:
        return "↓"
    return ""


def _save_discovery_log(scored: list[dict], volume_rows: list[dict], session: str = "morning") -> None:
    """발굴 결과를 data/discovery_log.json에 기록. 실패해도 예외 없이 경고만 출력."""
    try:
        from datetime import date as _date
        from datetime import timedelta
        import json as _json

        log_file = _ROOT / "data" / "discovery_log.json"

        # 기존 로그 읽기
        if log_file.exists():
            try:
                existing = _json.loads(log_file.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []
        else:
            existing = []

        # disc_price 매핑: volume_rows의 stck_prpr 필드
        price_map = _extract_metric_map(volume_rows, "stck_prpr")

        today = _date.today().isoformat()
        disc_time = datetime.now().strftime("%H:%M")

        # 오늘 날짜 기존 항목 제거 (재실행 시 덮어쓰기)
        existing = [e for e in existing if not (e.get("date") == today and e.get("session", "morning") == session)]

        # 새 항목 추가
        for item in scored:
            existing.append({
                "date": today,
                "session": session,
                "disc_time": disc_time,
                "code": item["code"],
                "name": item["name"],
                "disc_price": int(price_map.get(item["code"], 0)),
                "score": item["score"],
                "pow_2": round(item["pow_2"], 1),
                "flc_2": round(item["flc_2"], 2),
                "close_price": None,
                "return_pct": None,
                "updated_at": None,
            })

        # 30일 이전 항목 삭제
        cutoff = (_date.today() - timedelta(days=30)).isoformat()
        existing = [e for e in existing if e.get("date", "") >= cutoff]

        # 저장
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            _json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"[발굴로그] {len(scored)}개 종목 기록 완료 → {log_file.name}", file=sys.stderr)
    except Exception as e:
        print(f"[발굴로그] 저장 실패 (무시): {e}", file=sys.stderr)


def _fetch_current_price(client, code: str) -> int:
    try:
        info = client.get_price(code)
        return int(_safe_float((info or {}).get("stck_prpr", 0)) or 0)
    except Exception:
        return 0


def _track_recent_picks(client, round_data: dict | None) -> list[dict[str, Any]] | None:
    """이전 발굴 round의 상위 5개 종목 현재가 추적 (신규 시간대 공용)."""
    if not round_data:
        return None
    candidates = round_data.get("candidates", []) if isinstance(round_data, dict) else []
    top5 = sorted(candidates, key=lambda x: -x.get("score", 0))[:5]
    results = []
    for item in top5:
        code = item.get("code")
        if not code:
            continue
        disc_price = item.get("disc_price", 0)
        cur_price = _fetch_current_price(client, code)
        ret_pct = (cur_price - disc_price) / disc_price * 100 if disc_price and cur_price else None
        results.append({
            "code": code,
            "name": item.get("name", code),
            "disc_price": disc_price,
            "cur_price": cur_price,
            "ret_pct": round(ret_pct, 2) if ret_pct is not None else None,
            "disc_time": round_data.get("time", ""),
        })
    return results


def _fetch_morning_tracking(client, state: StateManager) -> list[dict[str, Any]]:
    """오전 round2 발굴 종목 상위 5개 현재가 추적."""
    round2 = state.get("intraday_discovery.round2") or {}
    if not isinstance(round2, dict) or not round2:
        print("[경고] round2 데이터 없음 — 오전 발굴 추적 생략", file=sys.stderr)
        return []
    candidates = round2.get("candidates", []) if isinstance(round2, dict) else []
    top5 = sorted(candidates, key=lambda x: -x.get("score", 0))[:5]
    results = []
    for item in top5:
        code = item.get("code")
        if not code:
            continue
        disc_price = item.get("disc_price", 0)
        cur_price = _fetch_current_price(client, code)
        ret_pct = (cur_price - disc_price) / disc_price * 100 if disc_price and cur_price else None
        results.append({
            "code": code,
            "name": item.get("name", code),
            "disc_price": disc_price,
            "cur_price": cur_price,
            "ret_pct": round(ret_pct, 2) if ret_pct is not None else None,
            "disc_time": round2.get("time", ""),
        })
    return results


def _fetch_afternoon_tracking(client, state: StateManager) -> list[dict[str, Any]]:
    """오후 round6 발굴 종목 상위 5개 현재가 추적."""
    round6 = state.get("intraday_discovery.round6") or {}
    if not isinstance(round6, dict) or not round6:
        print("[경고] round6 데이터 없음 — 오후 발굴 추적 생략", file=sys.stderr)
        return []
    candidates = round6.get("candidates", []) if isinstance(round6, dict) else []
    top5 = sorted(candidates, key=lambda x: -x.get("score", 0))[:5]
    results = []
    for item in top5:
        code = item.get("code")
        if not code:
            continue
        disc_price = item.get("disc_price", 0)
        cur_price = _fetch_current_price(client, code)
        ret_pct = (cur_price - disc_price) / disc_price * 100 if disc_price and cur_price else None
        results.append({
            "code": code,
            "name": item.get("name", code),
            "disc_price": disc_price,
            "cur_price": cur_price,
            "ret_pct": round(ret_pct, 2) if ret_pct is not None else None,
            "disc_time": round6.get("time", ""),
        })
    return results


def _build_message_round4(
    time_str: str,
    top_picks: list[dict[str, Any]],
    candidate_count: int,
    tracking: list[dict[str, Any]] | None = None,
    all_scored: list[dict[str, Any]] | None = None,
) -> str:
    # 시간대간 분리 (v2.8.3) — ⭐재확인은 같은 시간대(9:05↔9:33)이므로 자동으로 new_scored 에 포함
    new_scored, repeat_picks = (
        _split_new_and_repeat(all_scored, time_str) if all_scored else ([], [])
    )
    if all_scored:
        top_picks = new_scored[:3]

    lines = [
        f"🔍 {_time_header(time_str, '재발굴')}",
        "―――――――――――――――",
        "코스피200 실시간 분석",
        "",
    ]

    if candidate_count == 0:
        lines.append("교집합 종목 없음 — 오늘은 뚜렷한 신호 없음")
    elif not top_picks:
        lines.append("신규 발굴 없음 — 오늘 다른 시간대 발굴 종목만 등장")
    else:
        for idx, item in enumerate(top_picks):
            medal = _MEDALS[idx] if idx < len(_MEDALS) else f"{idx + 1}."
            reconfirmed = "  ⭐재확인" if item.get("is_reconfirmed") else ""
            lines.append(f"{medal} {item['name']} ({item['code']})  {item['score']}점{reconfirmed}")
            lines.append(
                "   "
                f"체결강도: {item['pow_2']:.0f}{_format_delta(item['pow_delta'], no_sign_if_zero=True)} "
                f"| 등락률: {item['flc_2']:+.1f}%{_trend_mark(item['flc_delta'])} "
                f"| {'거래량↑' if item['vol_delta'] > 0 else '거래량→'}"
            )
            lines.append("")

        if lines and lines[-1] == "":
            lines.pop()

        extra_pool = new_scored if all_scored else (all_scored or [])
        if extra_pool and len(extra_pool) >= 4:
            extra = extra_pool[3:5]
            lines.append("―――――――――――――――")
            lines.append("📋 추가 관심 후보")
            for rank, item in enumerate(extra, start=4):
                reconfirmed = "  ⭐재확인" if item.get("is_reconfirmed") else ""
                lines.append(
                    f"  {rank}위 {item['name']} ({item['code']}) "
                    f"— 체결강도: {item['pow_2']:.0f} | {item['flc_2']:+.1f}%{reconfirmed}"
                )

    # 이전 시간대 발굴 재등장 (v2.8.3)
    if repeat_picks:
        lines.append("―――――――――――――――")
        lines.append("🔁 이전 발굴 재등장")
        for item in repeat_picks[:5]:
            prev_t = item.get("prev_disc_time", "")
            prev_label = _korean_hm(prev_t) if prev_t else "이전"
            lines.append(
                f"  {item['name']}({item['code']}) {item['score']}점 "
                f"— {prev_label}에 발굴됨 (현재 {item['flc_2']:+.1f}%)"
            )

    if tracking:
        disc_time = tracking[0].get("disc_time", "")
        label_time = _korean_hm(disc_time) if disc_time else ""
        label = f"📊 {label_time} 발굴 종목 추적" if label_time else "📊 발굴 종목 추적"
        lines.append("―――――――――――――――")
        lines.append(label)
        for idx, item in enumerate(tracking, start=1):
            ret_text = f"({item['ret_pct']:+.1f}%)" if item.get("ret_pct") is not None else "(N/A)"
            cur_text = f"{item['cur_price']:,}" if item.get("cur_price") else "N/A"
            disc_text = f"{int(item['disc_price']):,}" if item.get("disc_price") else "N/A"
            lines.append(
                f"  {idx} {item['name']}  발굴가 {disc_text} → 현재 {cur_text}  {ret_text}"
            )

    new_count = len(new_scored) if all_scored else len(top_picks)
    summary = f"후보 {candidate_count}종목 → 신규 {new_count} + 재등장 {len(repeat_picks)}"
    lines.extend(["―――――――――――――――", summary])
    return "\n".join(lines)


def _build_message_afternoon(
    time_str: str,
    top_picks: list[dict[str, Any]],
    candidate_count: int,
    all_scored: list[dict[str, Any]] | None = None,
) -> str:
    new_scored, repeat_picks = (
        _split_new_and_repeat(all_scored, time_str) if all_scored else ([], [])
    )
    if all_scored:
        top_picks = new_scored[:3]

    lines = [
        f"🔍 {_time_header(time_str, '발굴')}",
        "―――――――――――――――",
        "코스피200 실시간 분석",
        "",
    ]

    if candidate_count == 0:
        lines.append("교집합 종목 없음 — 오늘은 뚜렷한 신호 없음")
        return "\n".join(lines)

    if not top_picks:
        if repeat_picks:
            lines.append("신규 발굴 없음 — 오늘 다른 시간대 발굴 종목만 등장")
        else:
            lines.append("교집합 종목 없음 — 오늘은 뚜렷한 신호 없음")

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

    if lines and lines[-1] == "":
        lines.pop()

    extra_pool = new_scored if all_scored else (all_scored or [])
    if extra_pool and len(extra_pool) >= 4:
        extra = extra_pool[3:5]
        lines.append("―――――――――――――――")
        lines.append("📋 추가 관심 후보")
        for rank, item in enumerate(extra, start=4):
            lines.append(
                f"  {rank}위 {item['name']} ({item['code']}) "
                f"— 체결강도: {item['pow_2']:.0f} | {item['flc_2']:+.1f}%"
            )

    if repeat_picks:
        lines.append("―――――――――――――――")
        lines.append("🔁 이전 발굴 재등장")
        for item in repeat_picks[:5]:
            prev_t = item.get("prev_disc_time", "")
            prev_label = _korean_hm(prev_t) if prev_t else "이전"
            lines.append(
                f"  {item['name']}({item['code']}) {item['score']}점 "
                f"— {prev_label}에 발굴됨 (현재 {item['flc_2']:+.1f}%)"
            )

    new_count = len(new_scored) if all_scored else len(top_picks)
    summary = f"후보 {candidate_count}종목 → 신규 {new_count} + 재등장 {len(repeat_picks)}"
    lines.extend(["―――――――――――――――", summary])
    return "\n".join(lines)


def _build_message_round8(
    time_str: str,
    top_picks: list[dict[str, Any]],
    candidate_count: int,
    tracking: list[dict[str, Any]] | None = None,
    all_scored: list[dict[str, Any]] | None = None,
) -> str:
    new_scored, repeat_picks = (
        _split_new_and_repeat(all_scored, time_str) if all_scored else ([], [])
    )
    if all_scored:
        top_picks = new_scored[:3]

    lines = [
        f"🔍 {_time_header(time_str, '재발굴')}",
        "―――――――――――――――",
        "코스피200 실시간 분석",
        "",
    ]

    if candidate_count == 0:
        lines.append("교집합 종목 없음 — 오늘은 뚜렷한 신호 없음")
    elif not top_picks:
        lines.append("신규 발굴 없음 — 오늘 다른 시간대 발굴 종목만 등장")
    else:
        for idx, item in enumerate(top_picks):
            medal = _MEDALS[idx] if idx < len(_MEDALS) else f"{idx + 1}."
            reconfirmed = "  ⭐재확인" if item.get("is_reconfirmed") else ""
            lines.append(f"{medal} {item['name']} ({item['code']})  {item['score']}점{reconfirmed}")
            lines.append(
                "   "
                f"체결강도: {item['pow_2']:.0f}{_format_delta(item['pow_delta'], no_sign_if_zero=True)} "
                f"| 등락률: {item['flc_2']:+.1f}%{_trend_mark(item['flc_delta'])} "
                f"| {'거래량↑' if item['vol_delta'] > 0 else '거래량→'}"
            )
            lines.append("")

        if lines and lines[-1] == "":
            lines.pop()

        extra_pool = new_scored if all_scored else (all_scored or [])
        if extra_pool and len(extra_pool) >= 4:
            extra = extra_pool[3:5]
            lines.append("―――――――――――――――")
            lines.append("📋 추가 관심 후보")
            for rank, item in enumerate(extra, start=4):
                reconfirmed = "  ⭐재확인" if item.get("is_reconfirmed") else ""
                lines.append(
                    f"  {rank}위 {item['name']} ({item['code']}) "
                    f"— 체결강도: {item['pow_2']:.0f} | {item['flc_2']:+.1f}%{reconfirmed}"
                )

    if repeat_picks:
        lines.append("―――――――――――――――")
        lines.append("🔁 이전 발굴 재등장")
        for item in repeat_picks[:5]:
            prev_t = item.get("prev_disc_time", "")
            prev_label = _korean_hm(prev_t) if prev_t else "이전"
            lines.append(
                f"  {item['name']}({item['code']}) {item['score']}점 "
                f"— {prev_label}에 발굴됨 (현재 {item['flc_2']:+.1f}%)"
            )

    if tracking:
        disc_time = tracking[0].get("disc_time", "")
        label_time = _korean_hm(disc_time) if disc_time else ""
        label = f"📊 {label_time} 발굴 종목 추적" if label_time else "📊 발굴 종목 추적"
        lines.append("―――――――――――――――")
        lines.append(label)
        for idx, item in enumerate(tracking, start=1):
            ret_text = f"({item['ret_pct']:+.1f}%)" if item.get("ret_pct") is not None else "(N/A)"
            cur_text = f"{item['cur_price']:,}" if item.get("cur_price") else "N/A"
            disc_text = f"{int(item['disc_price']):,}" if item.get("disc_price") else "N/A"
            lines.append(
                f"  {idx} {item['name']}  발굴가 {disc_text} → 현재 {cur_text}  {ret_text}"
            )

    new_count = len(new_scored) if all_scored else len(top_picks)
    summary = f"후보 {candidate_count}종목 → 신규 {new_count} + 재등장 {len(repeat_picks)}"
    lines.extend(["―――――――――――――――", summary])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="장초기 실시간 종목 발굴")
    parser.add_argument("--round", dest="round_no", type=int, choices=list(range(1, 27)), required=True)
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 출력만 수행")
    parser.add_argument("--debug", action="store_true", help="단계별 필터 진단 출력 (짝수 발굴/재발굴 round 전용)")
    args = parser.parse_args()
    return run(round_no=args.round_no, dry_run=args.dry_run, debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())
