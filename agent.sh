#!/usr/bin/env bash
set -euo pipefail

# PRD-first agent (ASCII-only)
PRD_PATH="PRD/product_prd.md"
AGENTS_PATH="AGENTS.md"
AUDIT_SCRIPT="tools/prd_audit.py"

CODEX_MODEL="${CODEX_MODEL:-gpt-5-codex}"
CODEX_SANDBOX="${CODEX_SANDBOX:-workspace-write}"
MAX_LOOPS="${MAX_LOOPS:-30}"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "INFO: $*"; }

need() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }

self_check() {
  # Fail if file contains Unicode replacement character (EF BF BD)
  if LC_ALL=C grep -n $'\xEF\xBF\xBD' "$0" >/dev/null 2>&1; then
    die "agent.sh contains Unicode replacement character. Recreate with: cat <<'EOF' > agent.sh"
  fi
}

# Run audit and preserve exit code.
# Prints audit output to stdout, and returns audit exit code.
run_audit() {
  set +e
  local out
  out="$(python "$AUDIT_SCRIPT" 2>&1)"
  local rc=$?
  set -e
  printf "%s\n" "$out"
  return $rc
}

build_prompt() {
  local audit_text="$1"
  local loop_id="$2"

  python - <<PY
prd_path = "${PRD_PATH}"
audit_text = """${audit_text}""".strip()
loop_id = "${loop_id}"

print(f"""You are a local dev agent for this Python repo. You MUST follow AGENTS.md in the repo root.
The ONLY source of truth is PRD: {prd_path}

MODE:
- Ignore PRD diff entirely.
- Always read the PRD fully each run.
- If ANY requirement is PARTIAL or MISSING, implement it and add pytest evidence.
- Frontend files under src/geo_analyzer/frontend count as implementation, BUT you still MUST add pytest evidence (API/engine fields/tests asserting UI copy/etc).
- Add explicit PRD tags in code/tests: '# PRD: F-06', '# PRD: E-01', '# PRD: Analytics' (and so on).

HARD PROCESS (in order):
1) Open and fully read PRD/product_prd.md (do not skip).
2) Output three parts (reference ONLY real IDs in PRD: F-01..F-06, E-01..E-02, Analytics):
   A) requirements + acceptance criteria (include key boundaries)
   B) in-scope / out-of-scope
   C) step-by-step plan referencing PRD IDs
3) Implement in-scope items:
   - after each small step run: pytest -q
   - if pytest fails: fix and rerun until passing
   - if a PRD item has no test evidence: add pytest tests
4) Final output: PRD Trace (ID -> changed files -> pytest test function names) + how to run tests (pytest -q)

IMPORTANT:
- You MUST make real changes in src/ and/or tests/ (and frontend is allowed but still needs pytest evidence).
- Avoid unrelated refactors or feature expansions.
- If PRD is ambiguous or missing key data: ask specific questions and STOP (do not guess).

AUDIT OUTPUT (input):
{audit_text}

Loop marker: {loop_id}
""")
PY
}

run_codex() {
  local prompt="$1"
  # COMMAND must be one argument. The agent will still execute its own commands.
  codex exec \
    -m "$CODEX_MODEL" \
    --sandbox "$CODEX_SANDBOX" \
    -C "$(pwd)" \
    "$prompt" \
    "bash -lc true"
}

has_code_changes() {
  # Require real changes in src/ or tests/ (frontend counts because it's under src/)
  local changed
  changed="$(git diff --name-only)"
  if echo "$changed" | grep -Eq '^(src/|tests/)'; then
    return 0
  fi
  return 1
}

main() {
  self_check
  need git
  need python
  need codex

  [[ -f "$PRD_PATH" ]] || die "Missing PRD: $PRD_PATH"
  [[ -f "$AGENTS_PATH" ]] || die "Missing AGENTS.md"
  [[ -f "$AUDIT_SCRIPT" ]] || die "Missing audit script: $AUDIT_SCRIPT"
  [[ -f pytest.ini ]] || info "pytest.ini not found (ok if project does not use it)"

  info "PRD: $PRD_PATH"
  info "Workdir: $(pwd)"
  info "Branch: $(git rev-parse --abbrev-ref HEAD)"

  for ((i=1;i<=MAX_LOOPS;i++)); do
    info "Loop $i/$MAX_LOOPS - audit"
    audit_text="$(run_audit)"
    audit_rc=$?
    echo "$audit_text"

    if [[ $audit_rc -eq 0 ]]; then
      info "Audit clean. Running pytest -q"
      pytest -q
      info "DONE: audit clean and tests passing"
      exit 0
    fi

    # Not clean -> run codex to implement missing/partial
    prompt="$(build_prompt "$audit_text" "$i")"
    run_codex "$prompt"

    info "Running pytest -q"
    pytest -q

    # Enforce real code/test/frontend change
    if ! has_code_changes; then
      info "No src/tests changes detected after codex run. Strengthening and retrying same loop..."
      # Add a harder instruction by re-running codex once immediately.
      prompt="$(build_prompt "$audit_text" "${i}-retry")"
      run_codex "$prompt"
      info "Running pytest -q (after retry)"
      pytest -q
    fi
  done

  die "MAX_LOOPS reached without clean audit"
}

main "$@"
