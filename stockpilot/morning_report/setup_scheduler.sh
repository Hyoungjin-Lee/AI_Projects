#!/bin/bash
# setup_scheduler.sh — Mac 자동실행 스케줄러 설정
# 4개 스케줄 자동 등록:
#   08:20 관심종목 동기화   (watchlist_sync.py)
#   08:30 모닝 브리핑       (morning_report.py)
#   09:10 장초기 브리핑     (intraday_report.py)
#   20:30 장마감 결산       (closing_report.py)
#   23:30 야간 종목 발굴    (stock_discovery.py)
#
# 실행 방법:
#   chmod +x setup_scheduler.sh
#   ./setup_scheduler.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
SCRIPT="$PROJECT_DIR/morning_report/morning_report.py"
INTRADAY_SCRIPT="$PROJECT_DIR/morning_report/intraday_report.py"
CLOSING_SCRIPT="$PROJECT_DIR/morning_report/closing_report.py"
DISCOVERY_SCRIPT="$PROJECT_DIR/morning_report/stock_discovery.py"
WATCHLIST_SCRIPT="$PROJECT_DIR/morning_report/watchlist_sync.py"
LOG_DIR="$PROJECT_DIR/logs"

PLIST_NAME="com.aigeenya.stockreport"
PLIST_NAME_INTRADAY="com.aigeenya.stockreport.intraday"
PLIST_NAME_CLOSING="com.aigeenya.stockreport.closing"
PLIST_NAME_DISCOVERY="com.aigeenya.stockreport.discovery"
PLIST_NAME_WATCHLIST="com.aigeenya.stockreport.watchlist"

PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
PLIST_PATH_INTRADAY="$HOME/Library/LaunchAgents/$PLIST_NAME_INTRADAY.plist"
PLIST_PATH_CLOSING="$HOME/Library/LaunchAgents/$PLIST_NAME_CLOSING.plist"
PLIST_PATH_DISCOVERY="$HOME/Library/LaunchAgents/$PLIST_NAME_DISCOVERY.plist"
PLIST_PATH_WATCHLIST="$HOME/Library/LaunchAgents/$PLIST_NAME_WATCHLIST.plist"

echo "================================================"
echo "주식 AI 브리핑 자동 실행 설정"
echo "================================================"
echo ""
echo "프로젝트 경로: $PROJECT_DIR"
echo "실행 일정: 08:20 동기화 / 08:30 모닝 / 09:10 장초기 / 20:30 결산 / 23:30 발굴"
echo ""

# ── 로그 폴더 + 로그 로테이션 스크립트 ───────────────────────────────────────
mkdir -p "$LOG_DIR"

cat > "$LOG_DIR/rotate_logs.sh" << 'ROTATE'
#!/bin/bash
# 10MB 초과 시 로그 압축 보관
LOG_DIR="$(dirname "$0")"
for log in morning_report.log morning_report_error.log \
           intraday_report.log intraday_report_error.log \
           closing_report.log closing_report_error.log \
           discovery_report.log discovery_report_error.log; do
    logfile="$LOG_DIR/$log"
    if [ -f "$logfile" ] && [ "$(stat -f%z "$logfile" 2>/dev/null || stat -c%s "$logfile")" -gt 10485760 ]; then
        mv "$logfile" "$logfile.$(date +%Y%m%d_%H%M%S)"
        gzip "$logfile."* 2>/dev/null || true
    fi
done
ROTATE
chmod +x "$LOG_DIR/rotate_logs.sh"

# ── Python 가상환경 확인 ──────────────────────────────────────────────────────
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ 가상환경을 찾을 수 없습니다: $VENV_PYTHON"
    echo "   먼저 프로젝트 루트에서 다음을 실행하세요:"
    echo "   python3 -m venv venv"
    echo "   source venv/bin/activate"
    echo "   pip install -r morning_report/requirements.txt"
    exit 1
fi
echo "✅ 가상환경 확인: $VENV_PYTHON"

# ── 기존 plist 모두 제거 ─────────────────────────────────────────────────────
for plist_path in "$PLIST_PATH" "$PLIST_PATH_INTRADAY" "$PLIST_PATH_CLOSING" "$PLIST_PATH_DISCOVERY" "$PLIST_PATH_WATCHLIST"; do
    if [ -f "$plist_path" ]; then
        launchctl unload "$plist_path" 2>/dev/null || true
        rm "$plist_path"
        echo "✅ 기존 스케줄 제거: $(basename $plist_path)"
    fi
done

# ══════════════════════════════════════════════════════════════════════════════
# 0. 관심종목 동기화 plist (평일 08:20 — 모닝 브리핑 직전)
# ══════════════════════════════════════════════════════════════════════════════
cat > "$PLIST_PATH_WATCHLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME_WATCHLIST</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>$WATCHLIST_SCRIPT</string>
    </array>

    <!-- 평일(월~금) 08:20 실행 (모닝 브리핑 10분 전) -->
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>20</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>20</integer></dict>
    </array>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/watchlist_sync.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/watchlist_sync_error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
