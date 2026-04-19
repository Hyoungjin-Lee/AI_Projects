#!/bin/bash

# dev_history 수동 기록 스크립트
# 목적: dev_history.md에 수동으로 항목 추가
# 사용법: ./append_history.sh "기록 메시지"

set -e

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
    exit 1
}

# 설정
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DEV_HISTORY="$PROJECT_DIR/docs/notes/dev_history.md"
MESSAGE="${1:-(메시지 없음)}"

# 메인 로직
main() {
    log_info "dev_history.md에 기록 추가 중..."

    # dev_history.md 파일 확인
    if [ ! -f "$DEV_HISTORY" ]; then
        log_warn "dev_history.md가 없습니다. 생성 중..."
        mkdir -p "$(dirname "$DEV_HISTORY")"
        cat > "$DEV_HISTORY" << 'EOF'
# 개발 기록 (Development History)

모든 단계, 결정, 사고의 누적 로그입니다.

## 타임라인

EOF
        log_success "dev_history.md 생성 완료"
    fi

    # 새 항목 생성
    local timestamp=$(date '+%Y-%m-%d %H:%M')
    local new_entry="### [$timestamp] 작업 기록
- **메시지**: $MESSAGE
- **상태**: 기록됨

"

    # dev_history.md 맨 뒤에 추가
    echo "" >> "$DEV_HISTORY"
    echo "$new_entry" >> "$DEV_HISTORY"

    log_success "기록이 추가되었습니다"

    # 확인
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "파일: ${YELLOW}$DEV_HISTORY${NC}"
    echo -e "시간: ${YELLOW}$timestamp${NC}"
    echo -e "내용: ${YELLOW}$MESSAGE${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    log_info "다음 명령어로 확인: tail -20 $DEV_HISTORY"
}

# 인자 확인
if [ -z "$1" ]; then
    log_error "기록 메시지를 입력하세요: aihist \"메시지\""
fi

main "$@"
