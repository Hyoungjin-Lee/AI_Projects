#!/bin/bash

# AI 워크플로우 프로젝트 초기화 스크립트
# 목적: 새 워크플로우 프로젝트용 폴더/파일 생성
# 사용법: ./init_project.sh [프로젝트명]

set -e

PROJECT_NAME="${1:-.}"
PROJECT_DIR="$(pwd)/$PROJECT_NAME"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 로그 함수
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# 메인 로직
main() {
    log_info "프로젝트 초기화 시작: $PROJECT_DIR"

    # 프로젝트 폴더 생성
    mkdir -p "$PROJECT_DIR/docs/01_brainstorm"
    mkdir -p "$PROJECT_DIR/docs/02_planning"
    mkdir -p "$PROJECT_DIR/docs/03_design"
    mkdir -p "$PROJECT_DIR/docs/04_implementation"
    mkdir -p "$PROJECT_DIR/docs/05_qa"
    mkdir -p "$PROJECT_DIR/docs/notes"
    mkdir -p "$PROJECT_DIR/docs/api"
    mkdir -p "$PROJECT_DIR/prompts/claude"
    mkdir -p "$PROJECT_DIR/prompts/codex"
    mkdir -p "$PROJECT_DIR/scripts"
    mkdir -p "$PROJECT_DIR/logs"

    log_success "폴더 구조 생성 완료"

    # Stage 1: brainstorm.md
    if [ ! -f "$PROJECT_DIR/docs/01_brainstorm/brainstorm.md" ]; then
        cat > "$PROJECT_DIR/docs/01_brainstorm/brainstorm.md" << 'EOF'
# Stage 1: 아이디어 구상

## 브레인스토밍 (Brainstorm)

### 프로젝트 개요
(프로젝트 핵심 설명)

### 문제 정의
(해결해야 할 문제 명시)

### 가능한 방향
1. (방향 A)
   - 장점:
   - 단점:
2. (방향 B)
   - 장점:
   - 단점:
3. (방향 C)
   - 장점:
   - 단점:

### 추천안
(가장 현실적인 방향)

### 제약 & 가정
- (제약 사항)
- (가정)

### 다음 단계
Stage 2: 계획 초안
EOF
        log_success "docs/01_brainstorm/brainstorm.md 생성"
    fi

    # Stage 2: plan_draft.md
    if [ ! -f "$PROJECT_DIR/docs/02_planning/plan_draft.md" ]; then
        cat > "$PROJECT_DIR/docs/02_planning/plan_draft.md" << 'EOF'
# Stage 2: 계획 초안

## 기획 초안 (Planning Draft)

### 프로젝트 개요
(프로젝트 개요)

### 목표
- 주요 목표
- 부차 목표

### 사용자 문제 정의
(사용자가 해결하려는 문제)

### 핵심 기능
1. (기능 A)
2. (기능 B)
3. (기능 C)

### 제외 범위
(스코프에서 제외할 항목)

### 사용자 흐름
(기본 사용자 여정 설명)

### 기술적 주의사항
- (주의할 기술 사항)

### 리스크
1. (리스크 A) - 완화 방법
2. (리스크 B) - 완화 방법

### 다음 단계
Stage 3: 계획 검토
EOF
        log_success "docs/02_planning/plan_draft.md 생성"
    fi

    # Stage 3: plan_review.md
    if [ ! -f "$PROJECT_DIR/docs/02_planning/plan_review.md" ]; then
        cat > "$PROJECT_DIR/docs/02_planning/plan_review.md" << 'EOF'
# Stage 3: 계획 검토

## 검토 피드백 (Planning Review)

### 전체 평가
(계획 초안 전체 평가)

### 잘된 점
- (긍정적 측면)

### 문제점
- (개선 필요 부분)

### 누락 사항
- (빠진 요구사항)

### 수정 제안
- (구체적 수정 방안)

### 다음 단계
Stage 4: 계획 통합
EOF
        log_success "docs/02_planning/plan_review.md 생성"
    fi

    # Stage 4: plan_final.md
    if [ ! -f "$PROJECT_DIR/docs/02_planning/plan_final.md" ]; then
        cat > "$PROJECT_DIR/docs/02_planning/plan_final.md" << 'EOF'
# Stage 4: 계획 통합

## 최종 확정 계획 (Planning Final)

### 프로젝트 개요
(확정된 프로젝트 개요)

### 목표
(확정된 목표)

### 사용자/사용 시나리오
(주요 사용자 시나리오)

### 핵심 기능
(우선순위 포함)

### 제외 범위
(최종 스코프)

### 기능 우선순위
1. 우선 (P0)
2. 중요 (P1)
3. 선택 (P2)

### 운영/기술 제약
(제약 사항 최종 정리)

### 리스크 및 가정
(최종 리스크 목록)

### 설계 단계 전달 메모
(Stage 5를 위한 핵심 포인트)

### 다음 단계
Stage 5: 기술 설계
EOF
        log_success "docs/02_planning/plan_final.md 생성"
    fi

    # 개발 기록 파일
    if [ ! -f "$PROJECT_DIR/docs/notes/dev_history.md" ]; then
        cat > "$PROJECT_DIR/docs/notes/dev_history.md" << 'EOF'
# 개발 기록 (Development History)

모든 단계, 결정, 사고의 누적 로그입니다.

## 타임라인

### [YYYY-MM-DD] Stage X - (단계명)
- **담당**: Claude / Codex
- **모델**: Opus / Sonnet / Haiku
- **노력**: Low / Medium / High / XHigh
- **결과**: (완료 여부 및 산출물)
- **이슈**: (차단 요인, 결정 사항)
- **참조**: docs/XX_*/FILE.md

EOF
        log_success "docs/notes/dev_history.md 생성"
    fi

    # 최종 검증 파일
    if [ ! -f "$PROJECT_DIR/docs/notes/final_validation.md" ]; then
        cat > "$PROJECT_DIR/docs/notes/final_validation.md" << 'EOF'
# Stage 11: 최종 검증

## Opus 최종 검증 기록

(최종 검증 결과 기록)

### 적합성 평가
(기획/설계/구현 일치도)

### 치명적 문제
(배포 차단 이슈)

### 권장 수정 사항
(선택 사항 개선안)

### 테스트 단계 이관 가능 여부
(배포 준비 상태)

EOF
        log_success "docs/notes/final_validation.md 생성"
    fi

    # QA 파일들
    if [ ! -f "$PROJECT_DIR/docs/05_qa/qa_scenarios.md" ]; then
        cat > "$PROJECT_DIR/docs/05_qa/qa_scenarios.md" << 'EOF'
# Stage 12: QA 시나리오

## 테스트 시나리오

### 정상 흐름 테스트
- (테스트 케이스)

### 경계값 테스트
- (경계값 케이스)

### 예외 상황 테스트
- (예외 케이스)

### 실패 복구 테스트
- (복구 시나리오)

### 우선순위별 테스트 목록
1. P0 - Critical
2. P1 - Important
3. P2 - Nice to have

### 완료 판단 기준
(테스트 통과 기준)

EOF
        log_success "docs/05_qa/qa_scenarios.md 생성"
    fi

    if [ ! -f "$PROJECT_DIR/docs/05_qa/release_checklist.md" ]; then
        cat > "$PROJECT_DIR/docs/05_qa/release_checklist.md" << 'EOF'
# 배포 전 체크리스트

## Release Checklist

- [ ] 모든 기능 테스트 통과
- [ ] 보안 검토 완료
- [ ] 문서화 최신화
- [ ] 성능 테스트 통과
- [ ] 의존성 업데이트 완료
- [ ] CHANGELOG 업데이트
- [ ] 버전 번호 업데이트
- [ ] 배포 승인 획득
- [ ] 배포 후 검증 계획 수립

EOF
        log_success "docs/05_qa/release_checklist.md 생성"
    fi

    log_success "프로젝트 초기화 완료!"
    log_info "다음 명령어를 실행하세요:"
    echo -e "${BLUE}  cd $PROJECT_DIR${NC}"
    echo -e "${BLUE}  aib  # Stage 1: 아이디어 구상 시작${NC}"
}

# 실행
main