echo "✅ 관심종목 동기화 스케줄 생성: 평일 08:20"

# ══════════════════════════════════════════════════════════════════════════════
# 1. 모닝 브리핑 plist (평일 08:30)
# ══════════════════════════════════════════════════════════════════════════════
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>$SCRIPT</string>
    </array>

    <!-- 평일(월~금) 08:30 실행 -->
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
    </array>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/morning_report.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/morning_report_error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
echo "✅ 모닝 브리핑 스케줄 생성: 평일 08:30"

# ══════════════════════════════════════════════════════════════════════════════
# 2. 장초기 브리핑 plist (평일 09:10)
# ══════════════════════════════════════════════════════════════════════════════
cat > "$PLIST_PATH_INTRADAY" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME_INTRADAY</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>$INTRADAY_SCRIPT</string>
    </array>

    <!-- 평일(월~금) 09:10 실행 -->
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>10</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>10</integer></dict>
    </array>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/intraday_report.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/intraday_report_error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
echo "✅ 장초기 브리핑 스케줄 생성: 평일 09:10"

# ══════════════════════════════════════════════════════════════════════════════
# 3. 장마감 결산 plist (평일 16:00)
# ══════════════════════════════════════════════════════════════════════════════
cat > "$PLIST_PATH_CLOSING" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME_CLOSING</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>$CLOSING_SCRIPT</string>
    </array>

    <!-- 평일(월~금) 20:30 실행 (넥스트장 마감 후) -->
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>20</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>20</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>20</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>20</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>20</integer><key>Minute</key><integer>30</integer></dict>
    </array>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/closing_report.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/closing_report_error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
echo "✅ 장마감 결산 스케줄 생성: 평일 20:30"

# ══════════════════════════════════════════════════════════════════════════════
# 4. 야간 종목 발굴 plist (매일 23:30 — 주말 포함, 스크립트 내부서 일요일 제외)
# ══════════════════════════════════════════════════════════════════════════════
cat > "$PLIST_PATH_DISCOVERY" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME_DISCOVERY</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>$DISCOVERY_SCRIPT</string>
    </array>

    <!-- 월~토 23:30 실행 (미국 장 초반 반영, 일요일 제외는 스크립트 내부 처리) -->
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
    </array>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/discovery_report.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/discovery_report_error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
echo "✅ 야간 종목 발굴 스케줄 생성: 월~토 23:30"

# ── launchd에 모두 등록 ───────────────────────────────────────────────────────
launchctl load "$PLIST_PATH_WATCHLIST"
launchctl load "$PLIST_PATH"
launchctl load "$PLIST_PATH_INTRADAY"
launchctl load "$PLIST_PATH_CLOSING"
launchctl load "$PLIST_PATH_DISCOVERY"
echo ""
echo "✅ 전체 스케줄 등록 완료"

echo ""
echo "================================================"
echo "설정 완료!"
echo ""
echo "📅 실행 일정:"
echo "   08:20 (평일)  관심종목 동기화   watchlist_sync.py"
echo "   08:30 (평일)  모닝 브리핑       morning_report.py"
echo "   09:10 (평일)  장초기 브리핑     intraday_report.py"
echo "   20:30 (평일)  장마감 결산       closing_report.py"
echo "   23:30 (월~토) 야간 종목 발굴    stock_discovery.py"
echo ""
echo "📄 로그 위치: $LOG_DIR/"
echo "📓 매매일지:  $PROJECT_DIR/reports/journal/"
echo "👀 관심 종목: $PROJECT_DIR/data/watchlist.json"
echo ""
echo "⚠️  주의사항:"
echo "   1. Mac이 각 실행 시각에 켜져(또는 깨어) 있어야 합니다."
echo "      배터리 설정 → '전원 어댑터 사용 시 잠자지 않게 하기' ON 권장"
echo ""
echo "   2. 한국 공휴일은 launchd가 인식 불가."
echo "      공휴일에는 KIS API 빈 데이터로 자동 감지 후 조용히 종료됩니다."
echo ""
echo "🔧 테스트 명령어:"
echo "   [동기화]   $VENV_PYTHON $WATCHLIST_SCRIPT --dry-run"
echo "   [현황확인] $VENV_PYTHON $WATCHLIST_SCRIPT --show"
echo "   [모닝]     $VENV_PYTHON $SCRIPT --dry-run"
echo "   [장초기]   $VENV_PYTHON $INTRADAY_SCRIPT --dry-run"
echo "   [장마감]   $VENV_PYTHON $CLOSING_SCRIPT --dry-run"
echo "   [종목발굴] $VENV_PYTHON $DISCOVERY_SCRIPT --dry-run"
echo ""
echo "   스케줄 등록 확인:"
echo "     launchctl list | grep stockreport"
echo ""
echo "   전체 스케줄 제거:"
echo "     launchctl unload $PLIST_PATH"
echo "     launchctl unload $PLIST_PATH_INTRADAY"
echo "     launchctl unload $PLIST_PATH_CLOSING"
echo "     launchctl unload $PLIST_PATH_DISCOVERY"
echo "================================================"
