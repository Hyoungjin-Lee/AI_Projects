## Stage 5: 기술 설계 (Technical Design)

**현재 단계**: Stage 5 - technical_design
**담당**: Claude
**모델**: Opus (깊은 아키텍처 설계)
**노력**: High (30-60분, 30-60K 토큰)
**입력**: Stage 4 최종 계획
**산출물**: `docs/03_design/technical_design.md`

---

### 목표

확정된 기획을 바탕으로 구현 가능한 기술 설계를 작성합니다. Codex가 이 문서를 읽고 구현을 시작할 수 있어야 합니다.

---

### 작업 원칙

- **MVP 우선**: 핵심 기능에만 집중 (Phase 1 기능)
- **과한 추상화 금지**: 실제로 코드로 작성할 수 있는 수준
- **유지보수 가능한 구조**: stockpilot 기존 패턴 준수
- **실제 구현 가능**: 팀 능력 범위 내

---

### 반드시 포함할 항목

1. **전체 아키텍처**:
   - 시스템 다이어그램 (텍스트 형식, ASCII art 가능)
   - 주요 컴포넌트 간 관계
   - 데이터 흐름

2. **주요 모듈 역할**:
   - 각 모듈의 책임 (Separation of Concerns)
   - 인터페이스 정의
   - 모듈 간 호출 관계

3. **데이터 흐름**:
   - Input → Processing → Output
   - 캐싱 전략
   - 상태 관리

4. **상태 관리 방식**:
   - 변수/설정 저장소
   - stockpilot의 Keychain 활용
   - 상태 전환 방식

5. **API 또는 내부 인터페이스 초안**:
   - 함수/클래스 시그니처 (의사 코드)
   - 입력/출력 형식
   - 오류 처리

6. **예외 처리 포인트**:
   - 어디서 예외가 발생할 수 있는가?
   - 각 예외별 처리 방식
   - Fail-safe 메커니즘

7. **로깅/모니터링 포인트**:
   - 어디를 로깅할 것인가?
   - 성능 측정 포인트
   - 문제 진단용 정보

8. **테스트 포인트**:
   - Unit test 대상
   - Integration test 대상
   - Edge case와 경계값

9. **확장 가능 포인트**:
   - Phase 2 기능 추가 시 영향 최소화
   - Plug-in 구조 (필요시)

10. **구현 순서 및 의존성**:
    - 어떤 모듈부터 구현할 것인가?
    - 모듈 간 의존성
    - 병렬 구현 가능한 부분

---

### 출력 형식

```
# Stage 5: 기술 설계

## 전체 아키텍처

(ASCII 다이어그램 또는 텍스트 설명)

```
┌─────────────────────────┐
│   KIS API Client        │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  Stock Analysis Module  │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  Report Generator       │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  Kakao Sender           │
└─────────────────────────┘
```

## 주요 모듈 역할

| 모듈 | 책임 | 주요 함수 |
|------|------|---------|
| `kis_client.py` | KIS API 통신 | `get_stock_data()`, `get_watchlist()` |
| `analyzer.py` | 기술적 분석 | `analyze_stock()`, `detect_signals()` |
| `report_gen.py` | 리포트 생성 | `generate_morning_report()` |
| `kakao_sender.py` | 카카오 전송 | `send_message()` (기존 활용) |

## 데이터 흐름

```
1. 08:20 - watchlist_sync.py 실행
   └─ KIS API에서 관심종목 조회
   └─ watchlist.json 업데이트
   └─ 캐시에 저장

2. 08:30 - morning_report.py 실행
   └─ watchlist.json 읽기
   └─ 각 종목 기술적 분석
   └─ 리포트 생성
   └─ 카카오톡 전송
```

## 상태 관리

- **설정 저장소**: Keychain (KIS API 키, 카카오톡 토큰)
  - `inject_to_env()` 사용 (기존 패턴)
- **캐시**: `data/cache/` 폴더
  - KIS 토큰 캐시 (만료 시간 관리)
  - 종목 데이터 캐시 (1시간 유효)

## API/인터페이스 초안

```python
# KIS API Client
def get_stock_data(symbol: str, period: str = "1d") -> Dict:
    """
    Args: symbol (예: "005930"), period ("1d", "1w", "1m")
    Returns: {"price": float, "high": float, "low": float, ...}
    Raises: KISAPIError, ValidationError
    """

# Analyzer
def analyze_stock(data: Dict) -> AnalysisResult:
    """
    Args: stock_data dictionary
    Returns: AnalysisResult(signal: str, confidence: float, reasoning: str)
    """
```

## 예외 처리 포인트

| 위치 | 예외 유형 | 처리 방식 |
|------|---------|---------|
| KIS API 호출 | NetworkError | 재시도 3회, 실패 시 로그 + 스킵 |
| 데이터 파싱 | ValueError | 로그 + 기본값 사용 |
| 카카오톡 전송 | AuthError | Keychain 재로드 + 재시도 |
| 파일 I/O | FileNotFoundError | 생성 또는 기본값 로드 |

## 로깅/모니터링 포인트

- `logs/morning_report.log`: 각 단계별 진행 상황
- `logs/closing_report.log`: 마감 리포트 생성 로그
- DEBUG: API 호출, 데이터 변환
- INFO: 시작/종료, 주요 결정
- ERROR: 실패 시나리오, 예외

## 테스트 포인트

### Unit Tests
- `test_analyzer.py`: 각 분석 함수
  - 정상 데이터, 경계값, 에러 조건
- `test_report_gen.py`: 리포트 생성 로직

### Integration Tests
- 전체 파이프라인 (API → 분석 → 리포트 → 전송)
- Mock KIS API 사용

## 확장 가능 포인트

- **Phase 2**: 텔레그램 봇 추가
  - `kakao_sender.py` 패턴으로 `telegram_sender.py` 작성
- **Phase 2**: 양방향 명령
  - 메시지 핸들러 플러그인 구조
- **Phase 3**: 머신러닝 모델
  - `analyzer.py`의 `analyze_stock()` 함수 확장

## 구현 순서 & 의존성

1. `kis_client.py` (의존성 없음) - 병렬 가능
2. `analyzer.py` (kis_client 필요)
3. `report_gen.py` (analyzer 필요)
4. `main.py` (모두 필요)

## 주요 설계 결정

- **이유**: ...
- **대안 검토**: ...
- **선택 사유**: ...
```

---

### 주의사항

- ✅ stockpilot 기존 구조 명시 (Python, KIS API, Keychain, launchd)
- ✅ 현실적인 구현 가능 수준
- ❌ 너무 상세한 구현 코드 금지 (의사 코드 수준)
- ✅ Codex가 읽고 이해할 수 있도록 명확하게
- ✅ 오류 처리, 성능, 보안 고려
- ✅ Phase 2 기능 추가 시 영향 최소화

---

### 다음 단계

**UI/UX 필요시:**
- **→ Stage 6: UI 요구사항** (aiui)
- **→ Stage 7: UI 플로우** (aiflow)

**그 외:**
- **→ Stage 8: 구현** (aiimpl - Codex)
프롬프트: `prompts/codex/implementation.txt`
산출물: 코드 + `docs/04_implementation/implementation_progress.md`
