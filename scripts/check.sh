#!/usr/bin/env bash
# Run the same checks as CI (except the Docker job) from the repository root.
#   TEST_DATABASE_URL=... ./scripts/check.sh            # backend + frontend
#   TEST_DATABASE_URL=... E2E_DATABASE_URL=... ./scripts/check.sh --e2e
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
step() { printf '\n== %s\n' "$*"; }

cd "$root/backend"
step "backend: lint, format, types";  uv run ruff check . && uv run ruff format --check . && uv run mypy
step "backend: tests";                REQUIRE_DB_TESTS=1 uv run pytest -q
step "evaluation (tool mode)";        uv run python -m evals.run --mode tools > /dev/null && echo "all cases passed"
step "API contract is current"
uv run python -m app.openapi_export ../frontend/src/lib/api/openapi.json
cd "$root/frontend"
npm run --silent gen:api > /dev/null
git -C "$root" diff --exit-code -- frontend/src/lib/api/ \
  || { echo "The API contract changed: commit frontend/src/lib/api/*"; exit 1; }

step "frontend: lint, types, tests";  npm run --silent lint && npm run --silent typecheck && npm test --silent
step "frontend: production build";    npm run --silent build > /dev/null && echo "build ok"

if [ "${1:-}" = "--e2e" ]; then
  step "end-to-end";                  npx playwright test
fi
printf '\nAll checks passed.\n'
