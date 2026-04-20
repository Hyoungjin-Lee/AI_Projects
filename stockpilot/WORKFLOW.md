# 🔄 AI 기반 개발 워크플로우

> **버전:** 1.2  
> **최종 수정:** 2026-04-19  
> **상태:** 활성화 (XHigh 노력으로 검증, CLI 도구 추가)  
> **범위:** 모든 프로젝트에 재사용 가능하며, 현재 `stockpilot`에 적용 중

---

## 1. 요약

이 워크플로우는 **문서 중심, 역할 분리 개발 프로세스**를 확립합니다:
- **Claude**는 사고, 아키텍처, 검증, QA를 담당
- **Codex**는 구현, 디버깅, 반복을 담당
- **문서** (`docs/` 폴더)가 단일 정보원
- **핸드오프 규칙**이 세션 간 부드러운 전환 가능하게 함

**검증 결과:** ✅ 잘 설계됨, 프로덕션 준비 완료 (아래 1가지 운영 명확화 필요)

---

## 2. 전체 평가

### 잘 설계된 부분
1. **명확한 역할 분리** — Claude와 Codex는 서로 다르고 중복되지 않는 책임
2. **중복 없는 단계** — 13개 단계가 최종 검증 전 루프 없이 논리적으로 흐름
3. **문서 중심** — 모든 산출물이 `docs/`에 정렬되어 세션 독립성 지원
4. **노력 비례 배치** — 리소스 배치(Low/Medium/High/XHigh)가 업무 복잡도와 일치
5. **미래 대비 아키텍처** — Claude→Codex 자동화 경로가 명확함 (3단계 로드맵)

### 해결할 이슈
1. **운영 모드 불명확:** 워크플로우는 *기능 개발* 위주이지만, `stockpilot`는 주로 *실행 모드*(자동화된 launchd 스크립트)로 작동. 명확한 컨텍스트 전환 규칙 필요.
2. **XHigh 노력 과다 사용 위험:** 현재 계획은 XHigh를 최종 검증에만 예약하지만, 일상적 기능에는 너무 비쌀 수 있음. 계층화 권장.
3. **긴급/핫픽스 경로 누락:** 디자인 단계를 건너뛰는 운영 사고나 보안 핫픽스에 대한 명시적 프로세스 없음.

### 적용된 권장사항 ✅
- "운영 컨텍스트" 섹션 추가 (기능 개발 vs 실행 모드)
- 의사결정 트리를 포함한 노력 계층 개선
- 운영 원칙에 핫픽스/사고 프로세스 포함

---

## 3. 핵심 워크플로우: 13단계

| # | 단계 | 담당자 | 모델 | 노력 | 입력 | 산출물 | 예상 시간 |
|---|------|--------|------|------|------|--------|----------|
| 1 | **아이디어 구상** | Claude | Opus | Medium | 사용자 요청/요구사항 | `docs/01_brainstorm/brainstorm.md` | 15-30분 |
| 2 | **계획 초안** | Claude | Sonnet | Medium | 아이디어 구상 결과 | `docs/02_planning/plan_draft.md` | 15-30분 |
| 3 | **계획 검토** | Claude | Sonnet | High | 계획 초안 | `docs/02_planning/plan_review.md` (피드백) | 10-20분 |
| 4 | **계획 통합** | Claude | Sonnet | Medium | 초안 + 검토 피드백 | `docs/02_planning/plan_final.md` | 10-15분 |
| 5 | **기술 설계** | Claude | Opus | High | 확정된 계획 | `docs/03_design/technical_design.md` | 30-60분 |
| 6 | **UI/UX 요구사항** (선택) | Claude | Sonnet | Medium | 기술 설계 (프론트엔드 필요시) | `docs/03_design/ui_requirements.md` | 15-30분 |
| 7 | **UI 플로우 설계** (선택) | Claude | Sonnet | Medium | UI 요구사항 | `docs/03_design/ui_flow.md` + 와이어프레임 | 20-40분 |
| 8 | **구현** | Codex | - | High | 기술 설계 + UI 플로우 (있을 경우) | 코드 + 테스트 + PR/커밋 | 1-8시간 |
| 9 | **코드 리뷰 (1차)** | Claude | Sonnet | High | Codex 구현 결과 | `docs/notes/dev_history.md` (리뷰 로그) | 15-30분 |
| 10 | **수정** | Codex | - | Medium | 코드 리뷰 피드백 | 수정된 코드 + 테스트 | 30분-2시간 |
| 11 | **최종 검증** | Claude | Opus | XHigh 또는 High* | 수정된 코드 + 테스트 결과 | `docs/notes/final_validation.md` | 30분-1시간 |
| 12 | **QA & 릴리스** | Claude | Sonnet | Medium | 검증된 코드 | `docs/04_qa/qa_scenarios.md` + `release_checklist.md` | 15-30분 |
| 13 | **배포 & 아카이브** | Codex | - | Medium | QA 승인 | 병합된 코드 + 업데이트된 `HANDOFF.md` | 가변 |

**노력 계층 참고:**
- **XHigh** 사용 대상: 보안 관련, 아키텍처 수준, 높은 위험 운영 변경
- **High** 사용 대상: 대부분의 기능 검증, 코드 리뷰, 설계 결정
- `*` 11단계: 일상적 기능은 기본값 **High**로 설정, 위 기준 충족시만 **XHigh**로 상향

---

## 4. 운영 컨텍스트: 기능 개발 vs 실행 모드

이 워크플로우는 **기능 개발**(새 기능, 리팩토링, 주요 변경)을 위한 것입니다.

`stockpilot`은 **실행 모드**(자동화된 launchd 스크립트, 지속적 운영)에서도 작동합니다. 이 컨텍스트들은 이 워크플로우를 **사용하지 않습니다:**

