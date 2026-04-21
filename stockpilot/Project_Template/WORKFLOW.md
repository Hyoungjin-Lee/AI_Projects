# 🔄 AI-Driven Development Workflow

> **Version:** 1.0
> **Scope:** Universal — applicable to any project using Claude as orchestrator
> **Korean version:** see bottom of this file (한국어 버전: 파일 하단 참조)

---

## 1. Summary

This workflow establishes a **document-centric, role-separated development process**:
- **Claude** handles thinking, architecture, review, and QA
- **Codex** handles implementation, debugging, and iteration
- **Documents** (`docs/` folder) are the single source of truth
- **Handoff rules** enable smooth transitions between sessions

---

## 2. Full Workflow: 13 Stages

| # | Stage | Owner | Model | Effort | Input | Output | Est. Time |
|---|-------|-------|-------|--------|-------|--------|-----------|
| 1 | **Brainstorm** ⚠️ | Claude + User | Opus | Medium | User request | `docs/01_brainstorm/brainstorm.md` | 15–30 min |
| 2 | **Plan Draft** | Claude | Sonnet | Medium | Brainstorm result | `docs/02_planning/plan_draft.md` | 15–30 min |
| 3 | **Plan Review** | Claude | Sonnet | High | Plan draft | `docs/02_planning/plan_review.md` | 10–20 min |
| 4 | **Plan Final** ⚠️ | Claude | Sonnet | Medium | Draft + review | `docs/02_planning/plan_final.md` | 10–15 min |
| 4.5 | **User Approval** 🔴 | User | — | — | plan_final.md | Approval confirmed | — |
| 5 | **Technical Design** | Claude | Opus | High | Approved plan | `docs/03_design/technical_design.md` | 30–60 min |
| 6 | **UI/UX Requirements** *(optional)* | Claude | Sonnet | Medium | Technical design | `docs/03_design/ui_requirements.md` | 15–30 min |
| 7 | **UI Flow** *(optional)* | Claude | Sonnet | Medium | UI requirements | `docs/03_design/ui_flow.md` | 20–40 min |
| 8 | **Implementation** | Codex | — | High | Technical design + UI flow | Code + tests + commit | 1–8 hrs |
| 9 | **Code Review (1st)** | Claude | Sonnet | High | Codex output | `docs/04_implementation/implementation_progress.md` | 15–30 min |
| 10 | **Revision** | Codex | — | Medium | Review feedback | Revised code + tests | 30 min–2 hrs |
| 11 | **Final Validation** | Claude | Opus | XHigh or High* | Revised code + test results | `docs/notes/final_validation.md` | 30 min–1 hr |
| 12 | **QA & Release** | Claude | Sonnet | Medium | Validated code | `docs/05_qa_release/qa_scenarios.md` + `release_checklist.md` | 15–30 min |
| 13 | **Deploy & Archive** | Codex | — | Medium | QA-approved code | Merged code + updated `HANDOFF.md` | varies |

**Effort tiers:**
- **XHigh** → security, architecture-level, high-risk production changes
- **High** → most feature validation, code review, design decisions
- `*` Stage 11: default is **High**; escalate to **XHigh** only if security/architecture criteria apply

---

## 3. Operating Context: Feature Development vs Execution Mode

This workflow is for **feature development** (new features, refactoring, major changes).

### Use the workflow (Feature Development)
- Adding new functionality
- Refactoring core modules
- Integrating new APIs or services
- Redesigning architecture
- Fixing bugs that affect architecture
- **Trigger:** "implement X" or "refactor Y module"

### Skip the workflow (Execution / Hotfix Mode)
- Emergency production fixes (go directly Stage 8 → 11 → 13)
- Config or data file updates
- Routine maintenance (log cleanup, cache refresh)
- Documentation-only updates
- **Trigger:** "fix bug in main.py" or "update config"

**Mode switch rule:** Check `HANDOFF.md` status at the start of every session:
- Status shows "feature development in progress" → use WORKFLOW.md
- Status shows "all systems nominal" → use only HANDOFF.md + CLAUDE.md

---

## 4. Model & Effort Strategy

### Model Selection Guide

| Task Type | Primary | Fallback | Reason |
|-----------|---------|----------|--------|
| Brainstorm, architecture | **Opus** | Sonnet | Strong reasoning on ambiguous/creative problems |
| Planning, design review | **Sonnet** | Opus | Fast iteration, sufficient depth |
| Code review, validation | **Sonnet** or **Opus** | — | Routine → Sonnet; critical path → Opus |
| Implementation | **Codex** | — | Specialized coding environment |
| Documentation, summary | **Haiku** | Sonnet | Fast and cost-efficient |

### Effort Decision Tree

