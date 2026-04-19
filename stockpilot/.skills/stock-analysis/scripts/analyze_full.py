"""
analyze_full.py — 단타·스윙·정량 세 관점 종합 분석

사용법:
  python analyze_full.py <종목코드>

내부적으로 analyze_swing / analyze_intraday / analyze_quant 를 순차 실행.
세 verdict가 다를 때는 confidence 가중평균으로 최종 verdict를 결정.
결과는 stdout에 종합 JSON + 각 관점 상세 dict 포함.
"""

import argparse
import json
import sys
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

import analyze_swing    as _swing
import analyze_intraday as _intraday
import analyze_quant    as _quant


# verdict → 숫자 점수 매핑 (가중평균용)
_SCORE = {"BUY": 1.0, "HOLD": 0.3, "WATCH": 0.0, "SELL": -1.0}
_SCORE_REV = {1.0: "BUY", 0.3: "HOLD", 0.0: "WATCH", -1.0: "SELL"}


def analyze(code: str) -> dict:
    """세 관점 분석을 합산해 최종 판정을 반환."""

    print(f"[1/3] 스윙 분석 중...", file=sys.stderr)
    swing_r    = _swing.analyze(code, days=120)

    print(f"[2/3] 단타 분석 중...", file=sys.stderr)
    intraday_r = _intraday.analyze(code)

    print(f"[3/3] 정량 분석 중...", file=sys.stderr)
    quant_r    = _quant.analyze(code, days=200)

    # ── 종합 판정 ─────────────────────────────────────────────────────────────
    # 가중치: 스윙 0.4, 정량 0.4, 단타 0.2
    weights = {"swing": 0.4, "quant": 0.4, "intraday": 0.2}
    results = {
        "swing":    swing_r,
        "quant":    quant_r,
        "intraday": intraday_r,
    }

    # confidence 가중 평균 점수
    weighted_score = 0.0
    total_w = 0.0
    for key, res in results.items():
        v = res.get("verdict", "WATCH")
        c = res.get("confidence", 0.0)
        score = _SCORE.get(v, 0.0) * c
        w = weights[key]
        weighted_score += score * w
        total_w += w

    final_score = weighted_score / total_w if total_w else 0.0

    # 점수 → 최종 verdict
    if final_score >= 0.5:
        final_verdict = "BUY"
    elif final_score >= 0.15:
        final_verdict = "HOLD"
    elif final_score <= -0.5:
        final_verdict = "SELL"
    elif final_score <= -0.15:
        final_verdict = "SELL"
    else:
        final_verdict = "WATCH"

    # 평균 confidence
    avg_conf = round(
        sum(results[k]["confidence"] * weights[k] for k in weights) / sum(weights.values()),
        2,
    )

    # 종합 시그널 (세 관점에서 핵심 시그널 2개씩 모아 요약)
    top_signals = []
    for key in ("swing", "quant", "intraday"):
        sigs = results[key].get("key_signals", [])[:2]
        for s in sigs:
            top_signals.append({**s, "perspective": key})

    # 리스크 합산
    all_risks = []
    for key in ("swing", "quant", "intraday"):
        all_risks.extend(results[key].get("risks", []))

    # 충돌 감지
    verdicts_set = {results[k]["verdict"] for k in weights}
    if len(verdicts_set) > 2:
        all_risks.append(
            f"세 관점 판정 충돌 (스윙:{swing_r['verdict']}, 정량:{quant_r['verdict']}, "
            f"단타:{intraday_r['verdict']}) — 신중히 판단하세요"
        )

    # 지지/저항은 스윙 기준
    support    = swing_r.get("support_levels", [])
    resistance = swing_r.get("resistance_levels", [])

    narrative = (
        f"{code} 종합 판정: {final_verdict} (종합 확신도 {avg_conf:.2f}). "
        f"스윙={swing_r['verdict']}({swing_r['confidence']:.2f}), "
        f"정량={quant_r['verdict']}({quant_r['confidence']:.2f}), "
        f"단타={intraday_r['verdict']}({intraday_r['confidence']:.2f}). "
        + (f"손절: {swing_r['stop_loss']:,.0f}원 / 목표: {swing_r['target_price']:,.0f}원."
           if swing_r.get("stop_loss") else "")
    )

    return {
        "code": code,
        "perspective": "full",
        "verdict": final_verdict,
        "confidence": avg_conf,
        "key_signals": top_signals,
        "support_levels": support,
        "resistance_levels": resistance,
        "stop_loss": swing_r.get("stop_loss"),
        "target_price": swing_r.get("target_price"),
        "narrative": narrative,
        "risks": list(dict.fromkeys(all_risks)),   # 중복 제거
        "details": {
            "swing":    swing_r,
            "quant":    quant_r,
            "intraday": intraday_r,
        },
        "data_window": swing_r.get("data_window", {}),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="종합(풀) 분석 — 단타·스윙·정량 통합")
    parser.add_argument("code", help="종목코드 (예: 005930)")
    args = parser.parse_args()

    result = analyze(args.code)
    print(json.dumps(result, ensure_ascii=False, indent=2))
