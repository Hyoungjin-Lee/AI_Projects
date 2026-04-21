# 🤖 Claude Operating Guide

> **Read order for every new session:** CLAUDE.md → HANDOFF.md → WORKFLOW.md → relevant docs/
> Current status and next tasks: see `HANDOFF.md`

---

> 한국어 버전: 이 파일 하단 참조 (Korean version below)

---

## 1. Project Summary

**[PROJECT_NAME]** — [One-line description of what this project does]

- **Python environment:** `venv/bin/python3`
- **Project path:** `/path/to/your/project`
- **Main scripts:** `src/` folder

> ✏️ Fill in the above when starting a new project.

---

## 2. Workflow Role Rules (see WORKFLOW.md for details)

```
✅ At the start of every new session, check WORKFLOW.md
✅ Feature development (new features, refactoring) → follow WORKFLOW.md Stages 1–13
✅ Claude's role: Planning (Stages 1–4) + Design (Stages 5–7) + Review (Stages 9, 11) + QA (Stage 12)
❌ Claude does NOT implement (Stages 8, 10) → always delegate to Codex
```

**Decision guide before starting work:**
- **Hotfix / config change / number tweak** → edit directly (execution mode)
- **New feature / logic / refactor** → write docs for Stages 1–7, then hand off to Codex

### 🔴 Mandatory Collaboration Checkpoints

| Stage | Rule |
|-------|------|
| Stage 1 Brainstorm | Discuss direction with the user — Claude must NOT write alone |
| After Stage 4 | **User approval required** → do NOT enter Stage 5 without it |
| Stage 5 Technical Design | Only start after Stage 4 approval is confirmed |

---

## 3. Absolute Rules (Security)

```
❌ Never expose API keys, account numbers, or tokens in code or logs
❌ Never place real credentials in .env (use secret_loader.py)
✅ All scripts load secrets via secret_loader.py (Keychain / Credential Manager)
✅ Always test with --dry-run before making real changes
✅ Run python3 -m py_compile on any modified file before committing
```

### Secret Loading Pattern
```python
from security.secret_loader import load_secret
api_key = load_secret("MY_API_KEY")   # loads from OS keychain
```

---

## 4. Running Scripts

```bash
cd /path/to/your/project

# First-time security setup
python3 security/secret_loader.py --setup

# Dry-run test (no side effects)
python3 src/main.py --dry-run

# Check git status
git status

# One-step git checkpoint
bash scripts/git_checkpoint.sh "Stage X complete: description"

# View logs
tail -50 logs/app.log
```

---

## 5. Key Files

| File | Purpose |
|------|---------|
| `security/secret_loader.py` | Cross-platform secret loading (macOS / Windows) |
| `security/keychain_manager.py` | macOS Keychain backend |
| `security/credential_manager.py` | Windows Credential Manager backend |
| `src/` | Main project source code |
| `docs/notes/dev_history.md` | Cumulative log of all stages and decisions |
| `data/` | Runtime data files (if needed) |
| `logs/` | Execution logs (if needed) |

---

## 6. Scheduled Tasks (if applicable)

> Fill in your schedule here after project setup.

| Time | Script | Description |
|------|--------|-------------|
| — | — | (add your scheduled tasks here) |

---

## 7. Skill References

| Task | Reference |
|------|-----------|
| API data access | `.skills/api-client/SKILL.md` (add your own) |
| Report generation | `.skills/reporting/SKILL.md` (add your own) |

---

## 8. Code Validation Guide

- Syntax check: `python3 -m py_compile src/<file>.py`
- Complex logic changes: use an Opus sub-agent (high effort) for independent validation
- All new files must pass `py_compile` before being committed

---

---

# 🤖 Claude 운영 지침 (한국어)

> **새 세션 읽기 순서:** CLAUDE.md → HANDOFF.md → WORKFLOW.md → 관련 docs/
> 현재 상태 및 다음 작업: `HANDOFF.md` 참고

---

## 1. 프로젝트 한 줄 요약

