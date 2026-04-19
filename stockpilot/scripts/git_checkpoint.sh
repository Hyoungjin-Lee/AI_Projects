#!/bin/bash

# Git 체크포인트 & 이력 기록 스크립트
# 목적: Git 커밋 + dev_history.md 자동 기록
# 사용법: ./git_checkpoint.sh "커밋 메시지"

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
COMMIT_MSG="${1:-(커밋 메시지 없음)}"

# 메인 로직
main() {
    cd "$PROJECT_DIR" || log_error "프로젝트 디렉토리 이동 실패"

    # Git 저장소 확인
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        log_warn "Git 저장소가 아닙니다. Git 초기화 중..."
        git init
    fi

    log_info "변경사항 스테이징 중..."
    git add -A

    # 변경사항 확인
    if ! git diff --cached --quiet; then
        log_info "Git 커밋: \"$COMMIT_MSG\""
        git commit -m "$COMMIT_MSG"
        log_success "Git 커밋 완료"
    else
        log_warn "스테이징된 변경사항이 없습니다"
        exit 0
    fi

    # dev_history.md 자동 기록
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

    # dev_history.md에 항목 추가 (마지막 줄 위에 삽입)
    local timestamp=$(date '+%Y-%m-%d %H:%M')
    local git_commit=$(git rev-parse --short HEAD)
    local new_entry="### [$timestamp] $COMMIT_MSG
- **Git Commit**: $git_commit
- **변경 파일**: $(git show --name-only --pretty='format:' HEAD | grep -v '^$' | wc -l)개
- **상태**: 진행 중

"

    # 기존 내용 읽기
    local existing=$(cat "$DEV_HISTORY")

    # 새 항목을 "타임라인" 섹션 아래에 삽입
    if grep -q "^## 타임라인" "$DEV_HISTORY"; then
        # "## 타임라인" 다음 줄에 삽입
        local line_num=$(grep -n "^## 타임라인" "$DEV_HISTORY" | cut -d: -f1)
        head -n "$line_num" "$DEV_HISTORY" > "${DEV_HISTORY}.tmp"
        echo "" >> "${DEV_HISTORY}.tmp"
        echo "$new_entry" >> "${DEV_HISTORY}.tmp"
        tail -n +$((line_num+1)) "$DEV_HISTORY" >> "${DEV_HISTORY}.tmp"
        mv "${DEV_HISTORY}.tmp" "$DEV_HISTORY"
    else
        # "타임라인" 섹션이 없으면 끝에 추가
        echo "" >> "$DEV_HISTORY"
        echo "## 타임라인" >> "$DEV_HISTORY"
        echo "" >> "$DEV_HISTORY"
        echo "$new_entry" >> "$DEV_HISTORY"
    fi

    log_success "dev_history.md 업데이트 완료"

    # 요약
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✓ Git 체크포인트 완료${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "커밋: ${YELLOW}$git_commit${NC}"
    echo -e "메시지: ${YELLOW}$COMMIT_MSG${NC}"
    echo -e "기록: ${YELLOW}docs/notes/dev_history.md${NC}"
    echo ""
}

# 인자 확인
if [ -z "$1" ]; then
    log_error "커밋 메시지를 입력하세요: aigit \"메시지\""
fi

main "$@"
