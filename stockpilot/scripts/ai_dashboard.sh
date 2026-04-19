#!/usr/bin/env bash

# ai_dashboard.sh — AI 프로젝트 워크플로우 대시보드 (박스형 TUI)
# 사용법: bash scripts/ai_dashboard.sh
# alias:  aidash

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOCS_DIR="$ROOT_DIR/docs"
CONFIG_DIR="$ROOT_DIR/config"

CURRENT_STEP_FILE="$CONFIG_DIR/current_step.txt"
WORKFLOW_FILE="$CONFIG_DIR/workflow_steps.txt"

# ---------- 색상 ----------
RESET='\033[0m'
BOLD='\033[1m'
GREEN='\033[32m'
YELLOW='\033[33m'
BLUE='\033[34m'
GRAY='\033[90m'
CYAN='\033[36m'

# ---------- 박스 그리기 ----------
draw_top() {
  printf "┌──────────────────────────────────────────┐\n"
}

draw_line() {
  printf "├──────────────────────────────────────────┤\n"
}

draw_bottom() {
  printf "└──────────────────────────────────────────┘\n"
}

# 텍스트 포함 행 (ANSI 코드 포함 시 길이 보정)
draw_text() {
  local raw="$1"       # 출력할 원본 문자열 (ANSI 포함 가능)
  local visible="$2"   # 실제 보이는 문자열 (길이 계산용)
  visible="${visible:-$raw}"
  # ANSI escape 제거 후 가시 길이 계산
  local clean
  clean="$(printf '%s' "$visible" | sed 's/\x1b\[[0-9;]*m//g')"
  local pad=$(( 40 - ${#clean} ))
  printf "│ %b%*s │\n" "$raw" "$pad" ""
}

# ---------- 단계 → 산출물 파일 매핑 ----------
get_output_path() {
  case "$1" in
    brainstorm)       echo "$DOCS_DIR/01_brainstorm/brainstorm.md" ;;
    planning_draft)   echo "$DOCS_DIR/02_planning/plan_draft.md" ;;
    planning_review)  echo "$DOCS_DIR/02_planning/plan_review.md" ;;
    planning_final)   echo "$DOCS_DIR/02_planning/plan_final.md" ;;
    technical_design) echo "$DOCS_DIR/03_design/technical_design.md" ;;
    ui_requirements)  echo "$DOCS_DIR/03_design/ui_requirements.md" ;;
    ui_flow)          echo "$DOCS_DIR/03_design/ui_flow.md" ;;
    implementation)   echo "$DOCS_DIR/04_implementation/implementation_request.md" ;;
    code_review)      echo "$DOCS_DIR/04_implementation/code_review.md" ;;
    revise)           echo "$DOCS_DIR/04_implementation/revise_request.md" ;;
    final_review)     echo "$DOCS_DIR/04_implementation/final_review.md" ;;
    qa)               echo "$DOCS_DIR/05_qa/qa_scenarios.md" ;;
    *)                echo "" ;;
  esac
}

# ---------- 워크플로우 파일 확인 ----------
if [ ! -f "$WORKFLOW_FILE" ]; then
  echo "❌ 워크플로우 파일 없음: $WORKFLOW_FILE"
  echo "   먼저 aiinit 을 실행해 프로젝트를 초기화하세요."
  exit 1
fi

mapfile -t STEPS < "$WORKFLOW_FILE"

# ---------- 현재 단계 로드 ----------
CURRENT_STEP=""
if [ -f "$CURRENT_STEP_FILE" ]; then
  CURRENT_STEP="$(tr -d '[:space:]' < "$CURRENT_STEP_FILE")"
fi

# current_step.txt 없으면 산출물 파일 기준으로 자동 추론
if [ -z "$CURRENT_STEP" ]; then
  for step in "${STEPS[@]}"; do
    path="$(get_output_path "$step")"
    if [ -n "$path" ] && [ -f "$path" ] && [ -s "$path" ]; then
      CURRENT_STEP="$step"
    fi
  done
fi

# ---------- 다음 단계 추론 ----------
NEXT_STEP=""
FOUND=0
if [ -n "$CURRENT_STEP" ]; then
  for step in "${STEPS[@]}"; do
    if [ "$FOUND" -eq 1 ]; then
      NEXT_STEP="$step"
      break
    fi
    [ "$step" = "$CURRENT_STEP" ] && FOUND=1
  done
else
  NEXT_STEP="${STEPS[0]}"
fi

# ---------- 렌더링 ----------
clear 2>/dev/null || true

draw_top
draw_text "$(printf "${BOLD}${CYAN}  AI PROJECT DASHBOARD${RESET}")" "  AI PROJECT DASHBOARD"
draw_line
draw_text "$(printf "Current Step : ${BLUE}${BOLD}${CURRENT_STEP:-없음}${RESET}")" "Current Step : ${CURRENT_STEP:-없음}"
draw_text "$(printf "Next Step    : ${YELLOW}${NEXT_STEP:-없음}${RESET}")" "Next Step    : ${NEXT_STEP:-없음}"
draw_line

for step in "${STEPS[@]}"; do
  path="$(get_output_path "$step")"

  if [ "$step" = "$CURRENT_STEP" ]; then
    draw_text "$(printf "${BLUE}${BOLD}[→] %-24s (CURRENT)${RESET}" "$step")" "[→] $step (CURRENT)"

  elif [ "$step" = "$NEXT_STEP" ]; then
    draw_text "$(printf "${YELLOW}[*] %-24s (NEXT)${RESET}" "$step")" "[*] $step (NEXT)"

  elif [ -n "$path" ] && [ -f "$path" ] && [ -s "$path" ]; then
    draw_text "$(printf "${GREEN}[✓] ${step}${RESET}")" "[✓] $step"

  else
    draw_text "$(printf "${GRAY}[ ] ${step}${RESET}")" "[ ] $step"
  fi

done

draw_bottom

echo
printf "  실행  : ${BOLD}aip <단계명>${RESET}   (예: aib, aipd, aitd)\n"
printf "  단계변경: ${BOLD}echo <단계명> > config/current_step.txt${RESET}\n"
echo
