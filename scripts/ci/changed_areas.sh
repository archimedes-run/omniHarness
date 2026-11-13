#!/usr/bin/env bash
# Decide which CI areas a change touches. Reads changed paths (one per line,
# repo-relative) on stdin; prints `backend=`, `frontend=` and `reason=` lines
# for $GITHUB_OUTPUT. Run from the repository root.
#
# Fail-safe by construction: anything not positively classified runs everything.
#
#   .github/**, scripts/ci/**          -> everything (CI itself changed)
#   frontend/**                        -> frontend
#   backend/**, docker/**, scripts/**,
#   skills/**, config.example.yaml,
#   Makefile, pyproject.toml, uv.lock  -> backend
#   *.md, docs/**, specs/**            -> docs only (docs lint, which always runs)
#   anything else                      -> everything
#
# Cross-area reads. Tests in one area read files from another (backend tests
# read frontend/next.config.js, specs/.../closed-set-coverage.md, docs/SETUP.md;
# frontend tests read config.example.yaml, THIRD-PARTY-NOTICES.md,
# backend/app/gateway/routers/composio.py). So a changed file whose basename
# appears anywhere under the other area's tests directory turns that area on,
# and frontend/tests/** turns backend on (backend/tests/test_shipped_paths.py
# scans every file there). LIMIT: a path assembled from a variable is invisible
# to this; push to main and the nightly run everything as the backstop.
set -euo pipefail

backend=false
frontend=false
all=false
reasons=()
count=0

while IFS= read -r f; do
  [ -n "$f" ] || continue
  count=$((count + 1))
  case "$f" in
    .github/* | scripts/ci/*)
      all=true; reasons+=("$f: CI definition") ;;
    frontend/tests/*)
      frontend=true; backend=true; reasons+=("$f: frontend test, scanned by backend tests") ;;
    frontend/*)
      frontend=true ;;
    backend/* | docker/* | scripts/* | skills/* | config.example.yaml | Makefile | pyproject.toml | uv.lock)
      backend=true ;;
    *.md | docs/* | specs/*)
      ;;
    *)
      all=true; reasons+=("$f: unclassified") ;;
  esac
  base=$(basename -- "$f")
  case "$f" in
    backend/*) ;;
    *) if [ "$backend" = false ] && grep -rqF -- "$base" backend/tests 2>/dev/null; then
         backend=true; reasons+=("$f: named by backend/tests")
       fi ;;
  esac
  case "$f" in
    frontend/*) ;;
    *) if [ "$frontend" = false ] && grep -rqF -- "$base" frontend/tests 2>/dev/null; then
         frontend=true; reasons+=("$f: named by frontend/tests")
       fi ;;
  esac
done

if [ "$count" -eq 0 ]; then
  all=true; reasons+=("no changed files listed")
fi
if [ "$all" = true ]; then
  backend=true
  frontend=true
fi

echo "backend=$backend"
echo "frontend=$frontend"
echo "reason=${reasons[*]:-path rules only}"
