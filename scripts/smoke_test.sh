#!/usr/bin/env bash
# Smoke-test a running deployment through its public URL.
#   ./scripts/smoke_test.sh https://analyst.example.com
# Creates a throwaway account (smoke-<timestamp>@example.com), uploads the sample dataset, and,
# if analysis is enabled, asks one question and waits for the answer. Needs curl and Python 3.
set -euo pipefail

base="${1:?usage: smoke_test.sh <base-url>}"
base="${base%/}"
here="$(cd "$(dirname "$0")/.." && pwd)"
sample="$here/data/samples/sales.csv"
# Git Bash on Windows: native curl needs a Windows-style path.
command -v cygpath > /dev/null && sample="$(cygpath -m "$sample")"
jar="$(mktemp)"
trap 'rm -f "$jar"' EXIT
hdr=(-H 'X-Requested-With: fetch' -H "Origin: $base")
# python3 may be a non-working stub on some systems (e.g. the Windows Store alias).
py=python3
"$py" -c '' 2>/dev/null || py=python
json() { "$py" -c "import json,sys; print(json.load(sys.stdin)$1)"; }

echo "1. sign-in page";   curl -fsS "$base/login" > /dev/null
echo "2. readiness";      curl -fsS "$base/api/health/ready" | json "['status']"
email="smoke-$(date +%s)@example.com"
echo "3. register $email"
curl -fsS -c "$jar" "${hdr[@]}" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$email\",\"password\":\"smoke-test-$(date +%s)\"}" "$base/api/auth/register" > /dev/null
echo "4. upload sample"
dataset=$(curl -fsS -b "$jar" "${hdr[@]}" -F "file=@$sample" "$base/api/datasets")
echo "$dataset" | json "['row_count']"
dataset_id=$(echo "$dataset" | json "['id']")

enabled=$(curl -fsS -b "$jar" "$base/api/config" | json "['analysis_enabled']")
if [ "$enabled" != "True" ]; then
  echo "5. analysis is disabled on this server (no API key); skipping the question"
  exit 0
fi
echo "5. ask a question"
conversation=$(curl -fsS -b "$jar" "${hdr[@]}" -H 'Content-Type: application/json' \
  -d "{\"dataset_id\":\"$dataset_id\"}" "$base/api/conversations" | json "['id']")
run=$(curl -fsS -b "$jar" "${hdr[@]}" -H 'Content-Type: application/json' \
  -d '{"question":"Why did revenue decrease in Q3?"}' \
  "$base/api/conversations/$conversation/analyses" | json "['id']")
for _ in $(seq 1 120); do
  status=$(curl -fsS -b "$jar" "$base/api/analyses/$run" | json "['status']")
  case "$status" in completed|failed|cancelled) break ;; esac
  sleep 2
done
echo "   status: $status"
curl -fsS -b "$jar" "$base/api/analyses/$run" | json "['answer_summary']"
test "$status" = "completed"
echo "smoke test passed"
