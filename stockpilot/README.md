# stockpilot

한국투자증권(KIS) Open API + Claude AI를 활용한 반자동 주식 투자 시스템.
단타·스윙·정량 세 관점의 기술적 분석을 자동화하고, 결과를 Notion/Word/Markdown으로 기록한다.

---

## 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 투자 스타일 | 단타(데이트레이딩) + 스윙(며칠~몇 주) + 정량 시스템 트레이딩 |
| API 환경 | 한국투자증권 실전투자 계좌 |
| 결과 공유 | Notion DB + Word/PDF 리포트 + Markdown |
| 주문 정책 | 주문 **초안** 생성까지만 (실주문은 별도 명시 필요) |

---

## 폴더 구조

```
stockpilot/
├── .env                             ← 직접 만들어야 함 (아래 셋업 참조)
├── .env.example                     ← 환경변수 템플릿
├── .gitignore
├── README.md
├── .skills/
│   ├── kis-api/                     ← 데이터 수집 스킬
│   │   ├── SKILL.md
│   │   ├── scripts/                 ← get_quote, get_daily_chart 등
│   │   └── references/
│   ├── stock-analysis/              ← 기술적 분석 스킬
│   │   ├── SKILL.md
│   │   ├── scripts/                 ← indicators, analyze_* 등
│   │   └── references/
│   └── trading-report/              ← 리포트 생성 스킬
│       ├── SKILL.md
│       └── templates/
├── data/
│   ├── raw/      ← API 원시 데이터 (자동 저장)
│   └── cache/    ← 토큰 캐시
├── reports/      ← 생성된 리포트
└── journal/      ← 매매 일지
    └── daily/    ← 일일 시황 브리프
```

---

## 셋업 순서

### 1단계: KIS 개발자 포털에서 앱키 발급

1. https://apiportal.koreainvestment.com 접속 후 로그인
2. **앱 등록** → 이름 입력 → **실전투자** 선택
3. APP KEY / APP SECRET 발급 (발급 즉시 복사 보관)
4. **IP 등록**: 내 PC IP 주소를 허용 목록에 추가 (미등록 시 호출 차단됨)
   - 내 IP 확인: https://www.myip.com

### 2단계: .env 파일 생성

프로젝트 루트에 `.env` 파일을 만들고 아래처럼 채운다.

```bash
cp .env.example .env
# 텍스트 에디터로 .env 열어 실제 값 입력
```

```
KIS_APP_KEY=발급받은앱키
KIS_APP_SECRET=발급받은시크릿
KIS_ACCOUNT_NO=12345678-01    # HTS에서 확인
KIS_ENV=real
```

### 3단계: 파이썬 패키지 확인

```bash
pip install requests python-dotenv pandas numpy
```

### 4단계: 첫 호출 테스트

```bash
cd .skills/kis-api/scripts
python get_quote.py 005930      # 삼성전자 현재가 조회
```

성공하면 JSON이 출력되고 `data/raw/`에 파일이 저장된다.

---

## 일일 워크플로 예시

### 장 시작 전 (08:30~09:00)

```
"오늘 시황 정리해줘"
→ Claude가 daily_brief 템플릿 기반으로 관심종목 현황 정리
```

### 종목 분석

```
"삼성전자 어때? 스윙으로 봐줘"
→ kis-api로 일봉 받고 → analyze_swing.py 실행 → 결과 요약

"005930 종합 분석해줘"
→ analyze_full.py 실행 → 단타·스윙·정량 세 관점 종합
```

### 리포트 저장

```
"Notion에 기록해줘"
→ trading-report 스킬이 Notion DB에 페이지 생성

"Word 리포트 만들어줘"
→ docx 스킬 활용해 reports/ 폴더에 저장
```

### 주문 초안 생성

```
"삼성전자 70000원에 500주 매수 초안 만들어줘"
→ draft_order.py가 JSON payload + curl 명령 출력 (실제 전송 X)
```

### 매매 후 일지

```
"오늘 SK하이닉스 매매 일지 써줘"
→ trade_journal_entry 템플릿 기반으로 journal/ 에 저장
```

---

## 보안 주의사항

- `.env` 파일을 **절대** Git에 올리지 마세요. `.gitignore`에 포함되어 있음.
- APP KEY / APP SECRET 유출 시 즉시 KIS 포털에서 재발급 후 기존 키 비활성화.
- `KIS_ALLOW_LIVE_ORDER=1` 환경변수 없이는 실주문이 전송되지 않음 — 의도적인 안전장치.
- 실주문 전 반드시 초안(JSON payload)을 직접 검토 후 실행.

---

## 스킬 목록

| 스킬 | 경로 | 역할 |
|---|---|---|
| kis-api | `.skills/kis-api/` | 현재가·차트·잔고 조회, 주문 초안 |
| stock-analysis | `.skills/stock-analysis/` | 단타·스윙·정량 기술적 분석 |
| trading-report | `.skills/trading-report/` | Notion·Word·Markdown 리포트 생성 |

---

*본 시스템은 투자 참고 목적이며, 투자 결과에 대한 책임은 투자자 본인에게 있습니다.*
