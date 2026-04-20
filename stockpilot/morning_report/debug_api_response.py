"""
debug_api_response.py — 체결강도/등락률 API 응답 구조 진단

실행:
  venv/bin/python3 morning_report/debug_api_response.py
"""
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / ".skills" / "kis-api" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(_ROOT / ".env")

from keychain_manager import inject_to_env
inject_to_env()

from kis_client import KISClient
client = KISClient()


def dump(label: str, response: dict):
    print(f"\n{'='*55}")
    print(f"📡 {label}")
    print(f"{'='*55}")
    # rt_cd, msg 확인
    print(f"  rt_cd : {response.get('rt_cd')}")
    print(f"  msg1  : {response.get('msg1')}")
    output = response.get("output", response.get("output1", response.get("output2", "없음")))
    if isinstance(output, list):
        print(f"  output 행 수: {len(output)}")
        if output:
            print(f"  첫 번째 행 키: {list(output[0].keys())}")
            print(f"  첫 번째 행 데이터:")
            for k, v in output[0].items():
                print(f"    {k}: {v}")
    elif isinstance(output, dict):
        print(f"  output(dict) 키: {list(output.keys())}")
    else:
        print(f"  output 없음 — 전체 키: {list(response.keys())}")
        # output 관련 키 찾기
        for k in response:
            if "output" in k.lower():
                print(f"  후보 키 [{k}]: {str(response[k])[:200]}")


# ── 1. 체결강도 (volume-power) ──────────────────────────
print("\n\n[1] 체결강도 랭킹 API 테스트")
try:
    resp = client._get(
        "/uapi/domestic-stock/v1/ranking/volume-power",
        "FHPST01680000",
        {
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
    dump("체결강도 랭킹 (FHPST01680000, iscd=0000)", resp)
except Exception as e:
    print(f"  ❌ 오류: {e}")


# ── 2. 등락률 랭킹 (fluctuation) ────────────────────────
print("\n\n[2] 등락률 랭킹 API 테스트")
try:
    resp = client._get(
        "/uapi/domestic-stock/v1/ranking/fluctuation",
        "FHPST01700000",
        {
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
    dump("등락률 랭킹 (FHPST01700000, iscd=0000)", resp)
except Exception as e:
    print(f"  ❌ 오류: {e}")


# ── 3. 거래량 랭킹 (참고용 — 이건 되는 것) ─────────────
print("\n\n[3] 거래량 랭킹 API 테스트 (정상 작동 확인용)")
try:
    resp = client._get(
        "/uapi/domestic-stock/v1/quotations/volume-rank",
        "FHPST01710000",
        {
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
    dump("거래량 랭킹 (FHPST01710000, iscd=0000)", resp)
except Exception as e:
    print(f"  ❌ 오류: {e}")
