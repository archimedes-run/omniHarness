#!/bin/sh
# Daily rotation for nginx's logs (in the nginx container, and for the host
# nginx that scripts/serve.sh starts), plus a size cap for the other
# append-only logs (console captures).
#
# Matches the gateway's policy (app/gateway/log_files.py): a file per day,
# 30 days kept, gzip-compressed. NO LINE IS EVER LOST:
#   1. the live file is RENAMED (nginx keeps writing to it via its descriptor);
#   2. nginx is told to reopen (SIGUSR1) and we WAIT, bounded, until it has:
#      the pid is alive and a fresh live file exists;
#   3. only then is the renamed day compressed.
# If the reopen fails (stale/missing pidfile, nginx gone, timeout) nothing is
# compressed or unlinked: each renamed file is moved BACK to its live name, an
# ERROR is printed to stderr, and the script exits 1.
#
#   rotate-logs.sh once <logdir> <stamp> <pidfile>   rotate now, stamp the files
#   rotate-logs.sh loop <logdir> <pidfile>           rotate at each new day
#   rotate-logs.sh cap  <file> <max-bytes>           copy+truncate when too big
#
# LOG_NAMES (default "access error"), RETENTION_DAYS (30), CHECK_SECONDS (60),
# REOPEN_WAIT_TENTHS (100 = 10 s) and CAP_FILES/CAP_BYTES (for loop) are tunable.
# Plain POSIX sh + busybox: works in nginx:alpine on Docker Desktop for Mac.
set -u

LOG_NAMES="${LOG_NAMES:-access error}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
CHECK_SECONDS="${CHECK_SECONDS:-60}"
REOPEN_WAIT_TENTHS="${REOPEN_WAIT_TENTHS:-100}"
CAP_FILES="${CAP_FILES:-}"
CAP_BYTES="${CAP_BYTES:-52428800}"

prune() {
    dir="$1"
    for name in $LOG_NAMES; do
        find "$dir" -maxdepth 1 -type f -name "$name-*.log.gz" -mtime +"$RETENTION_DAYS" -exec rm -f {} \;
    done
}

reopened() {
    # $1 pid; rest: live files that must exist again after the reopen
    pid="$1"
    shift
    kill -0 "$pid" 2>/dev/null || return 1
    for live in "$@"; do
        [ -e "$live" ] || return 1
    done
    return 0
}

rotate_once() {
    dir="$1"
    stamp="$2"
    pidfile="$3"
    rotated=""
    lives=""
    for name in $LOG_NAMES; do
        live="$dir/$name.log"
        if [ -s "$live" ] && [ ! -e "$dir/$name-$stamp.log" ] && [ ! -e "$dir/$name-$stamp.log.gz" ]; then
            if mv "$live" "$dir/$name-$stamp.log"; then
                rotated="$rotated $name"
                lives="$lives $live"
            fi
        fi
    done
    [ -n "$rotated" ] || { prune "$dir"; return 0; }

    pid=""
    [ -s "$pidfile" ] && pid="$(cat "$pidfile")"
    ok=1
    if [ -n "$pid" ] && kill -USR1 "$pid" 2>/dev/null; then
        tries=0
        # shellcheck disable=SC2086
        until reopened "$pid" $lives; do
            tries=$((tries + 1))
            if [ "$tries" -ge "$REOPEN_WAIT_TENTHS" ]; then
                ok=0
                break
            fi
            sleep 0.1
        done
    else
        ok=0
    fi

    if [ "$ok" -ne 1 ]; then
        for name in $rotated; do
            if [ ! -e "$dir/$name.log" ]; then
                mv "$dir/$name-$stamp.log" "$dir/$name.log"
            fi
        done
        echo "rotate-logs: ERROR: nginx did not reopen its logs (pidfile $pidfile, pid '${pid}'); rotation abandoned, nothing compressed or removed" >&2
        return 1
    fi

    for name in $rotated; do
        gzip -f "$dir/$name-$stamp.log"
    done
    prune "$dir"
    return 0
}

cap_file() {
    file="$1"
    max="$2"
    [ -f "$file" ] || return 0
    size="$(wc -c <"$file" | tr -d ' ')"
    [ "$size" -gt "$max" ] || return 0
    stamp="$(date +%Y-%m-%d-%H%M%S)"
    base="${file%.log}"
    # copy, then truncate: the writer appends (O_APPEND) and keeps going.
    cp "$file" "$base-$stamp.log" && : >"$file" && gzip -f "$base-$stamp.log"
    find "$(dirname "$file")" -maxdepth 1 -type f -name "$(basename "$base")-*.log.gz" -mtime +"$RETENTION_DAYS" -exec rm -f {} \;
}

case "${1:-}" in
    once)
        rotate_once "$2" "$3" "$4"
        exit $?
        ;;
    cap)
        cap_file "$2" "$3"
        ;;
    loop)
        dir="$2"
        pidfile="$3"
        day="$(date +%Y-%m-%d)"
        while :; do
            sleep "$CHECK_SECONDS"
            for f in $CAP_FILES; do
                cap_file "$f" "$CAP_BYTES"
            done
            now="$(date +%Y-%m-%d)"
            if [ "$now" != "$day" ]; then
                # On failure the files stay live; retry on the next check.
                rotate_once "$dir" "$day" "$pidfile" && day="$now"
            fi
        done
        ;;
    *)
        echo "usage: $0 once <logdir> <stamp> <pidfile> | loop <logdir> <pidfile> | cap <file> <max-bytes>" >&2
        exit 2
        ;;
esac
