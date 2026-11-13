#!/bin/sh
# Delete the tool caches and build output that regenerate on their own:
# Python bytecode, mypy/pytest/ruff caches, and the local Next.js build.
# Never touches data, config, secrets, logs or installed dependencies
# (backend/.venv, frontend/node_modules). Safe to run any time; the
# frontend build is kept while a local dev server is serving it.
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

find . \( -path ./frontend/node_modules -o -path ./backend/.venv -o -path ./.git \) -prune \
    -o -type d -name __pycache__ -prune -exec rm -rf {} +
rm -rf backend/.mypy_cache backend/.pytest_cache backend/.ruff_cache \
    .mypy_cache .pytest_cache .ruff_cache

# Only this repo's dev server counts; another project may hold :3000.
serving=""
if command -v lsof >/dev/null 2>&1; then
    for pid in $(lsof -nP -t -iTCP:"${FRONTEND_DEV_PORT:-3000}" -sTCP:LISTEN 2>/dev/null || true); do
        case "$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')" in
        "$root/frontend"*) serving=1 ;;
        esac
    done
fi
if [ -n "$serving" ]; then
    echo "Kept frontend/.next: this repo's dev server is serving it on :${FRONTEND_DEV_PORT:-3000}"
else
    rm -rf frontend/.next frontend/tsconfig.tsbuildinfo
fi
echo "✓ Tool caches cleaned"
