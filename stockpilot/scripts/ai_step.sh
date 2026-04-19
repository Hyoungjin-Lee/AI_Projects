#!/usr/bin/env zsh

# AI 워크플로우 단계 실행 스크립트
# 목적: 현재 단계의 프롬프트 출력 및 로그 기록
# 사용법: ./ai_step.sh <stage_name> 또는 ./ai_step.sh (대화형)

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
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

# 프롬프트 파일 경로 확인
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PROMPTS_DIR="$PROJECT_DIR/prompts"
LOGS_DIR="$PROJECT_DIR/logs"

# 로그 디렉토리 생성
mkdir -p "$LOGS_DIR"

# 단계명 → 파일명 매핑 (Claude)
declare -A CLAUDE_STAGES=(
    [brainstorm]="brainstorm"
    [planning_draft]="planning_draft"
    [planning_review]="planning_review"
    [planning_final]="planning_final"
    [technical_design]="technical_design"
    [ui_requirements]="ui_requirements"
    [ui_flow]="ui_flow"
    [code_review]="code_review"
    [final_review]="final_review"
    [qa]="qa"
)

# 단계명 → 파일명 매핑 (Codex)
declare -A CODEX_STAGES=(
    [implementation]="implementation"
    [revise]="revise"
)

# 전체 단계 정보
declare -A STAGE_INFO=(
    [brainstorm]="Stage 1: 아이디어 구상|Claude|Opus|Medium"
    [planning_draft]="Stage 2: 계획 초안|Claude|Sonnet|Medium"
    [planning_review]="Stage 3: 계획 검토|Claude|Sonnet|High"
    [planning_final]="Stage 4: 계획 통합|Claude|Sonnet|Medium"
    [technical_design]="Stage 5: 기술 설계|Claude|Opus|High"
    [ui_requirements]="Stage 6: UI 요구사항|Claude|Sonnet|Medium"
    [ui_flow]="Stage 7: UI 플로우|Claude|Sonnet|Medium"
    [implementation]="Stage 8: 구현|Codex|-|High"
    [code_review]="Stage 9: 코드 리뷰|Claude|Sonnet|High"
    [revise]="Stage 10: 수정|Codex|-|Medium"
    [final_review]="Stage 11: 최종 검증|Claude|Opus|XHigh"
    [qa]="Stage 12: QA & 릴리스|Claude|Sonnet|Medium"
)

# 대화형 선택
interactive_select() {
    log_info "단계를 선택하세요:"
    echo ""

    # Claude 단계
    echo -e "${CYAN}=== Claude 단계 ===${NC}"
    local i=1
    local -a stages
    for stage in "${!CLAUDE_STAGES[@]}"; do
        stages+=("$stage")
        echo "$i) $stage"
        i=$((i+1))
    done

    # Codex 단계
    echo ""
    echo -e "${CYAN}=== Codex 단계 ===${NC}"
    for stage in "${!CODEX_STAGES[@]}"; do
        stages+=("$stage")
        echo "$i) $stage"
        i=$((i+1))
    done

    echo ""
    read -p "선택 (1-$i): " choice

    if [ "$choice" -ge 1 ] && [ "$choice" -le "${#stages[@]}" ]; then
        STAGE_NAME="${stages[$((choice-1))]}"
    else
        log_error "잘못된 선택"
        exit 1
    fi
}

# 프롬프트 출력
show_prompt() {
    local stage_name="$1"
    local prompt_file=""
    local stage_type=""

    # 단계 유형 결정
    if [[ -v CLAUDE_STAGES[$stage_name] ]]; then
        prompt_file="$PROMPTS_DIR/claude/${CLAUDE_STAGES[$stage_name]}.txt"
        stage_type="Claude"
    elif [[ -v CODEX_STAGES[$stage_name] ]]; then
        prompt_file="$PROMPTS_DIR/codex/${CODEX_STAGES[$stage_name]}.txt"
        stage_type="Codex"
    else
        log_error "알 수 없는 단계: $stage_name"
        exit 1
    fi

    # 단계 정보 출력
    IFS='|' read -r stage_full agent model effort <<< "${STAGE_INFO[$stage_name]}"
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}$stage_full${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "담당: ${YELLOW}$agent${NC} | 모델: ${YELLOW}$model${NC} | 노력: ${YELLOW}$effort${NC}"
    echo ""

    # 프롬프트 파일 확인
    if [ ! -f "$prompt_file" ]; then
        log_warn "프롬프트 파일이 없습니다: $prompt_file"
        log_info "아래 프롬프트 템플릿을 참고하여 작업하세요."
        echo ""
        echo -e "${CYAN}[프롬프트 템플릿]${NC}"
        case "$stage_name" in
            brainstorm)
                cat << 'EOF'
