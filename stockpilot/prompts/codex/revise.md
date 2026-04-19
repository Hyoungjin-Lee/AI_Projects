## Stage 10: 수정 (Revise)

**현재 단계**: Stage 10 - revise
**담당**: Codex
**모델**: Codex (수정 및 개선)
**노력**: Medium (30분-2시간)
**입력**: Stage 9 코드 리뷰 피드백
**산출물**: 수정된 코드 + 테스트

---

### 목표

Stage 9 코드 리뷰의 피드백을 반영하여 코드를 수정합니다. 기존 구조를 무지막지하게 흔들지 않으면서 필요한 부분만 수정합니다.

---

### 수정 원칙

1. **요구된 부분만 수정**:
   - 리뷰에서 지적한 항목에만 집중
   - Scope creep 방지

2. **기존 구조 유지**:
   - 불필요한 리팩토링 금지
   - 기존 API 호환성 유지

3. **새로운 버그 최소화**:
   - 수정 부분의 테스트 재확인
   - 의존하는 다른 코드 영향 확인

4. **변경 이유 명확화**:
   - 커밋 메시지에 명시
   - 코드 주석으로 설명

---

### 작업 지침

1. **변경 파일 목록**:
   - 어떤 파일을 수정했는가?

2. **변경 내용 요약**:
   - 각 파일별 주요 변경
   - 우선순위 (Critical → Medium)

3. **수정된 코드**:
   - 변경 전/후 코드 비교
   - 관련 함수만 포함

4. **추가 확인 포인트**:
   - 수정 후 어디를 테스트할 것인가?
   - 의존 코드에 영향은?

---

### 출력 형식

```
# Stage 10: 수정

## 변경 파일 목록
1. `analyzer/signals.py` - Critical 1개 + Medium 2개
2. `analyzer/test_analyzer.py` - 테스트 추가
3. `morning_report/morning_report.py` - 통합 수정

## 변경 내용 요약

### Priority 1: Critical (예외 처리)

#### 파일: analyzer/signals.py
**문제**: ZeroDivisionError 가능 (빈 리스트)

**변경 전**:
\`\`\`python
def detect_moving_average_signal(prices):
    ma20 = sum(prices[:20]) / 20  # 리스트가 비어있으면 crash
\`\`\`

**변경 후**:
\`\`\`python
def detect_moving_average_signal(prices):
    if not prices or len(prices) < 20:
        raise ValueError("최소 20개의 가격 데이터 필요")

    ma20 = sum(prices[:20]) / 20
\`\`\`

**이유**: 리뷰에서 "불완전한 예외 처리" 지적

---

### Priority 2: Medium (로그 추가)

#### 파일: analyzer/signals.py
**문제**: 신호 생성 시 로그 없음

**변경 후**:
\`\`\`python
import logging

logger = logging.getLogger(__name__)

def detect_moving_average_signal(prices):
    logger.debug(f"신호 검출 시작: {len(prices)}개 데이터")
    # ... 로직 ...
    logger.info(f"신호: {signal.signal}, 신뢰도: {signal.confidence:.2%}")
\`\`\`

---

## 추가 확인 포인트

### 테스트
- [ ] `pytest analyzer/test_analyzer.py -v` 모두 통과
- [ ] 새로운 테스트 케이스 추가 (ZeroDivisionError 방지)
  \`\`\`python
  def test_empty_list(self):
      with self.assertRaises(ValueError):
          detect_moving_average_signal([])
  \`\`\`
- [ ] 로그 출력 확인
  \`\`\`bash
  grep -i "신호" logs/analyzer.log
  \`\`\`

### 의존 코드 영향
- [ ] `morning_report.py`의 `analyzer.detect_moving_average_signal()` 호출부
  - 예외 처리 추가됨 (기존 코드 호환성 유지)
  - 새로운 ValueError 처리 필요? (이미 처리됨)

### 성능 영향
- [ ] 로그 추가로 인한 성능 저하: 무시할 수준 (logging은 lazy evaluation)

## 다음 단계

**→ Stage 11: 최종 검증** (aifinal - Claude)
프롬프트: `prompts/claude/final_review.txt`

(문제 있으면)
**→ 다시 Stage 9: 코드 리뷰** (aireview)
```

---

### 주의사항

- ✅ 리뷰 피드백만 반영 (별도의 개선 금지)
- ✅ 수정 이유를 명확하게 커밋 메시지에 기록
- ❌ 기존 API 변경 금지 (호환성 유지)
- ✅ 모든 변경 후 테스트 재실행
- ✅ 새로운 버그 도입 여부 확인

---

### 다음 단계

**→ Stage 11: 최종 검증** (aifinal)
프롬프트: `prompts/claude/final_review.txt`
산출물: `docs/notes/final_validation.md`

(추가 문제 발견시)
**→ 다시 Stage 9: 코드 리뷰** (aireview)

(문제 없시)
**→ Stage 12: QA & 릴리스** (aiqa)
프롬프트: `prompts/claude/qa.txt`