### 워크플로우 사용 시점 (기능 개발)
- 새로운 분석 지표 추가
- 핵심 모듈 리팩토링
- 새 API 통합 (Telegram 봇 등)
- 리포트 생성 방식 재설계
- 아키텍처 영향 주요 버그 수정
- **트리거:** "X 기능 구현" 또는 "Y 모듈 리팩토링"

### 워크플로우 건너뛰기 (실행/핫픽스 모드)
- 긴급 프로덕션 수정 (Stage 5 → Stage 8로 직접)
- 데이터 파일 또는 설정 업데이트
- 일상적 유지보수 (로그 정리, 캐시 새로고침)
- 문서 업데이트만 필요
- **트리거:** "closing_report.py의 버그 수정" 또는 "watchlist 업데이트"

**모드 전환 규칙:** 모든 세션에서 `HANDOFF.md`의 **상태** 섹션 확인:
- 상태가 "기능 개발 진행 중" 표시 → WORKFLOW.md 사용
- 상태가 "모든 시스템 정상" 표시 → HANDOFF.md + CLAUDE.md만 사용

---

## 5. 모델 & 노력 전략

### 모델 선택 가이드

| 업무 유형 | 주요 | 백업 | 이유 |
|---------|------|------|------|
| 아이디어 구상, 아키텍처 | **Opus** | Sonnet | 모호하고 창의적인 문제에 강한 추론 |
| 계획, 설계 검토 | **Sonnet** | Opus | 빠른 반복, 충분한 깊이 |
| 코드 리뷰, 검증 | **Sonnet** 또는 **Opus** | - | 일상적은 Sonnet, 중요 경로는 Opus |
| 구현 | **Codex** | - | 전문화된 코딩 환경 |
| 문서화, 요약 | **Haiku** | Sonnet | 빠르고 비용 효율적, 복잡하면 Sonnet |

### 노력 계층 의사결정 트리

```
보안 관련 또는 프로덕션 수준인가?
├─ YES → XHigh (최종 검증에만)
└─ NO
   ├─ 핵심 아키텍처 또는 여러 시스템에 영향을 주는가?
   │  ├─ YES → High
   │  └─ NO
   │     ├─ 새 기능 또는 중요 리팩토링인가?
   │     │  ├─ YES → Medium (계획) → High (코드 리뷰)
   │     │  └─ NO → Medium 또는 Low
   │     └─ 문서화 또는 요약인가?
   │        └─ YES → Low 또는 Medium
```

### 단계별 리소스 추정

| 노력 | 시간 | 토큰 예산 | 일반적 단계 |
|------|------|----------|-----------|
| Low | 5-10분 | 5-15K | 문서화, 요약 |
| Medium | 15-30분 | 15-30K | 계획, 간단한 구현 |
| High | 30-60분 | 30-60K | 코드 리뷰, 기술 설계, 리팩토링 |
| XHigh | 1-2시간 | 60-120K | 최종 검증, 보안 검토, 아키텍처 결정 |

---

## 6. 운영 원칙 (개선됨)

### 핵심 규칙
1. **역할 혼합 금지** — Claude는 구현 안함, Codex는 검증 안함
2. **설계 전에 계획** — Stage 4 확정 없이 Stage 5 진입 금지
3. **코드 전에 설계** — Stage 5 확정 없이 코드 금지 (핫픽스 예외, 별도 기록)
4. **문서 우선** — 모든 산출물 → `docs/` (다음 단계 전)
5. **단일 정보원** — `docs/` > Slack > 채팅 기록

### 검증 규율
- **코드 리뷰 (Stage 9):** 수정 승인 전 최소 요구사항
  - [ ] 모든 테스트 통과
  - [ ] 보안 안티패턴 없음 (하드코딩 인증정보, 미검증 입력 등)
  - [ ] 프로젝트 스타일 가이드 및 기존 패턴 준수
  - [ ] 비자명한 로직은 주석 포함
  - [ ] 중복 코드 없음 (유틸리티로 추출 가능한 경우 제외)
  
- **최종 검증 (Stage 11):** 병합 전
  - [ ] Codex 수정이 모든 리뷰 피드백 반영
  - [ ] 변경사항이 기존 모듈과 깔끔하게 통합
  - [ ] 성능 회귀 없음 (필요시 프로파일링)
  - [ ] 문서화 (docstring, README 업데이트) 완료

### 세션 지속성
- 모든 세션 **시작**은 `HANDOFF.md` 읽기 (현재 상태)
- 모든 세션 **종료**는 `HANDOFF.md` 업데이트 (변경 사항, 다음 업무)
- 워크플로우 단계가 미완료면 `docs/notes/dev_history.md`에 차단 요인 기록
- 참조할 때 명시적 단계 번호 사용 ("현재 Stage 7")

### 핫픽스 / 사고 프로세스 (주 워크플로우 외)
운영 긴급 상황:
1. **심각도 평가:** 시스템이 다운되었거나 저하되었는가? 데이터 위험인가?
2. **YES인 경우:** Stage 8로 건너뛰기 (수정 구현) → Stage 11 (Opus 검증만) → Stage 13 (배포)
3. **NO인 경우:** Stage 1-4를 거쳐 정상적으로 진행
4. **사고 기록:** 항상 `docs/notes/dev_history.md`에 라인 추가하여 사고 및 수정 표시

### 노력 상향 조정
- 단계가 **예상 시간의 2배** 이상 소요되면 일시 중단하고 재평가:
  - 요구사항이 불명확? → Stage 1-4로 돌아가기
  - 구현 차단됨? → 차단 요인 기록, Opus 상담, 계획 업데이트
  - 예상보다 복잡? → 노력 계층 상향, 타임라인 조정

