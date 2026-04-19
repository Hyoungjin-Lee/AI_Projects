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
