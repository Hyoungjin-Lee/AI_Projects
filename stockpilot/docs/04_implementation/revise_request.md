# Stage 10: 수정 요청서 — telegram_sender.py 코드 리뷰 반영

> 날짜: 2026-04-18 | 담당: Codex | Effort: Medium
> 기준: Stage 9 코드 리뷰 결과 (`docs/04_implementation/code_review.md`)

---

## 수정 대상 파일

`morning_report/telegram_sender.py` 한 파일만 수정한다.
다른 파일은 건드리지 않는다.

---

## 수정 1 — 🔴 P0 필수: `_split_message()` 무한루프 제거

### 문제
현재 구현은 청크 수가 늘어날 때마다 prefix 길이가 변하고,
그 변화로 청크 수가 또 늘어나는 순환이 이론상 발생 가능.

### 현재 코드
```python
def _split_message(text: str, limit: int = _MSG_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    total = 2
    while True:
        prefix_len = len(f"[{total}/{total}]\n")
        body_limit = limit - prefix_len
        chunks = [text[i:i + body_limit] for i in range(0, len(text), body_limit)]
        if len(chunks) == total:
            return [f"[{idx + 1}/{total}]\n{chunk}" for idx, chunk in enumerate(chunks)]
        total = len(chunks)
```

### 교체할 코드
```python
def _split_message(text: str, limit: int = _MSG_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = [text[i:i + limit] for i in range(0, len(text), limit)]
    total = len(chunks)
    return [f"[{i+1}/{total}]\n{chunk}" for i, chunk in enumerate(chunks)]
```

### 이유
- prefix 최대 9자(`[10/10]\n`), limit 4000자 → 실용상 오차 없음
- 루프 제거로 단순하고 안전한 구조

---

## 수정 2 — 🟡 P1 권고: `send_text()` 청크 실패 시 즉시 중단

### 문제
현재 1번 청크 전송 실패 시 2, 3번 청크를 계속 전송한다.
수신자 입장에서 맥락 없는 중간 청크만 받게 되어 혼란스럽다.

### 현재 코드 (send_text 내부)
```python
    for idx, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            print(f"[텔레그램] {idx}/{len(chunks)} 청크 전송")

        if not _send_raw(token, chat_id, chunk):
            success = False

        if idx < len(chunks):
            time.sleep(1)

    return success
```

### 교체할 코드
```python
    for idx, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            print(f"[텔레그램] {idx}/{len(chunks)} 청크 전송")

        if not _send_raw(token, chat_id, chunk):
            return False  # 실패 즉시 중단

        if idx < len(chunks):
            time.sleep(1)

    return True
```

### 이유
브리핑 특성상 "전부 전송 or 전부 실패"가 "일부만 전송"보다 낫다.

---

## 수정 원칙

```
✅ 위 2개 수정만 진행. 다른 코드 변경 금지.
✅ 함수 시그니처, 변수명, 로깅 패턴은 그대로 유지.
✅ 수정 후 py_compile 문법 검사 필수.
```

---

## 확인해야 할 TODO

- [ ] `_split_message()` 교체 완료
- [ ] `send_text()` 실패 시 즉시 `return False` 교체 완료
- [ ] `py_compile` 통과

```bash
venv/bin/python3 -m py_compile morning_report/telegram_sender.py
```

---

## 다음 단계: final_review (Stage 11, Claude Opus XHigh)