---

## 7. 개선된 파일 & 폴더 구조

```
project-root/
├─ CLAUDE.md                          ← 프로젝트 개요 + 보안 규칙 (먼저 읽기)
├─ HANDOFF.md                         ← 현재 상태 + 다음 업무 (두 번째 읽기)
├─ WORKFLOW.md                        ← 이 파일 (필요시 참조)
├─ README.md                          ← 사용자 대면 프로젝트 문서
│
├─ docs/
│  ├─ 01_brainstorm/
│  │  └─ brainstorm.md               ← Stage 1 산출물: 원시 아이디어, 제약, 가정
│  │
│  ├─ 02_planning/
│  │  ├─ plan_draft.md               ← Stage 2: 문제 진술, 범위, 성공 기준
│  │  ├─ plan_review.md              ← Stage 3: 검토 피드백 (주석 형식 또는 별도 문서)
│  │  └─ plan_final.md               ← Stage 4: 통합된 계획, 설계 준비 완료
│  │
│  ├─ 03_design/
│  │  ├─ technical_design.md         ← Stage 5: 아키텍처, API 계약, 데이터 흐름
│  │  ├─ ui_requirements.md          ← Stage 6 (선택): 사용자 스토리, 수용 기준
│  │  └─ ui_flow.md                  ← Stage 7 (선택): 와이어프레임, 상태 머신, 흐름
│  │
│  ├─ 04_implementation/
│  │  └─ implementation_progress.md  ← Stage 8-10: 구현 진행 상황 및 코드 리뷰 로그
│  │
│  ├─ 05_qa/
│  │  ├─ qa_scenarios.md             ← Stage 12: 테스트 케이스, 엣지 케이스, 성공 기준
│  │  └─ release_checklist.md        ← Stage 12: 배포 전 체크리스트
│  │
│  ├─ notes/
│  │  ├─ dev_history.md              ← 모든 단계, 결정, 사고의 누적 로그
│  │  ├─ decisions.md                ← 결정 이유 (아키텍처 선택지 등)
│  │  └─ final_validation.md         ← Stage 11 산출물: Opus 승인 또는 우려사항
│  │
│  └─ api/ (프로젝트별)
│     └─ [API 참조 문서, 해당시]
│
├─ prompts/                           ← Claude/Codex 워크플로우 재사용 가능 프롬프트
│  ├─ claude/                         ← Claude 전담 단계 프롬프트
│  │  ├─ brainstorm.txt              ← Stage 1: 아이디어 구상 (Opus)
│  │  ├─ planning_draft.txt           ← Stage 2: 계획 초안 (Sonnet)
│  │  ├─ planning_review.txt          ← Stage 3: 계획 검토 (Sonnet)
│  │  ├─ planning_final.txt           ← Stage 4: 계획 통합 (Sonnet)
│  │  ├─ technical_design.txt         ← Stage 5: 기술 설계 (Opus)
│  │  ├─ ui_requirements.txt          ← Stage 6 (선택): UI 요구사항 (Sonnet)
│  │  ├─ ui_flow.txt                  ← Stage 7 (선택): UI 플로우 (Sonnet)
│  │  ├─ code_review.txt              ← Stage 9: 코드 리뷰 (Sonnet)
│  │  ├─ final_review.txt             ← Stage 11: 최종 검증 (Opus)
│  │  └─ qa.txt                       ← Stage 12: QA 시나리오 (Sonnet)
│  │
│  └─ codex/                          ← Codex 전담 단계 프롬프트
│     ├─ implementation.txt           ← Stage 8: 구현 (Codex)
│     └─ revise.txt                   ← Stage 10: 수정 (Codex)
│
├─ scripts/                           ← 자동화 스크립트, 배포 스크립트, CLI 도구
│  ├─ init_project.sh                 ← 프로젝트 초기화 (폴더/파일 생성)
│  ├─ ai_step.sh                      ← 단계 실행 (프롬프트 출력 + 로그 기록)
│  ├─ git_checkpoint.sh               ← Git 체크포인트 + 이력 기록
│  ├─ append_history.sh               ← dev_history 수동 기록
│  ├─ zsh_aliases.sh                  ← zsh alias 설정 (소싱용)
│  ├─ setup_scheduler.sh               ← launchd 스케줄 설정 (기존)
│  └─ run_checks.sh                   ← 배포 전 검증 스크립트
│
├─ src/ (또는 메인 코드 디렉토리)      ← 프로젝트 소스 코드
├─ tests/                             ← 테스트 파일 (PR/리뷰에서 자동 참조)
│
└─ [프로젝트별 디렉토리]
   ├─ data/ (데이터 파일 필요시)
   ├─ logs/ (로깅 디렉토리 필요시)
   └─ reports/ (산출물 디렉토리 필요시)
```

**원본과의 주요 차이:**
- `docs/04_implementation/` 추가 (Stage 8-10 구현 진행 상황)
- `docs/05_qa/`로 QA 폴더 이동 (번호 조정)
- `docs/notes/dev_history.md` 추가 (누적 로그)
- `docs/notes/final_validation.md` 추가 (Stage 11 승인)
- `prompts/` 폴더 추가 (Claude/Codex 재사용 가능 프롬프트, 단계명 기반)
- `scripts/` 폴더 확장 (CLI 자동화 도구, alias 파일 추가)

---

## 8. Claude ↔ Codex 통합 로드맵