```
Is it security-related or production-critical?
├─ YES → XHigh (final validation only)
└─ NO
   ├─ Does it affect core architecture or multiple systems?
   │  ├─ YES → High
   │  └─ NO
   │     ├─ Is it a new feature or significant refactor?
   │     │  ├─ YES → Medium (planning) → High (code review)
   │     │  └─ NO → Medium or Low
   │     └─ Is it documentation or a summary?
   │        └─ YES → Low or Medium
```

---

## 5. Agent Composition

This workflow runs with **4 dedicated agents**. Codex is treated as an external implementation tool, not an agent.

### Agent Role Table

| Agent | Stages | Primary Model | Effort |
|-------|--------|---------------|--------|
| 🧠 Planner | 1, 2, 3, 4 | Sonnet (Opus for Stage 1 only) | Medium–High |
| 🏗️ Designer | 5, 6, 7 | Opus (Stage 5) / Sonnet (Stage 6–7) | Medium–High |
| 🔍 Reviewer | 9, 11 | Sonnet (Stage 9) / Opus (Stage 11) | High–XHigh |
| 🧪 QA Engineer | 12, 13 | Sonnet | Medium |
| ⚙️ Codex (external) | 8, 10 | — | — |

### Design Principles

1. **Designer ≠ Reviewer** — The agent that designs must NOT validate its own work (confirmation bias)
2. **Stage 1 uses Opus** — Getting direction wrong at brainstorm breaks everything downstream
3. **Codex is a tool** — Stages 8 and 10 are Codex's job; keep it out of agent composition

### Full Flow

```
🧠 Planner         🏗️ Designer        ⚙️ Codex          🔍 Reviewer        🧪 QA Engineer
Stage 1 (Opus)  →
Stage 2 (Sonnet) →
Stage 3 (Sonnet) →
Stage 4 (Sonnet) → Stage 5 (Opus)  →
                   Stage 6 (Sonnet) →
                   Stage 7 (Sonnet) → Stage 8 (impl.)  →
                                      Stage 10 (revise) → Stage 9 (Sonnet) →
                                                          Stage 11 (Opus)  →
                                                                             Stage 12 (Sonnet)
                                                                             Stage 13
```

### Hotfix Agent Composition

Skip Planner and Designer for emergency hotfixes:
```
⚙️ Codex → 🔍 Reviewer (Stage 11, Opus) → 🧪 QA Engineer (Stage 13)
```

---

## 6. Core Operating Principles

1. **No role mixing** — Claude does not implement; Codex does not validate
2. **Plan before design** — Do not enter Stage 5 without confirmed Stage 4
3. **Design before code** — No code without confirmed Stage 5 (hotfix exception, always logged)
4. **Documents first** — All outputs go to `docs/` before moving to the next stage
5. **Single source of truth** — `docs/` > chat history > memory

### Validation Discipline

**Code Review (Stage 9) — minimum before approving changes:**
- [ ] All tests pass
- [ ] No security anti-patterns (hardcoded credentials, unvalidated input, etc.)
- [ ] Follows project style and existing patterns
- [ ] Non-obvious logic is commented
- [ ] No unnecessary code duplication

**Final Validation (Stage 11) — minimum before merging:**
- [ ] All review feedback addressed by Codex
- [ ] Changes integrate cleanly with existing modules
- [ ] No performance regressions (profile if needed)
- [ ] Documentation updated (docstrings, README)

---

## 7. Session Handoff & Persistence

