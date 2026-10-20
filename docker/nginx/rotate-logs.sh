#!/bin/sh
# Daily rotation for nginx's access/error logs, inside the nginx container.
#
# Matches the gateway's policy (app/gateway/log_files.py): a file per day,
# 30 days kept; nginx's are also gzip-compressed. No lines are lost: the live
# file is RENAMED (nginx keeps writing to the renamed file through its open
# descriptor), then nginx is told to reopen its logs (SIGUSR1), and only then is
# the renamed file compressed. Plain POSIX sh + busybox: works in nginx:alpine
# on Docker Desktop for Mac and on Linux; no logrotate, no cron.
#
#   rotate-logs.sh once <logdir> <stamp> <pidfile>   rotate now, stamp the files
#   rotate-logs.sh loop <logdir> <pidfile>           rotate at each new day
#
# RETENTION_DAYS (default 30) and CHECK_SECONDS (default 60) are tunable.
set -u

RETENTION_DAYS="${RETENTION_DAYS:-30}"
CHECK_SECONDS="${CHECK_SECONDS:-60}"

rotate_once() {
    dir="$1"
    stamp="$2"
    pidfile="$3"
    rotated=""
    for name in access error; do
        live="$dir/$name.log"
        if [ -s "$live" ] && [ ! -e "$dir/$name-$stamp.log" ] && [ ! -e "$dir/$name-$stamp.log.gz" ]; then
            mv "$live" "$dir/$name-$stamp.log" && rotated="$rotated $dir/$name-$stamp.log"
        fi
    done
    if [ -n "$rotated" ] && [ -s "$pidfile" ]; then
        kill -USR1 "$(cat "$pidfile")" 2>/dev/null || true
        # Let nginx finish reopening before the old files are compressed.
        sleep 1
    fi
    for file in $rotated; do
        gzip -f "$file"
    done
    # Retention: compressed days older than RETENTION_DAYS go.
    find "$dir" -maxdepth 1 -type f \( -name 'access-*.log.gz' -o -name 'error-*.log.gz' \) -mtime +"$RETENTION_DAYS" -exec rm -f {} \;
}

case "${1:-}" in
    once)
        rotate_once "$2" "$3" "$4"
        ;;
    loop)
        dir="$2"
        pidfile="$3"
        day="$(date +%Y-%m-%d)"
        while :; do
            sleep "$CHECK_SECONDS"
            now="$(date +%Y-%m-%d)"
            if [ "$now" != "$day" ]; then
                rotate_once "$dir" "$day" "$pidfile"
                day="$now"
            fi
        done
        ;;
    *)
        echo "usage: $0 once <logdir> <stamp> <pidfile> | loop <logdir> <pidfile>" >&2
        exit 2
        ;;
esac