### Stage 1: 수동 핸드오프 (현재)
**일정:** 현재 ~ 1개월  
**프로세스:**
1. Claude가 Stage 1-7 완료, `docs/03_design/technical_design.md`에 기록
2. Claude가 수동으로 **technical_design.md를 Codex 프롬프트로 복사** (또는 문서 링크 공유)
3. Codex가 설계 문서를 읽고 Stage 8 시작
4. Codex 구현 (Stage 8) 후, Claude가 코드 읽고 Stage 9 진행

**마찰점:** 복사-붙여넣기 및 컨텍스트 전환  
**완화:** 설계 문서에서 일관된 포맷 사용, Codex가 파일 맨 앞부터 읽기

### Stage 2: 자동 브리프 (2-3개월)
**일정:** Codex 통합 가능시  
**프로세스:**
1. Stage 5 확정 후, Claude가 자동으로 `prompts/codex/08_implement.md` 생성
2. Claude가 **프로그래매틱하게** Codex에 브리프 전달 (MCP 도구 또는 API 래퍼 경유)
3. Codex가 자동으로 브리프 읽음, 요약으로 인정, Stage 8 시작
4. Codex가 Stage 8 완료 후, 산출물 참조가 Claude로 돌아옴
5. Claude가 자동으로 코드 diff 읽고 Stage 9 진행

**얻는 것:** 컨텍스트 손실 없음, 더 빠른 피드백 루프  
**필요 조건:** Codex API 주변 커스텀 MCP 도구 또는 래퍼 스크립트

### Stage 3: 완전 자동화 (4개월+)
**일정:** 향후, MCP 인프라 성숙시  
**프로세스:**
1. 사용자 시작: `"X 구현"` (채팅 또는 API경유)
2. **Claude Agent** (이 워크플로우)가 자율적으로:
   - Stage 1-7 (계획/설계)
   - **Codex MCP 도구** 호출 (Stage 8: 구현)
   - Stage 9-13 (리뷰, 검증, QA, 배포)
3. Claude가 최종 요약 + 병합된 코드 + 변경로그 반환
4. 사용자가 검토하고 PR 병합 또는 수동 배포

**얻는 것:** 진정한 엔드-투-엔드 자동화, 단일 에이전트 경험  
**위험:** 강건한 MCP 에러 처리, 타임아웃 관리 필요

---

## 9. 세션 핸드오프 & 지속성 규칙

