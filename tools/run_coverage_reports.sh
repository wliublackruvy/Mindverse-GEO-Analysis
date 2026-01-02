#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

run_with_marker() {
  local marker="$1"
  local xml_report="$2"
  local coverage_file="$3"
  echo "=== Running ${marker} tests with coverage (report: ${xml_report})"
  COVERAGE_FILE="${coverage_file}" pytest -m "${marker}" --cov-report=term-missing --cov-report="xml:${xml_report}"
}

run_with_marker "unit" "coverage-unit.xml" ".coverage.unit"
run_with_marker "integration" "coverage-integration.xml" ".coverage.integration"