**[프로젝트명]** — [이 프로젝트가 하는 일을 한 줄로]

- **Python 환경:** `venv/bin/python3`
- **프로젝트 경로:** `/path/to/your/project`
- **메인 스크립트:** `src/` 폴더

> ✏️ 새 프로젝트 시작 시 위 내용을 채워주세요.

---

## 2. 워크플로우 역할 규칙 (WORKFLOW.md 요약)

```
✅ 새 세션 시작 시 반드시 WORKFLOW.md 확인
✅ 기능 개발(새 기능·리팩토링)은 WORKFLOW.md Stage 1~13 준수
✅ Claude 역할: 기획(Stage 1~4) + 설계(Stage 5~7) + 검증(Stage 9, 11) + QA(Stage 12)
❌ Claude는 구현(Stage 8, 10) 직접 금지 → 반드시 Codex에 위임
```

작업 전 판단 기준:
- **핫픽스·수치조정·설정변경** → 직접 수정 가능 (실행 모드)
- **새 기능·로직 추가·리팩토링** → WORKFLOW.md Stage 1~7 문서 작성 후 Codex 위임

### 🔴 필수 협업 체크포인트

| 단계 | 규칙 |
|------|------|
| Stage 1 브레인스토밍 | 사용자와 대화하며 방향 잡기 — Claude 혼자 작성 금지 |
| Stage 4 계획 통합 완료 후 | **사용자 승인 필수** → 승인 없이 Stage 5 진입 금지 |
| Stage 5 기술 설계 | Stage 4 승인 확인 후에만 작성 |

---

## 3. 절대 규칙 (보안)

```
❌ API키·계좌번호·토큰을 코드/로그에 평문 노출 금지
❌ 실제 인증정보를 .env에 저장 금지 (secret_loader.py 사용)
✅ 모든 스크립트는 secret_loader.py로 OS 키체인에서 인증정보 로드
✅ 변경 전 반드시 --dry-run으로 먼저 확인
✅ 파일 생성·수정 후 python3 -m py_compile 로 문법 검사
```

### 인증정보 로드 패턴
```python
from security.secret_loader import load_secret
api_key = load_secret("MY_API_KEY")   # OS 키체인에서 로드
```

---

## 4. 스크립트 실행

```bash
cd /path/to/your/project

# 최초 보안 설정
python3 security/secret_loader.py --setup

# 테스트 (부작용 없음)
python3 src/main.py --dry-run

# Git 상태 확인
git status

# Git 체크포인트 (한 번에)
bash scripts/git_checkpoint.sh "Stage X 완료: 설명"

# 로그 확인
tail -50 logs/app.log
```

---

## 5. 핵심 파일

| 파일 | 역할 |
|------|------|
| `security/secret_loader.py` | 크로스플랫폼 인증정보 로더 (macOS / Windows) |
| `security/keychain_manager.py` | macOS Keychain 백엔드 |
| `security/credential_manager.py` | Windows Credential Manager 백엔드 |
| `src/` | 프로젝트 소스 코드 |
| `docs/notes/dev_history.md` | 전체 단계 및 결정 누적 로그 |
| `data/` | 런타임 데이터 파일 (필요시) |
| `logs/` | 실행 로그 (필요시) |

---

## 6. 자동 실행 스케줄 (해당시)

> 프로젝트 설정 후 여기에 스케줄을 채워주세요.

| 시각 | 스크립트 | 설명 |
|------|----------|------|
| — | — | (여기에 스케줄 추가) |

---

## 7. 스킬 참조

| 작업 | 참조 |
|------|------|
| API 데이터 조회 | `.skills/api-client/SKILL.md` (직접 추가) |
| 리포트 생성 | `.skills/reporting/SKILL.md` (직접 추가) |

---

## 8. 코드 검증 가이드

- 문법 검사: `python3 -m py_compile src/<파일>.py`
- 복잡한 로직 변경 시: Opus 서브에이전트(high effort)로 독립 검증
- 신규 파일은 반드시 `py_compile` 통과 후 커밋