### 읽기 순서 (매 새 세션)
1. **CLAUDE.md** — 프로젝트 규칙, 보안 절대, 핵심 파일, 실행 스케줄
2. **HANDOFF.md** — 현재 상태, 최근 변경, 다음 업무, 차단 요인
3. **WORKFLOW.md** — 이 문서 (기능 개발이면 1-3절 훑기, 4절+ 필요시 참조)
4. **관련 docs/** — 현재 작업 중인 단계 문서만

### 쓰기 순서 (세션 종료)
1. **현재 단계 문서 업데이트** (예: `plan_final.md`, `technical_design.md`)
2. **`docs/notes/dev_history.md`에 항목 추가:**
   - 단계 번호 + 날짜
   - 완료된 내용
   - 차단 요인 또는 결정사항
   - 산출물 문서 링크
3. **`HANDOFF.md` 업데이트:**
   - 현재 상태 (예: "Stage 5 완료, 코드 리뷰 대기")
   - 다음 세션 업무 (예: "Stage 8: watchlist_sync.py 구현")
   - 긴급 차단 요인
   - 관련 문서 링크
4. **다음 세션 프롬프트 생성 (필수):**
   - `HANDOFF.md` 하단 `## 📋 다음 세션 시작 프롬프트` 섹션에 작성
   - 아래 프롬프트 작성 규칙 참고

### 다음 세션 프롬프트 작성 규칙

사용자가 "다음 세션에서 이어서 할 수 있게 해줘"라고 하면 반드시:

1. `HANDOFF.md` 업데이트 (미완료 이슈, 다음 우선순위 등)
2. `HANDOFF.md` 하단에 `## 📋 다음 세션 시작 프롬프트` 섹션 추가 또는 갱신

**프롬프트 작성 원칙:**
- 복사해서 바로 붙여넣을 수 있을 것 (설명 필요 없이)
- 오늘 한 작업 요약 포함 (컨텍스트 복원용)
- 다음 할 작업 명확히 명시 (파일명·이슈번호 포함)
- 관련 파일 경로 포함
- 핵심 판단 기준·설계 결정 포함 (새 세션이 다시 고민하지 않도록)

**프롬프트 템플릿:**
```
stockpilot 프로젝트 이어서 진행해줘.
HANDOFF.md 와 CLAUDE.md 파일을 먼저 읽어줘.
경로: /Users/geenya/projects/AI_Projects/stockpilot/

현재 상태 요약:
- [버전] 완료 ([날짜])
- [오늘 완료한 작업 1~3줄]

다음 할 작업:
1. [우선순위 1 — 파일명·이슈 포함]
2. [우선순위 2]
3. [기타]

참고 사항:
- [핵심 설계 결정이나 주의사항]

어디서부터 시작할까?
```

### HANDOFF 항목 예시
```markdown
## 상태 (2026-04-20 기준, Session 5)

현재 단계: 8 (Codex 구현)

**완료:**
- ✅ Stage 1-4: 계획 확정
- ✅ Stage 5: 기술 설계 최종화 (참조: docs/03_design/technical_design.md)

**진행 중:**
- 🔄 Stage 8: Codex가 watchlist_sync.py 구현 중
  - 브리프: prompts/codex/08_implement.md
  - 예상 완료: 2026-04-21

**다음 세션:**
- Stage 9: Claude 코드 리뷰 (diff 읽기, 설계와 검증)
- 예상 노력: High, 30분

**차단 요인:**
- 현재 없음

**참조:**
- 최종 계획: docs/02_planning/plan_final.md
- 기술 설계: docs/03_design/technical_design.md
- 개발 기록: docs/notes/dev_history.md
```

---

## 10. 독립 검증 프로토콜 (확증 편향 방지)

**Stage 11 (최종 검증)에서 반드시 적용. 복잡한 로직 변경 시에도 권장.**

### 왜 필요한가?

같은 세션에서 코드를 작성하고 검증하면 **확증 편향(confirmation bias)**이 발생한다.
내가 만든 코드를 내가 검토하면 "이건 맞을 것"이라는 전제가 생겨 실제 버그를 놓친다.

### 독립 검증 방법

```
1. 새 Claude 세션 시작 (현재 세션의 컨텍스트 없음)
2. 아래 프롬프트 템플릿 사용
3. 변경된 코드 전체를 붙여넣기 (이전 대화 없이)
4. 독립 세션의 검증 결과를 현재 세션에 반영
```

### 프롬프트 템플릿

```markdown
# 독립 코드 검증 요청

아래 코드를 **완전히 처음 보는 코드**로 검토해줘.
이전 대화 없음. 맥락 없음. 순수 코드 리뷰만.

## 검토 요청 사항
1. 버그나 로직 오류가 있는가?
2. 보안 취약점이 있는가? (특히 인증정보 노출)
3. 예외 처리가 충분한가?
4. 개선할 점이 있는가?

## 코드
[변경된 파일 전체 내용 붙여넣기]

## 배경 (최소한만)
- Python 3.14, macOS launchd 환경
- KIS Open API 클라이언트 사용
- Keychain에서 인증정보 로드 (inject_to_env())
```

### 적용 기준

| 변경 규모 | 검증 방법 |
|-----------|-----------|
| 1-10줄 수정 | 현재 세션 self-review로 충분 |
| 10-50줄 수정 | 독립 검증 권장 |
| 50줄+ 또는 신규 파일 | 독립 검증 필수 |
| 새 에이전트/오케스트레이터 | 독립 검증 필수 |

### 검증 결과 기록

독립 검증 완료 후 `docs/05_qa_release/qa_report.md`에 기록:

```markdown
## 독립 검증 결과 (YYYY-MM-DD)
- 검증 대상: [파일명]
- 발견된 이슈: [있으면 목록]
- 조치 사항: [없으면 "없음"]
- 최종 판정: PASS / FAIL
```

---

## 11. Claude 세션 초기화 템플릿

**워크플로우 추적 기능 작업을 시작하는 모든 새 세션에서 이 프롬프트 사용.**

```markdown
# 세션 시작 체크리스트

워크플로우에서 추적하는 기능 또는 리팩토링 작업을 시작합니다.

## 1단계: 현재 상태 이해하기
1. `/path/to/project/CLAUDE.md` 읽기 (보안, 프로젝트 개요)
2. `/path/to/project/HANDOFF.md` 읽기 (현재 상태, 지난 세션 산출물)
3. 확인: 현재 어느 단계에 있는가?

## 2단계: 역할 파악하기
- 나는 Claude(계획/검증)인가, 아니면 Codex가 코드를 넘겨받았는가?
- Claude라면: 다음 단계는?
- 코드 리뷰라면: 구현 diff를 먼저 읽기

## 3단계: 관련 문서 읽기
- 단계에 진입한다면, `docs/` 관련 문서 읽기 (예: Stage 5 전에 `plan_final.md`)
- 단계를 계속한다면, 마지막 `dev_history.md` 항목 읽기

## 4단계: 작업 시작
- WORKFLOW.md Section 3의 단계 정의 사용
- 노력 계층 및 시간 추정 참조
- 올바른 파일에 산출물 저장 (예: `docs/03_design/technical_design.md`)
- 완료 후 `docs/notes/dev_history.md`에 작업 기록

## 5단계: 핸드오프
- `HANDOFF.md`를 산출물 및 다음 세션 업무로 업데이트
- 업데이트된 `docs/` 및 `HANDOFF.md` 커밋 또는 저장

---

질문? WORKFLOW.md Section 4-6 참조 (모드 컨텍스트, 노력 가이드, 원칙).
```

---

## 12. 기존 stockpilot 패턴과의 통합

이 워크플로우는 기존 `stockpilot` 구조를 **보완**합니다 (대체 X):

### 변경 없는 부분
- **CLAUDE.md:** 프로젝트 규칙, 보안, 핵심 파일, 실행 스케줄의 권위 있는 정보원 유지
- **HANDOFF.md:** 세션 간 상태 추적기 유지 (이제 워크플로우 단계 정보 포함)
- **실행 모드:** Launchd 스케줄, 자동화 스크립트, `.skills/` 모듈 — 모두 미변경

### 신규
- **WORKFLOW.md:** **기능 개발만**을 위한 구조화된 프로세스 추가
- **docs/01-04/:** 계획, 설계, QA 산출물용 새 서브디렉토리
- **docs/notes/:** 결정 추적 및 사고 기록용 새 누적 로그

### 스타트업 프로세스 미변경
```bash
cd /Users/geenya/projects/AI_Projects/stockpilot
venv/bin/python3 morning_report/morning_report.py --dry-run
# 여전히 작동. 실행 모드 영향 없음.
```

### 예시: 새 기능 추가 (Telegram Bot)
1. 새 요청: "Telegram 봇 통합, 양방향 명령 가능"
2. HANDOFF.md 상태 확인 → "모든 시스템 정상" → **실행 모드**
3. **기능 개발 모드**로 전환: Stage 1 시작 (아이디어 구상)
4. WORKFLOW.md Stage 1-7 (계획/설계) 따르기, `docs/`에 산출물 저장
5. Codex에 Stage 8 핸드오프 (`telegram_bot.py` 구현)
6. 완료 후 **실행 모드** 복귀 — launchd 업데이트, HANDOFF.md 업데이트
7. 다음 세션: HANDOFF.md 읽기, "Telegram 봇 배포됨" 확인 → CLAUDE.md/실행 모드로 복귀

---

## 13. CLI 자동화 도구 & 별칭 설정

이 섹션은 `scripts/` 폴더의 4개 자동화 도구와 zsh alias 설정 방법을 설명합니다.

### 도구 개요

| 도구 | 파일 | 목적 | 사용 시점 |
|------|------|------|----------|
| **프로젝트 초기화** | `init_project.sh` | 새 워크플로우 프로젝트용 폴더/파일 생성 | 프로젝트 시작 시 1회 |
| **단계 실행** | `ai_step.sh` | 현재 단계의 프롬프트 출력, 로그 기록 | 매 단계마다 |
| **Git 체크포인트** | `git_checkpoint.sh` | Git 커밋 + `dev_history.md` 자동 기록 | 단계 완료 후 |
| **수동 기록** | `append_history.sh` | `dev_history.md` 수동 항목 추가 | 필요시 |

### zsh alias 설정

**1단계: alias 파일 소싱**

`.zshrc`에 다음 한 줄 추가:

```bash
source /Users/geenya/projects/AI_Projects/stockpilot/scripts/zsh_aliases.sh
```

**2단계: 셸 새로고침**

```bash
source ~/.zshrc
```

### 사용 예시

#### 예시 1: 새 기능 프로젝트 시작

```bash
cd /Users/geenya/projects/AI_Projects/stockpilot

# 프로젝트 초기화 (폴더/파일 생성)
aiinit

# Stage 1 시작: 아이디어 구상
aib
# → 브레인스토밍 프롬프트 출력, 결과를 docs/01_brainstorm/brainstorm.md에 저장

# 작업 완료 후 Git 체크포인트
aigit "Stage 1 완료: Telegram 봇 아이디어 구상"
# → 변경사항 커밋 + dev_history.md 자동 기록
```

#### 예시 2: 계획 단계 진행

```bash
# Stage 2: 계획 초안
aipd
# → 프롬프트 출력, docs/02_planning/plan_draft.md에 저장

aigit "Stage 2 완료: 계획 초안 작성"

# Stage 3: 계획 검토
aipr
aigit "Stage 3 완료: 계획 검토"

# Stage 4: 계획 통합
aipf
aigit "Stage 4 완료: 최종 계획 확정"
```

#### 예시 3: 기술 설계 단계

```bash
# Stage 5: 기술 설계
aitd
# → Opus 수준 설계 프롬프트 출력

aigit "Stage 5 완료: 기술 설계 최종화"

# Codex에 핸드오프 준비
# prompts/codex/implementation.md를 technical_design.md 기반으로 수동 생성
```

#### 예시 4: 수동 로그 기록

정기적으로 단계 진행 상황을 기록하고 싶다면:

```bash
aihist "Stage 9 진행 중: 코드 리뷰 완료, 5개 이슈 찾음"
# → docs/notes/dev_history.md에 타임스탬프와 함께 추가
```

### alias 목록

| alias | 명령 | 목적 |
|-------|------|------|
| `aip` | `ai_step.sh` (대화형) | 단계 선택하여 실행 |
| `aib` | `ai_step.sh brainstorm` | Stage 1: 아이디어 구상 |
| `aipd` | `ai_step.sh planning_draft` | Stage 2: 계획 초안 |
| `aipr` | `ai_step.sh planning_review` | Stage 3: 계획 검토 |
| `aipf` | `ai_step.sh planning_final` | Stage 4: 계획 통합 |
| `aitd` | `ai_step.sh technical_design` | Stage 5: 기술 설계 |
| `aiui` | `ai_step.sh ui_requirements` | Stage 6: UI 요구사항 |
| `aiflow` | `ai_step.sh ui_flow` | Stage 7: UI 플로우 |
| `aiimpl` | `ai_step.sh implementation` | Stage 8: 구현 (Codex) |
| `aireview` | `ai_step.sh code_review` | Stage 9: 코드 리뷰 |
| `airevise` | `ai_step.sh revise` | Stage 10: 수정 (Codex) |
| `aifinal` | `ai_step.sh final_review` | Stage 11: 최종 검증 |
| `aiqa` | `ai_step.sh qa` | Stage 12: QA 시나리오 |
| `aigit` | `git_checkpoint.sh` | Git 커밋 + dev_history 기록 |
| `aihist` | `append_history.sh` | dev_history 수동 기록 |
| `aiinit` | `init_project.sh` | 프로젝트 초기화 |

---

## 14. 단계명 표준 & 매핑 테이블

### 단계명 통일 규칙

워크플로우에서는 두 가지 표기법을 혼용합니다:

1. **Stage 번호**: 공식 단계 (1-13)
2. **단계명 문자열**: CLI/alias에서 사용 (brainstorm, planning_draft 등)

이 테이블은 두 표기법의 매핑을 제공합니다.

### 전체 매핑 테이블

| Stage | 단계명 (영문) | 한국어 | 담당 | 모델 | 프롬프트 파일 | 산출물 파일 |
|-------|-------------|--------|------|------|-------------|-----------|
| 1 | `brainstorm` | 아이디어 구상 | Claude | Opus | `prompts/claude/brainstorm.md` | `docs/01_brainstorm/brainstorm.md` |
| 2 | `planning_draft` | 계획 초안 | Claude | Sonnet | `prompts/claude/planning_draft.md` | `docs/02_planning/plan_draft.md` |
| 3 | `planning_review` | 계획 검토 | Claude | Sonnet | `prompts/claude/planning_review.md` | `docs/02_planning/plan_review.md` |
| 4 | `planning_final` | 계획 통합 | Claude | Sonnet | `prompts/claude/planning_final.md` | `docs/02_planning/plan_final.md` |
| 5 | `technical_design` | 기술 설계 | Claude | Opus | `prompts/claude/technical_design.md` | `docs/03_design/technical_design.md` |
| 6 | `ui_requirements` | UI 요구사항 | Claude | Sonnet | `prompts/claude/ui_requirements.md` | `docs/03_design/ui_requirements.md` |
| 7 | `ui_flow` | UI 플로우 | Claude | Sonnet | `prompts/claude/ui_flow.md` | `docs/03_design/ui_flow.md` |
| 8 | `implementation` | 구현 | Codex | - | `prompts/codex/implementation.md` | 코드 + `docs/04_implementation/implementation_progress.md` |
| 9 | `code_review` | 코드 리뷰 | Claude | Sonnet | `prompts/claude/code_review.md` | `docs/04_implementation/implementation_progress.md` (리뷰 로그) |
| 10 | `revise` | 수정 | Codex | - | `prompts/codex/revise.md` | 수정된 코드 + `docs/04_implementation/implementation_progress.md` |
| 11 | `final_review` | 최종 검증 | Claude | Opus | `prompts/claude/final_review.md` | `docs/notes/final_validation.md` |
| 12 | `qa` | QA & 릴리스 | Claude | Sonnet | `prompts/claude/qa.md` | `docs/05_qa/qa_scenarios.md` + `release_checklist.md` |
| 13 | `deployment` | 배포 & 아카이브 | Codex | - | - | 병합된 코드 + `HANDOFF.md` 업데이트 |

### 프롬프트 파일 선택 가이드

`ai_step.sh <stage_name>` 실행 시, 자동으로 해당 프롬프트 파일을 로드합니다:

```bash
aib         # → prompts/claude/brainstorm.md 로드
aipd        # → prompts/claude/planning_draft.md 로드
aitd        # → prompts/claude/technical_design.md 로드
aiimpl      # → prompts/codex/implementation.md 로드
```

### stockpilot 프로젝트 매핑

stockpilot의 실행 모드 (기존 CLAUDE.md)와 워크플로우 기능 개발 모드의 관계:

| 운영 스크립트 | 기능 개발 시 해당 Stage |
|---------|-------------|
| `morning_report.py` | Stage 5 (기술 설계) |
| `closing_report.py` | Stage 5 (기술 설계) |
| `stock_discovery.py` | Stage 5 (기술 설계) |
| 새 지표 추가 | Stage 1-7 (계획 + 설계) |
| 보안 핫픽스 | Stage 8 직접 (핫픽스 경로) |
| 데이터 파일 업데이트 | Stage 8로 건너뛰기 (실행 모드) |

---

## 14. 문제 해결 & FAQ

### Q: Stage 8 중간에 Codex가 차단됨. 어떻게 하나?
**A:** 차단 요인을 `docs/notes/dev_history.md`에 기록하고 `HANDOFF.md` 업데이트. 다음 세션에서 Claude가:
- technical_design.md (Stage 5) 수정하여 차단 요인 해결 후 Codex 재브리프
- 또는 Opus에 빠른 상담 요청 (Stage 5 전체 재작업 X)

### Q: 긴급 핫픽스에도 이 워크플로우 사용?
**A:** 아니오, 핫픽스는 Stage 8로 직접 건너뛰기 (구현) → Stage 11 (Opus 검증만) → Stage 13 (배포). 항상 `dev_history.md`에 사고로 기록.

### Q: 계획이 3세션 걸리면?
**A:** 문제없음. `HANDOFF.md` 및 누적 문서 계속 업데이트. 워크플로우는 시간 제한 없이 논리적 순서만 강제.

### Q: 백엔드만 하는 기능은 Stage 6 & 7 (UI) 건너뛸 수?
**A:** 네, **(선택)**으로 표시됨. Stage 5에서 직접 Stage 8로 진행.

### Q: 누가 기능이 "프로덕션 준비 완료"인지 결정? (Stage 13)
**A:** 보통 코드 리뷰어 (Claude, Stage 9)가 프로젝트 소유자와 협의. `docs/04_qa/release_checklist.md` 체크리스트가 게이트.

---

## 16. 문서 유지 & 아카이빙

### 분기별 검토 (3개월마다)
- `docs/notes/dev_history.md` 감시하여 교훈 수집
- 패턴 발견시 (예: "Stage 5는 항상 2배 더 소요") Section 3의 노력 추정 업데이트
- 완료된 기능을 `docs/archive/`로 요약과 함께 아카이빙

### 연간 업데이트
- 이 전체 WORKFLOW.md를 실제 사용 현황과 비교 검토
- Claude/Codex 릴리스 노트에 근거해 모델 추천 업데이트
- 팀 피드백 수집 및 개선사항 반영

---

## 15. 에이전트 구성

이 워크플로우는 **4개의 전담 에이전트**로 운영한다.
Codex는 에이전트가 아닌 외부 구현 도구로 취급한다.

### 설계 원칙

1. **설계사 ≠ 검증관** — 설계한 에이전트가 검증하면 자기 편향이 생긴다. 반드시 분리.
2. **기획가의 Stage 1은 Opus** — 방향성을 잘못 잡으면 이후 전체가 무너진다. 브레인스토밍에 Opus를 투자하는 게 가장 비용 효율적.
3. **Codex는 도구** — Stage 8(구현), Stage 10(수정)은 Codex가 담당. 에이전트 구성에서 제외.

---

### 에이전트 역할표

| 에이전트 | 담당 Stage | 주 모델 | Effort |
|---------|-----------|---------|--------|
| 🧠 기획가 (Planner) | 1, 2, 3, 4 | Sonnet (Stage 1만 Opus) | Medium~High |
| 🏗️ 설계사 (Designer) | 5, 6, 7 | Opus (Stage 5) / Sonnet (Stage 6~7) | Medium~High |
| 🔍 검증관 (Reviewer) | 9, 11 | Sonnet (Stage 9) / Opus (Stage 11) | High~XHigh |
| 🧪 QA관 (QA Engineer) | 12, 13 | Sonnet | Medium |
| ⚙️ Codex (외부 도구) | 8, 10 | - | - |

---

### 에이전트별 상세

#### 🧠 기획가 (Planner)
- **담당:** Stage 1~4 (브레인스토밍 → 기획 초안 → 기획 검증 → 기획 통합)
- **모델:** Sonnet (Stage 1만 Opus)
- **겸업 이유:** 4단계가 같은 문서를 계속 다듬는 흐름. 컨텍스트가 이어지므로 한 에이전트가 담당해야 일관성 유지.
- **산출물:** `docs/02_planning/plan_final.md` (Stage 4 완료 시)

#### 🏗️ 설계사 (Designer)
- **담당:** Stage 5~7 (기술 설계 → UI/UX 요구사항 → UI 플로우)
- **모델:** Opus (Stage 5), Sonnet (Stage 6, 7)
- **겸업 이유:** Stage 5 산출물이 6~7의 입력이 된다. 기술 제약과 UI 흐름을 동시에 고려 가능.
- **산출물:** `docs/03_design/technical_design.md` (Codex 구현 브리프)
- **주의:** 검증관과 역할 혼용 금지.

#### 🔍 검증관 (Reviewer)
- **담당:** Stage 9 (1차 코드 리뷰), Stage 11 (최종 검증)
- **모델:** Sonnet (Stage 9), Opus (Stage 11)
- **겸업 이유:** 두 단계 모두 "코드가 설계 의도에 맞는지" 검증하는 동일한 성격.
- **독립성 원칙:** 설계사와 다른 에이전트여야 함. 자기 설계를 자기가 검증하면 편향 발생.
- **최종 검증 루프:** 최대 3회 반복. XHigh Effort 적용.

#### 🧪 QA관 (QA Engineer)
- **담당:** Stage 12 (QA 시나리오 & 릴리스 체크리스트), Stage 13 (배포 & 아카이브)
- **모델:** Sonnet
- **겸업 이유:** QA 시나리오 작성과 릴리스 체크리스트는 같은 성격. 실행 QA(로그 확인)도 담당.
- **산출물:** `docs/05_qa/qa_scenarios.md`, `docs/05_qa/release_checklist.md`

---

### 전체 흐름도

```
🧠 기획가          🏗️ 설계사          ⚙️ Codex          🔍 검증관          🧪 QA관
Stage 1 (Opus)  →
Stage 2 (Sonnet) →
Stage 3 (Sonnet) →
Stage 4 (Sonnet) → Stage 5 (Opus)  →
                   Stage 6 (Sonnet) →
                   Stage 7 (Sonnet) → Stage 8 (구현)  →
                                      Stage 10 (수정) → Stage 9 (Sonnet) →
                                                        Stage 11 (Opus)  →
                                                                           Stage 12 (Sonnet)
                                                                           Stage 13 (Sonnet)
```

---

### 핫픽스 시 에이전트 구성

긴급 핫픽스는 기획가/설계사 생략:
```
⚙️ Codex → 🔍 검증관 (Stage 11, Opus) → 🧪 QA관 (Stage 13)
```

---

## 16. 버전 기록

| 날짜 | 버전 | 변경사항 |
|------|------|---------|
| 2026-04-18 | 1.2 | 에이전트 구성 섹션 추가 (섹션 15): 기획가/설계사/검증관/QA관 4개 에이전트, 설계-검증 분리 원칙, 핫픽스 에이전트 구성 |
| 2026-04-18 | 1.1 | CLI 자동화 도구 & alias 추가 (섹션 12), 단계명 표준 & 매핑 테이블 (섹션 13), prompts 폴더 단계명 기반으로 통일, docs/04_implementation/ 추가, scripts/ CLI 도구 4개 추가 |
| 2026-04-18 | 1.0 | 초기 XHigh 검증 + 공개. 운영 컨텍스트 전환, 노력 계층 가이드, 핫픽스 프로세스 반영. |

---

## 관련 문서

| 문서 | 목적 |
|------|------|
| `CLAUDE.md` | 프로젝트 규칙, 보안, 핵심 파일 (매 세션 먼저 읽기) |
| `HANDOFF.md` | 현재 상태 및 다음 업무 (매 세션 두 번째 읽기) |
| `docs/01_brainstorm/brainstorm.md` | Stage 1 산출물 |
| `docs/02_planning/plan_final.md` | Stage 4 산출물 (확정된 계획) |
| `docs/03_design/technical_design.md` | Stage 5 산출물 (Codex용 설계 브리프) |
| `docs/notes/dev_history.md` | 모든 단계 및 결정의 누적 로그 |
| `scripts/zsh_aliases.sh` | zsh alias 설정 (소싱용) |
| `prompts/claude/` | Claude 단계별 프롬프트 템플릿 |
| `prompts/codex/` | Codex 단계별 프롬프트 템플릿 |

---

*이 워크플로우는 생명력 있는 문서입니다. 피드백 및 개선사항 환영합니다. 최종 검증: 2026-04-18 (XHigh 노력).*

---
