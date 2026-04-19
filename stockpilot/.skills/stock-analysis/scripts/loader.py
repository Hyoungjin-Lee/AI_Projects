"""
loader.py — data/raw/ 폴더의 JSON 캐시를 pandas DataFrame으로 읽어주는 헬퍼

주요 함수:
  load_latest(code, kind) — 가장 최근 캐시 파일을 자동으로 찾아 DataFrame 반환
  load_file(path)         — 특정 파일 경로를 직접 읽어 DataFrame 반환
"""

import json
import glob
import os
from datetime import datetime, date

import pandas as pd

# 프로젝트 루트: 이 파일 기준으로 3단계 위
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
_RAW_DIR = os.path.join(_PROJECT_ROOT, "data", "raw")

# kind → 파일명에 포함된 접미사 매핑
_KIND_MAP = {
    "daily":     "daily",
    "minute":    "minute",
    "quote":     "quote",
    "orderbook": "orderbook",
    "balance":   "balance",
}


def load_latest(code: str, kind: str) -> pd.DataFrame:
    """
    data/raw/ 에서 code·kind에 해당하는 가장 최근 JSON 파일을 찾아 DataFrame으로 반환.

    Parameters
    ----------
    code : str  종목코드 (예: "005930"). balance는 코드 무관 → "all" 전달
    kind : str  "daily" | "minute" | "quote" | "orderbook" | "balance"

    Returns
    -------
    pd.DataFrame

    Raises
    ------
    FileNotFoundError : 해당 캐시 파일이 없을 때
    ValueError        : kind 값이 올바르지 않을 때
    """
    if kind not in _KIND_MAP:
        raise ValueError(f"kind='{kind}' 은 지원하지 않습니다. 사용 가능: {list(_KIND_MAP)}")

    suffix = _KIND_MAP[kind]
    if kind == "balance":
        pattern = os.path.join(_RAW_DIR, f"*_{suffix}_*.json")
    else:
        pattern = os.path.join(_RAW_DIR, f"{code}_{suffix}_*.json")

    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"캐시 파일을 찾을 수 없습니다: {pattern}\n"
            f"먼저 kis-api 스킬의 get_{suffix}.py 스크립트로 데이터를 받아오세요."
        )

    latest = files[-1]  # 파일명이 날짜시각 포함이므로 lexicographic 정렬 = 시간 정렬
    return load_file(latest)


def load_file(path: str) -> pd.DataFrame:
    """
    JSON 파일을 열어 DataFrame으로 변환.

    KIS API가 돌려주는 JSON 구조를 자동 감지:
      - output / output1 / output2 키 내부의 list 자동 탐지
      - 최상위가 list인 경우도 처리
    날짜/시각 컬럼은 자동으로 파싱한다.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    records = _extract_records(raw)
    df = pd.DataFrame(records)
    df = _parse_columns(df)
    return df


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _extract_records(raw) -> list:
    """JSON에서 레코드 리스트 추출 (KIS 응답 구조 자동 감지)."""
    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):
        # KIS는 output, output1, output2 를 씀
        for key in ("output", "output1", "output2", "data"):
            val = raw.get(key)
            if isinstance(val, list) and val:
                return val
            if isinstance(val, dict):
                return [val]

        # output 키가 없으면 최상위 dict 자체를 단일 레코드로
        return [raw]

    return []


def _parse_columns(df: pd.DataFrame) -> pd.DataFrame:
    """숫자/날짜 컬럼 자동 캐스팅."""
    # 날짜 컬럼
    date_cols = [c for c in df.columns if c in ("stck_bsop_date", "date", "bass_dt")]
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce")

    # 시각 컬럼
    time_cols = [c for c in df.columns if c in ("stck_cntg_hour", "time", "hour")]
    for col in time_cols:
        df[col] = pd.to_datetime(df[col], format="%H%M%S", errors="coerce").dt.time

    # 숫자형 컬럼 (KIS는 숫자를 문자열로 내려줌)
    num_candidates = [
        "stck_oprc", "stck_hgpr", "stck_lwpr", "stck_clpr", "stck_prpr",
        "acml_vol", "acml_tr_pbmn",
        "open", "high", "low", "close", "volume",
        "askp1", "askp2", "askp3", "askp4", "askp5",
        "bidp1", "bidp2", "bidp3", "bidp4", "bidp5",
        "askp_rsqn1", "askp_rsqn2", "askp_rsqn3", "askp_rsqn4", "askp_rsqn5",
        "bidp_rsqn1", "bidp_rsqn2", "bidp_rsqn3", "bidp_rsqn4", "bidp_rsqn5",
        "prdy_ctrt", "prdy_vrss",
    ]
    for col in num_candidates:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 표준 컬럼명 alias (분석 스크립트가 open/high/low/close/volume 로 접근)
    alias = {
        "stck_oprc": "open",
        "stck_hgpr": "high",
        "stck_lwpr": "low",
        "stck_clpr": "close",
        "acml_vol":  "volume",
        "stck_bsop_date": "date",
        "stck_prpr": "current_price",
    }
    for src, dst in alias.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = df[src]

    return df


# ── CLI 테스트 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("사용법: python loader.py <종목코드> <kind>")
        print("  kind: daily | minute | quote | orderbook | balance")
        sys.exit(1)

    code_arg = sys.argv[1]
    kind_arg = sys.argv[2]

    df = load_latest(code_arg, kind_arg)
    print(f"✅ 로드 완료: {len(df)}행 × {len(df.columns)}열")
    print(df.head())
