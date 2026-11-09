#!/usr/bin/env bash
# Full verification: tests + coverage, lint, type-check. Tools live outside the repo (TOOLS dir), so no project deps.
set -u
TOOLS=${TOOLS:-/tmp/claude-0/-home-user-projects/30a903c4-e629-57bb-9f72-e47ef1449eda/scratchpad/tools}
cd "$(dirname "$0")"
echo "== python tests";  python -m pytest -q -p no:cacheprovider 2>&1 | tail -1
echo "== node tests";    (cd game && node --test --experimental-test-coverage 2>&1 | grep -E "^# (tests|pass|fail)|^# all files")
echo "== lint (eslint)"; "$TOOLS/node_modules/.bin/eslint" -c "$TOOLS/eslint.config.mjs" game/*.js 2>&1 | tail -3; echo "eslint exit ${PIPESTATUS[0]}"
echo "== lint (pyflakes)"; python -m pyflakes build.py test_powermap.py; echo "pyflakes exit $?"
echo "== types (tsc --checkJs)"; "$TOOLS/node_modules/.bin/tsc" --noEmit --allowJs --checkJs --target es2022 --module commonjs --moduleResolution node --resolveJsonModule --types node --typeRoots "$TOOLS/node_modules/@types" game/solver.js game/calibrate.js game/prefs.js 2>&1 | grep -c "error TS" | sed 's/^/tsc errors: /'