현재 단계: brainstorm (Stage 1)
목표: 프로젝트 방향성 탐색, 가능한 접근 방식 비교, 현실적인 방향 추천
출력 형식:
1. 문제 정의
2. 가능한 방향 3개
3. 각 방향의 장점/단점
4. 가장 현실적인 추천안
5. 다음 단계에서 결정할 질문
6. 다음 단계 추천: planning_draft
EOF
                ;;
            planning_draft)
                cat << 'EOF'
현재 단계: planning_draft (Stage 2)
목표: 브레인스토밍 결과를 바탕으로 기획 초안 작성
출력 형식:
1. 프로젝트 개요 | 2. 목표 | 3. 사용자 문제 정의 | 4. 핵심 기능 | 5. 제외 범위
6. 예상 사용자 흐름 | 7. 기술적 주의사항 | 8. 리스크 | 9. 다음 단계: planning_review
EOF
                ;;
            technical_design)
                cat << 'EOF'
현재 단계: technical_design (Stage 5)
목표: 확정된 기획을 바탕으로 기술 설계 작성
반드시 포함:
1. 전체 아키텍처 | 2. 주요 모듈 역할 | 3. 데이터 흐름 | 4. 상태 관리 방식
5. API/인터페이스 초안 | 6. 예외 처리 포인트 | 7. 로깅/모니터링 | 8. 테스트 포인트
9. 확장 가능 포인트 | 10. 다음 단계: implementation
EOF
                ;;
            implementation)
                cat << 'EOF'
현재 단계: implementation (Stage 8)
목표: 기술 설계를 바탕으로 구현
구현 원칙: MVP 우선, 과한 추상화 금지, 실행 가능한 코드 중심
출력 형식:
1. 구현 대상 요약 | 2. 권장 파일 구조 | 3. 구현 우선순위
4. 코드 작성 | 5. 확인할 TODO | 6. 다음 단계: code_review
EOF
                ;;
            code_review)
                cat << 'EOF'
현재 단계: code_review (Stage 9)
목표: 구현 결과를 설계 기준으로 검토
검증 기준: 설계와 구현 일치, 구조적 과함, 예외 처리, 유지보수 위험
출력 형식:
1. 일치하는 부분 | 2. 문제점 | 3. 위험 요소 | 4. 수정 우선순위
5. 수정 지시문 | 6. 다음 단계: revise 또는 final_review
EOF
                ;;
            *)
                log_info "프롬프트 템플릿은 prompts/ 폴더에 저장하세요: $prompt_file"
                ;;
        esac
    else
        # 프롬프트 파일 내용 출력
        cat "$prompt_file"
    fi

    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# 로그 기록
log_execution() {
    local stage_name="$1"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local log_file="$LOGS_DIR/ai_steps.log"

    echo "[$timestamp] $stage_name - 실행" >> "$log_file"
    log_success "로그 기록: $log_file"
}

# 메인 로직
main() {
    if [ -z "$1" ]; then
        interactive_select
    else
        STAGE_NAME="$1"
    fi

    # 단계명 검증
    if [[ ! -v CLAUDE_STAGES[$STAGE_NAME] ]] && [[ ! -v CODEX_STAGES[$STAGE_NAME] ]]; then
        log_error "알 수 없는 단계: $STAGE_NAME"
        echo ""
        echo "사용 가능한 단계:"
        for stage in "${!STAGE_INFO[@]}"; do
            echo "  - $stage"
        done
        exit 1
    fi

    # 프롬프트 출력
    show_prompt "$STAGE_NAME"

    # 로그 기록
    log_execution "$STAGE_NAME"

    # 안내
    echo -e "${BLUE}ℹ 다음 명령어를 실행하세요:${NC}"
    echo -e "${YELLOW}  aigit \"Stage X 완료: (설명)\"${NC}"
    echo -e "${BLUE}  (또는) aihist \"(변경 사항)\"${NC}"
}

main "$@"
