#!/bin/bash
# git_upload.sh — 안전한 GitHub 업로드 자동화
#
# 사용법:
#   aigit_upload           # 상태 확인 + 승인 후 push
#   aigit_upload --auto    # 승인 없이 자동 push (CI용)
#
# 동작:
#   1. 변경 파일 목록 확인
#   2. 보안 파일(.env, 토큰 등) 포함 여부 검사
#   3. 문제 없으면 승인 요청 → push

set -e

PROJECT_ROOT="/Users/geenya/projects/AI_Projects/stockpilot"
cd "$PROJECT_ROOT"

AUTO_MODE=0
if [ "$1" = "--auto" ]; then
    AUTO_MODE=1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📦 GitHub 업로드 검토"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. 변경사항 확인 ──────────────────────────────────
# git diff는 .git 루트 기준 경로를 반환하므로 PROJECT_ROOT 기준으로 변환
MODIFIED=$(git diff --name-only HEAD 2>/dev/null | sed "s|^stockpilot/||")
STAGED=$(git diff --name-only --cached 2>/dev/null | sed "s|^stockpilot/||")
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | sed "s|^stockpilot/||")

if [ -z "$MODIFIED" ] && [ -z "$STAGED" ] && [ -z "$UNTRACKED" ]; then
    # 로컬과 리모트 비교
    git fetch origin main --quiet 2>/dev/null || true
    AHEAD=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo "0")
    if [ "$AHEAD" = "0" ]; then
        echo "✅ 업로드할 내용이 없습니다. 이미 최신 상태입니다."
        echo ""
        exit 0
    else
        echo "📤 커밋은 있지만 push 안 된 상태: ${AHEAD}개"
    fi
fi

# ── 2. 변경 파일 목록 출력 ────────────────────────────
if [ -n "$MODIFIED" ]; then
    echo "📝 수정된 파일:"
    echo "$MODIFIED" | sed 's/^/   /'
    echo ""
fi

if [ -n "$STAGED" ]; then
    echo "✅ 스테이징된 파일:"
    echo "$STAGED" | sed 's/^/   /'
    echo ""
fi

if [ -n "$UNTRACKED" ]; then
    echo "❓ 추적되지 않는 새 파일:"
    echo "$UNTRACKED" | sed 's/^/   /'
    echo ""
fi

# ── 3. 보안 검사 ──────────────────────────────────────
DANGER=0
DANGER_FILES=""

ALL_FILES="$MODIFIED $STAGED $UNTRACKED"

for f in $ALL_FILES; do
    # .env 파일
    if echo "$f" | grep -qE "^\.env$|^\.env\.[^e]"; then
        DANGER=1
        DANGER_FILES="$DANGER_FILES\n   🚨 $f (.env 파일)"
    fi
    # 토큰/키 파일
    if echo "$f" | grep -qiE "token|secret|password|credential|keychain"; then
        DANGER=1
        DANGER_FILES="$DANGER_FILES\n   🚨 $f (민감정보 파일명)"
    fi
    # 캐시/토큰 json
    if echo "$f" | grep -qE "data/cache/|\.token"; then
        DANGER=1
        DANGER_FILES="$DANGER_FILES\n   🚨 $f (캐시/토큰 파일)"
    fi
done

if [ $DANGER -eq 1 ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  🚨 업로드 불가 — 보안 문제 발견"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "다음 파일이 포함되어 있습니다:"
    echo -e "$DANGER_FILES"
    echo ""
    echo "해결 방법:"
    echo "  1. .gitignore에 해당 파일 추가"
    echo "  2. git rm --cached <파일> 로 추적 제거"
    echo ""
    exit 1
fi

# ── 4. push 안 된 커밋 확인 ───────────────────────────
git fetch origin main --quiet 2>/dev/null || true
AHEAD=$(git rev-list origin/main..HEAD --count 2>/dev/null || echo "0")

if [ "$AHEAD" -gt 0 ]; then
    echo "📤 push 안 된 커밋: ${AHEAD}개"
    git log origin/main..HEAD --oneline | sed 's/^/   /'
    echo ""
fi

# ── 5. 스테이징/커밋이 필요한 파일 처리 ──────────────
NEED_COMMIT=0
if [ -n "$MODIFIED" ] || [ -n "$STAGED" ] || [ -n "$UNTRACKED" ]; then
    NEED_COMMIT=1
fi

# ── 6. 승인 요청 ──────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $AUTO_MODE -eq 1 ]; then
    REPLY="y"
    echo "  자동 모드 — 바로 업로드합니다."
else
    echo "  보안 검사 통과 ✅"
    echo ""
    # 커밋 메시지 자동 생성
    if [ $NEED_COMMIT -eq 1 ]; then
        FILE_COUNT=$(echo "$MODIFIED $STAGED" | wc -w | tr -d ' ')
        COMMIT_MSG="chore: 변경사항 업데이트 ${FILE_COUNT}개 파일 ($(date '+%Y-%m-%d %H:%M'))"
        echo "  📝 커밋 메시지: $COMMIT_MSG"
        echo ""
    fi
    read -p "  GitHub에 업로드하시겠습니까? (y/N): " REPLY
fi

echo ""

if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    # 수정 파일 + 새 파일 모두 스테이징
    if [ -n "$MODIFIED" ]; then
        git add $MODIFIED
    fi
    if [ -n "$UNTRACKED" ]; then
        git add $UNTRACKED
    fi
    if [ -n "$STAGED" ] || [ -n "$MODIFIED" ] || [ -n "$UNTRACKED" ]; then
        FILE_COUNT=$(echo "$MODIFIED $STAGED $UNTRACKED" | wc -w | tr -d ' ')
        COMMIT_MSG="chore: 변경사항 업데이트 ${FILE_COUNT}개 파일 ($(date '+%Y-%m-%d %H:%M'))"
        git commit -m "${COMMIT_MSG}" \
            -m "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>" 2>/dev/null || true
    fi

    echo "  📤 push 중..."
    git push origin main

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ✅ GitHub 업로드 완료!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
else
    echo "  취소했습니다."
    echo ""
fi