### Read Order (every new session)
1. **CLAUDE.md** — project rules, security, key files
2. **HANDOFF.md** — current status, recent changes, next tasks
3. **WORKFLOW.md** — this file (skim sections 1–3 for feature work)
4. **Relevant docs/** — only the document for the current stage

### Write Order (end of session)
1. Update the current stage document (e.g., `plan_final.md`, `technical_design.md`)
2. Append to `docs/notes/dev_history.md`: stage number, date, what was done, blockers, output links
3. Update `HANDOFF.md`: current status, next session tasks, blockers, document links
4. Write the "next session prompt" at the bottom of `HANDOFF.md`

### Next-Session Prompt Rules

When the user says "set me up to continue next session", you must:
1. Update `HANDOFF.md`
2. Add or refresh the `## 📋 Next Session Prompt` section at the bottom

**Prompt writing principles:**
- Copy-pasteable with no explanation needed
- Includes a summary of today's work (for context restoration)
- Clearly states the next task (with file names and stage numbers)
- Includes relevant file paths
- Includes key design decisions (so the next session doesn't re-debate them)

---

## 8. Independent Validation Protocol (Confirmation Bias Prevention)

**Required for Stage 11. Recommended for any complex logic change.**

Reviewing code in the same session that produced it introduces confirmation bias. Use a fresh Claude session with no prior context.

### Steps
1. Start a new Claude session (no context from the current session)
2. Paste only the changed code and the minimal background
3. Ask for: bug/logic errors, security vulnerabilities, exception handling, improvements
4. Apply findings back to the current session

### When to Apply

| Change Size | Validation Method |
|------------|-------------------|
| 1–10 lines | Current-session self-review is sufficient |
| 10–50 lines | Independent validation recommended |
| 50+ lines or new file | Independent validation required |
| New agent or orchestrator | Independent validation required |

---

## 9. File & Folder Structure

```
project-root/
├─ CLAUDE.md                          ← Project rules + security (read first)
├─ HANDOFF.md                         ← Current status + next tasks (read second)
├─ WORKFLOW.md                        ← This file (reference as needed)
├─ README.md                          ← User-facing project docs
│
├─ docs/
│  ├─ 01_brainstorm/
│  │  └─ brainstorm.md               ← Stage 1: raw ideas, constraints, assumptions
│  ├─ 02_planning/
│  │  ├─ plan_draft.md               ← Stage 2: problem statement, scope, success criteria
│  │  ├─ plan_review.md              ← Stage 3: review feedback
│  │  └─ plan_final.md               ← Stage 4: final confirmed plan
│  ├─ 03_design/
│  │  ├─ technical_design.md         ← Stage 5: architecture, APIs, data flow
│  │  ├─ ui_requirements.md          ← Stage 6 (optional): user stories, acceptance criteria
│  │  └─ ui_flow.md                  ← Stage 7 (optional): wireframes, state machine
│  ├─ 04_implementation/
│  │  └─ implementation_progress.md  ← Stages 8–10: progress log and code review notes
│  ├─ 05_qa_release/
│  │  ├─ qa_scenarios.md             ← Stage 12: test cases, edge cases
│  │  └─ release_checklist.md        ← Stage 12: pre-release checklist
│  └─ notes/
│     ├─ dev_history.md              ← Cumulative log of all stages and decisions
│     ├─ decisions.md                ← Decision rationale (architecture choices)
│     └─ final_validation.md         ← Stage 11: Opus approval or concerns
│
├─ prompts/
│  ├─ claude/                        ← Reusable prompts for Claude-owned stages
│  └─ codex/                         ← Reusable prompts for Codex-owned stages
│
├─ scripts/
│  ├─ init_project.sh                ← Project initialization
│  ├─ ai_step.sh                     ← Stage runner (prints prompt + logs step)
│  ├─ git_checkpoint.sh              ← Git commit + auto dev_history entry
│  └─ setup_security.sh              ← Security setup (Keychain / Credential Manager)
│
├─ security/
│  ├─ secret_loader.py               ← Cross-platform secret loading
│  ├─ keychain_manager.py            ← macOS Keychain backend
│  └─ credential_manager.py          ← Windows Credential Manager backend
│
├─ src/                              ← Project source code
├─ tests/                            ← Test files
├─ .claude/
│  ├─ settings.json                  ← Model/effort config (fixed in v0.1)
│  └─ language.json                  ← Language preference (set on first run)
├─ .env.example                      ← Environment variable template (no real values)
├─ .gitignore
└─ LICENSE
```

---

## 10. CLI Automation Aliases

Add to your shell config (`~/.zshrc` or `~/.bashrc`):

```bash
source /path/to/your/project/scripts/zsh_aliases.sh
```

| Alias | Stage | Description |
|-------|-------|-------------|
| `aiinit` | — | Initialize project folders |
| `aib` | 1 | Brainstorm (Opus) |
| `aipd` | 2 | Plan Draft (Sonnet) |
| `aipr` | 3 | Plan Review (Sonnet) |
| `aipf` | 4 | Plan Final (Sonnet) |
| `aitd` | 5 | Technical Design (Opus) |
| `aiui` | 6 | UI Requirements (Sonnet) |
| `aiflow` | 7 | UI Flow (Sonnet) |
| `aiimpl` | 8 | Implementation (Codex) |
| `aireview` | 9 | Code Review (Sonnet) |
| `airevise` | 10 | Revision (Codex) |
| `aifinal` | 11 | Final Validation (Opus) |
| `aiqa` | 12 | QA & Release (Sonnet) |
| `aigit` | — | Git checkpoint + dev_history entry |
| `aihist` | — | Manual dev_history entry |

---

## 11. Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-04-21 | 1.0 | Initial release. Generalized from stockpilot workflow. KIS/stock-specific content removed. Cross-platform security module added. |

---

---

# 🔄 AI 기반 개발 워크플로우 (한국어)

> **버전:** 1.0
> **범위:** 범용 — Claude를 오케스트레이터로 사용하는 모든 프로젝트에 적용 가능

---

## 1. 요약

이 워크플로우는 **문서 중심, 역할 분리 개발 프로세스**를 확립합니다:
- **Claude**: 사고, 아키텍처, 검증, QA 담당
- **Codex**: 구현, 디버깅, 반복 담당
- **문서** (`docs/` 폴더): 단일 정보원
- **핸드오프 규칙**: 세션 간 부드러운 전환

---

## 2. 전체 워크플로우: 13단계

| # | 단계 | 담당 | 모델 | 노력 | 입력 | 산출물 | 예상 시간 |
|---|------|------|------|------|------|--------|----------|
| 1 | **아이디어 구상** ⚠️ | Claude + 사용자 | Opus | Medium | 사용자 요청 | `docs/01_brainstorm/brainstorm.md` | 15~30분 |
| 2 | **계획 초안** | Claude | Sonnet | Medium | 구상 결과 | `docs/02_planning/plan_draft.md` | 15~30분 |
| 3 | **계획 검토** | Claude | Sonnet | High | 계획 초안 | `docs/02_planning/plan_review.md` | 10~20분 |
| 4 | **계획 통합** ⚠️ | Claude | Sonnet | Medium | 초안 + 검토 | `docs/02_planning/plan_final.md` | 10~15분 |
| 4.5 | **사용자 승인** 🔴 | 사용자 | — | — | plan_final.md | 승인 확인 | — |
| 5 | **기술 설계** | Claude | Opus | High | 승인된 계획 | `docs/03_design/technical_design.md` | 30~60분 |
| 6 | **UI/UX 요구사항** *(선택)* | Claude | Sonnet | Medium | 기술 설계 | `docs/03_design/ui_requirements.md` | 15~30분 |
| 7 | **UI 플로우** *(선택)* | Claude | Sonnet | Medium | UI 요구사항 | `docs/03_design/ui_flow.md` | 20~40분 |
| 8 | **구현** | Codex | — | High | 기술 설계 | 코드 + 테스트 + 커밋 | 1~8시간 |
| 9 | **코드 리뷰 (1차)** | Claude | Sonnet | High | Codex 구현 결과 | `docs/04_implementation/implementation_progress.md` | 15~30분 |
| 10 | **수정** | Codex | — | Medium | 코드 리뷰 피드백 | 수정된 코드 | 30분~2시간 |
| 11 | **최종 검증** | Claude | Opus | XHigh or High* | 수정된 코드 | `docs/notes/final_validation.md` | 30분~1시간 |
| 12 | **QA & 릴리스** | Claude | Sonnet | Medium | 검증된 코드 | `docs/05_qa_release/qa_scenarios.md` | 15~30분 |
| 13 | **배포 & 아카이브** | Codex | — | Medium | QA 승인 | 병합된 코드 + `HANDOFF.md` 업데이트 | 가변 |

---

## 3. 에이전트 구성

| 에이전트 | 담당 Stage | 주 모델 | Effort |
|---------|-----------|---------|--------|
| 🧠 기획가 (Planner) | 1, 2, 3, 4 | Sonnet (Stage 1만 Opus) | Medium~High |
| 🏗️ 설계사 (Designer) | 5, 6, 7 | Opus (Stage 5) / Sonnet (Stage 6~7) | Medium~High |
| 🔍 검증관 (Reviewer) | 9, 11 | Sonnet (Stage 9) / Opus (Stage 11) | High~XHigh |
| 🧪 QA관 (QA Engineer) | 12, 13 | Sonnet | Medium |
| ⚙️ Codex (외부 도구) | 8, 10 | — | — |

---

## 4. 핵심 운영 원칙

1. **역할 혼합 금지** — Claude는 구현 안 함, Codex는 검증 안 함
2. **설계 전에 계획** — Stage 4 확정 없이 Stage 5 진입 금지
3. **코드 전에 설계** — Stage 5 확정 없이 코드 금지
4. **문서 우선** — 모든 산출물 → `docs/` (다음 단계 전)
5. **단일 정보원** — `docs/` > 채팅 기록 > 기억

---

## 5. 세션 핸드오프 규칙

**읽기 순서 (매 새 세션):**
1. CLAUDE.md → HANDOFF.md → WORKFLOW.md → 관련 docs/

**쓰기 순서 (세션 종료):**
1. 현재 단계 문서 업데이트
2. `docs/notes/dev_history.md`에 항목 추가 (단계 번호, 날짜, 완료 내용, 차단 요인)
3. `HANDOFF.md` 업데이트 (현재 상태, 다음 작업, 관련 문서 링크)
4. `HANDOFF.md` 하단에 다음 세션 프롬프트 작성

---

*이 워크플로우는 살아있는 문서입니다. 피드백과 개선사항을 환영합니다.*
