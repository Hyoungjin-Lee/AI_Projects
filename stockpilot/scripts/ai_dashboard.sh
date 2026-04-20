#!/usr/bin/env zsh

# ai_dashboard.sh — AI 프로젝트 워크플로우 대시보드 (박스형 TUI)
# 사용법: zsh scripts/ai_dashboard.sh  또는  aidash
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

# 텍스트 포함 행 — visible 인자(plain text)로 길이 계산
draw_text() {
  local raw="$1"      # ANSI 포함 출력용
  local visible="$2"  # 순수 텍스트(길이 계산용), 없으면 raw 그대로
  visible="${visible:-$raw}"
  local pad=$(( 40 - ${#visible} ))
  (( pad < 0 )) && pad=0
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

# zsh 호환 파일 읽기 (mapfile 대신)
STEPS=()
while IFS= read -r line || [ -n "$line" ]; do
  [[ -z "$line" ]] && continue
  STEPS+=("$line")
done < "$WORKFLOW_FILE"

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

# ---------- 현재/다음 단계 인덱스 계산 (zsh 1-based) ----------
CURRENT_IDX=0
NEXT_STEP=""
for (( i=1; i<=${#STEPS[@]}; i++ )); do
  if [ "${STEPS[$i]}" = "$CURRENT_STEP" ]; then
    CURRENT_IDX=$i
    if (( i < ${#STEPS[@]} )); then
      NEXT_STEP="${STEPS[$((i+1))]}"
    fi
    break
  fi
done
# current_step.txt 없으면 첫 단계가 NEXT
if [ -z "$CURRENT_STEP" ]; then
  NEXT_STEP="${STEPS[1]}"
fi

# ---------- 헤더 (한글 없이 ASCII로 고정폭 유지) ----------
clear 2>/dev/null || true

draw_top
draw_text "$(printf "${BOLD}${CYAN}  AI PROJECT DASHBOARD${RESET}")" "  AI PROJECT DASHBOARD"
draw_line

# Current / Next — ASCII로만 구성해 폭 계산 안정화
cur_val="${CURRENT_STEP:-none}"
nxt_val="${NEXT_STEP:-none}"
draw_text "$(printf "Current : ${BLUE}${BOLD}%-20s${RESET}" "$cur_val")" "$(printf "Current : %-20s" "$cur_val")"
draw_text "$(printf "Next    : ${YELLOW}%-20s${RESET}"     "$nxt_val")" "$(printf "Next    : %-20s"     "$nxt_val")"
draw_line

# ---------- 단계 목록 ----------
for (( i=1; i<=${#STEPS[@]}; i++ )); do
  step="${STEPS[$i]}"
  path="$(get_output_path "$step")"

  if [ "$step" = "$CURRENT_STEP" ]; then
    # 현재 단계
    draw_text "$(printf "${BLUE}${BOLD}[>] %-22s NOW${RESET}" "$step")" "$(printf "[>] %-22s NOW" "$step")"

  elif [ "$step" = "$NEXT_STEP" ]; then
    # 다음 단계
    draw_text "$(printf "${YELLOW}[*] %-22s ---${RESET}" "$step")" "$(printf "[*] %-22s ---" "$step")"

  elif [ "$CURRENT_IDX" -gt 0 ] && [ "$i" -lt "$CURRENT_IDX" ]; then
    # 현재보다 앞 → 완료
    draw_text "$(printf "${GREEN}[v] ${step}${RESET}")" "[v] $step"

  elif [ -n "$path" ] && [ -f "$path" ] && [ -s "$path" ]; then
    # 산출물 파일 있으면 완료
    draw_text "$(printf "${GREEN}[v] ${step}${RESET}")" "[v] $step"

  else
    # 미완료
    draw_text "$(printf "${GRAY}[ ] ${step}${RESET}")" "[ ] $step"
  fi

done

draw_bottom

echo
printf "  단계변경: ${BOLD}echo <단계명> > config/current_step.txt${RESET}\n"
printf "  단계명  : issue_fix / phase1_intraday / phase2_trading / phase3_position / phase4_webui\n"
echo
