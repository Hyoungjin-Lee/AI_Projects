## Stage 8: 구현 (Implementation)

**현재 단계**: Stage 8 - implementation
**담당**: Codex
**모델**: Codex (전문화된 코딩 환경)
**노력**: High (1-8시간, 프로젝트 복잡도에 따라)
**입력**: Stage 5 기술 설계 + Stage 7 UI 플로우 (있을 경우)
**산출물**: 코드 + 테스트 + PR/커밋

---

### 목표

기술 설계를 바탕으로 구현 가능한 코드를 작성합니다. Unit 테스트를 포함하고, Stage 9 코드 리뷰 준비를 완료합니다.

---

### 구현 원칙

1. **MVP 우선**:
   - Phase 1 기능에만 집중
   - 완전하기보다 동작하는 코드
   - 향후 리팩토링 여지

2. **과한 추상화 금지**:
   - 실제 동작하는 코드
   - Design pattern은 필요한 경우만
   - 복잡도와 이득 비교

3. **실행 가능한 코드 중심**:
   - 의존성 명시
   - 설치 지침 포함
   - 테스트 실행 가능

4. **파일 단위 책임 분리**:
   - 각 파일은 하나의 책임 (SRP)
   - 모듈 간 느슨한 결합

5. **에러 처리 포함**:
   - 예외 처리 (try-except)
   - 로그 기록
   - Graceful degradation

---

### 작업 지침

1. **구현 대상 요약**:
   - 무엇을 구현하는가?
   - 범위는 무엇인가?

2. **권장 파일 구조**:
   - 각 모듈 파일명
   - 패키지 구성
   - 테스트 파일 위치

3. **구현 우선순위**:
   - 어떤 모듈부터 구현할 것인가?
   - 의존성 순서

4. **코드 작성**:
   - 주요 함수/클래스 작성
   - Unit 테스트 작성
   - 주석 포함

5. **확인할 TODO**:
   - 구현 후 확인 항목
   - 테스트 실행 방법
   - 수동 검증 항목

---

### 출력 형식 및 예시

```
# Stage 8: 구현

## 구현 대상
stockpilot의 새로운 기술적 분석 지표 추가 기능

## 권장 파일 구조
```
morning_report/
├─ analyzer/
│  ├─ __init__.py
│  ├─ technical_analyzer.py  ← 기술적 분석 로직
│  ├─ signals.py              ← 시그널 검출
│  └─ test_analyzer.py        ← 단위 테스트
├─ config/
│  └─ indicators.json         ← 지표 설정
└─ logs/
   └─ analyzer.log            ← 로그
```

## 구현 우선순위

1. `signals.py` (의존성 없음)
2. `technical_analyzer.py` (signals.py 필요)
3. `test_analyzer.py`
4. `morning_report.py` 수정 (analyzer 통합)

## 코드 작성

### 1. signals.py
```python
from enum import Enum
from dataclasses import dataclass

class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

@dataclass
class AnalysisSignal:
    signal: Signal
    confidence: float  # 0.0 ~ 1.0
    reason: str

def detect_moving_average_signal(prices: list) -> AnalysisSignal:
    \"\"\"
    이동평균선 교차 신호 검출
    Args: 가격 리스트 (최근순)
    Returns: AnalysisSignal
    Raises: ValueError (데이터 부족시)
    \"\"\"
    if len(prices) < 20:
        raise ValueError("20일 이상의 데이터 필요")

    ma20 = sum(prices[:20]) / 20
    ma50 = sum(prices[:50]) / 50 if len(prices) >= 50 else ma20

    current = prices[0]
    if current > ma20 > ma50:
        return AnalysisSignal(Signal.BUY, 0.8, "상승 교차 신호")
    elif current < ma20 < ma50:
        return AnalysisSignal(Signal.SELL, 0.8, "하락 교차 신호")
    else:
        return AnalysisSignal(Signal.HOLD, 0.5, "추세 불명확")
```

### 2. test_analyzer.py
```python
import unittest
from analyzer.signals import detect_moving_average_signal, Signal

class TestSignals(unittest.TestCase):
    def test_buy_signal(self):
        # 상승 추세 데이터
        prices = [105, 104, 103, 102, 101] + [100] * 15  # MA20=100
        signal = detect_moving_average_signal(prices)
        self.assertEqual(signal.signal, Signal.BUY)

    def test_insufficient_data(self):
        prices = [100, 99, 98]
        with self.assertRaises(ValueError):
            detect_moving_average_signal(prices)

if __name__ == '__main__':
    unittest.main()
```

## 확인할 TODO

- [ ] `python3 -m pytest analyzer/test_analyzer.py -v` 모두 통과
- [ ] `python3 -m py_compile analyzer/technical_analyzer.py` 문법 확인
- [ ] 보안: API 키/비밀번호 노출 여부 확인 (✗ 없음)
- [ ] stockpilot 기존 코드와 통합 테스트
  - [ ] `morning_report.py` import 테스트
  - [ ] Keychain 통합 테스트
- [ ] 로그 출력 테스트 (`logs/analyzer.log` 생성 확인)
- [ ] 예외 처리 테스트 (잘못된 데이터 입력)

## 다음 단계

**→ Stage 9: 코드 리뷰** (aireview - Claude)
프롬프트: `prompts/claude/code_review.txt`
```

---

### 주의사항

- ✅ stockpilot 기존 패턴 준수 (Keychain, 로깅, 보안)
- ✅ Python 3.14 기준 (타입 힌트 권장)
- ✅ Unit 테스트 포함 (최소 정상 + 예외 케이스)
- ❌ 외부 의존성 무분별 추가 금지 (기존 라이브러리 활용)
- ✅ API 키, 계좌번호 등 민감정보는 Keychain에서 로드
- ✅ 에러 처리 및 로그 기록 필수

---

### 다음 단계

**→ Stage 9: 코드 리뷰** (aireview)
프롬프트: `prompts/claude/code_review.txt`
산출물: 리뷰 피드백

(문제 있으면)
**→ Stage 10: 수정** (airevise)
프롬프트: `prompts/codex/revise.txt`

(문제 없으면)
**→ Stage 11: 최종 검증** (aifinal)
프롬프트: `prompts/claude/final_review.txt`
