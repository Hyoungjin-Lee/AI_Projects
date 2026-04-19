#!/bin/bash

# zsh alias 설정 파일
# 목적: AI 워크플로우 CLI 자동화 alias 정의
# 사용법: .zshrc에서 `source /path/to/zsh_aliases.sh` 추가 후 셸 재시작
#
# 예시:
#   $ source ~/.zshrc
#   $ aib      # Stage 1: 아이디어 구상
#   $ aipd     # Stage 2: 계획 초안
#   $ aigit "메시지"  # Git 커밋 + 기록

# 프로젝트 루트 디렉토리 설정
# .zshrc에서 사용할 경우, 아래 경로를 자신의 프로젝트 경로로 수정하세요
STOCKPILOT_ROOT="/Users/geenya/projects/AI_Projects/stockpilot"

# scripts 디렉토리 확인
if [ ! -d "$STOCKPILOT_ROOT/scripts" ]; then
    echo "경고: scripts 디렉토리를 찾을 수 없습니다: $STOCKPILOT_ROOT/scripts"
    return 1
fi

# 스크립트에 실행 권한 부여 (처음 한 번만 필요)
chmod +x "$STOCKPILOT_ROOT/scripts"/*.sh 2>/dev/null || true

# ============================================================
# AI Workflow CLI Aliases
# ============================================================

# 프로젝트 초기화
alias aiinit="bash $STOCKPILOT_ROOT/scripts/init_project.sh"

# 단계 실행 (대화형 또는 지정)
alias aip="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh"

# Git 체크포인트
alias aigit="bash $STOCKPILOT_ROOT/scripts/git_checkpoint.sh"

# GitHub 안전 업로드 (보안검사 + 승인 후 push)
alias aigit_upload="bash $STOCKPILOT_ROOT/scripts/git_upload.sh"

# 수동 기록
alias aihist="bash $STOCKPILOT_ROOT/scripts/append_history.sh"

# ============================================================
# Stage별 Alias - Claude 단계
# ============================================================

# Stage 1: 아이디어 구상
alias aib="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh brainstorm"

# Stage 2: 계획 초안
alias aipd="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh planning_draft"

# Stage 3: 계획 검토
alias aipr="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh planning_review"

# Stage 4: 계획 통합
alias aipf="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh planning_final"

# Stage 5: 기술 설계
alias aitd="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh technical_design"

# Stage 6: UI 요구사항 (선택)
alias aiui="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh ui_requirements"

# Stage 7: UI 플로우 (선택)
alias aiflow="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh ui_flow"

# Stage 9: 코드 리뷰
alias aireview="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh code_review"

# Stage 11: 최종 검증
alias aifinal="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh final_review"

# Stage 12: QA & 릴리스
alias aiqa="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh qa"

# ============================================================
# Stage별 Alias - Codex 단계
# ============================================================

# Stage 8: 구현
alias aiimpl="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh implementation"

# Stage 10: 수정
alias airevise="zsh $STOCKPILOT_ROOT/scripts/ai_step.sh revise"

# ============================================================
# 편의 함수
# ============================================================

# 현재 단계 상태 보기
ai_status() {
    echo "AI Workflow 상태"
    echo "================"
    echo ""
    echo "현재 프로젝트: $STOCKPILOT_ROOT"
    echo ""

    if [ -f "$STOCKPILOT_ROOT/HANDOFF.md" ]; then
        echo "--- HANDOFF.md (현재 상태) ---"
        head -20 "$STOCKPILOT_ROOT/HANDOFF.md"
    fi

    echo ""
    echo "--- 최근 기록 ---"
    if [ -f "$STOCKPILOT_ROOT/docs/notes/dev_history.md" ]; then
        tail -10 "$STOCKPILOT_ROOT/docs/notes/dev_history.md"
    fi
}

# dev_history 마지막 N줄 보기 (기본 10줄)
ai_log() {
    local lines="${1:-10}"
    if [ -f "$STOCKPILOT_ROOT/docs/notes/dev_history.md" ]; then
        tail -n "$lines" "$STOCKPILOT_ROOT/docs/notes/dev_history.md"
    else
        echo "dev_history.md 파일이 없습니다"
    fi
}

# 프로젝트 디렉토리로 이동
ai_cd() {
    cd "$STOCKPILOT_ROOT"
}

# 대시보드
alias aidash="zsh $STOCKPILOT_ROOT/scripts/ai_dashboard.sh"

# ============================================================
# 사용 안내
# ============================================================

# alias 목록 보기 함수
ai_help() {
    cat << 'EOF'
┌────────────────────────────────────────────────────────────┐
│  AI Workflow CLI 사용 안내                                  │
└────────────────────────────────────────────────────────────┘

[프로젝트 초기화]
  aiinit                   프로젝트 초기화 (폴더/파일 생성)

[단계 실행 - Claude]
  aib                      Stage 1: 아이디어 구상
  aipd                     Stage 2: 계획 초안
  aipr                     Stage 3: 계획 검토
  aipf                     Stage 4: 계획 통합
  aitd                     Stage 5: 기술 설계
  aiui                     Stage 6: UI 요구사항 (선택)
  aiflow                   Stage 7: UI 플로우 (선택)
  aireview                 Stage 9: 코드 리뷰
  aifinal                  Stage 11: 최종 검증
  aiqa                     Stage 12: QA & 릴리스

[단계 실행 - Codex]
  aiimpl                   Stage 8: 구현
  airevise                 Stage 10: 수정

[기록 & 커밋]
  aigit "메시지"           Git 커밋 + dev_history 기록
  aihist "메시지"          dev_history 수동 기록

[편의 함수]
  aidash                   워크플로우 대시보드 (박스형 TUI)
  ai_status                현재 상태 보기
  ai_log [N]               마지막 N줄 기록 보기 (기본 10)
  ai_cd                    프로젝트 디렉토리로 이동

[예시 워크플로우]
  $ aib                    Stage 1 시작
  $ aigit "아이디어 구상 완료"
  $ aipd                   Stage 2 시작
  $ aigit "계획 초안 작성"
  $ ai_log 5               최근 5줄 기록 보기

자세한 내용은 WORKFLOW.md Section 12 & 13 참고
EOF
}

# 초기 안내 메시지
echo "✓ AI Workflow CLI aliases 로드됨"
echo "  ai_help 명령어로 사용 안내 보기"

