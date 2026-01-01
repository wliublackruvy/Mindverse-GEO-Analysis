#!/usr/bin/env bash
set -euo pipefail

# =========================
# PRD-first local agent (FINAL - EXECUTION MODE)
# =========================

PRD_PATH="PRD/product_prd.md"
AGENTS_PATH="AGENTS.md"
AUDIT_SCRIPT="tools/prd_audit.py"
PARSER_SCRIPT="tools/audit_to_json.py"

CODEX_MODEL="${CODEX_MODEL:-gpt-5-codex}"
CODEX_SANDBOX="${CODEX_SANDBOX:-workspace-write}"
MAX_LOOPS="${MAX_LOOPS:-30}"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "INFO: $*" >&2; }

need() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }

self_check() {
  if LC_ALL=C grep -n $'\xEF\xBF\xBD' "$0" >/dev/null 2>&1; then
    die "agent.sh contains Unicode replacement character. Recreate via cat <<'EOF'."
  fi
}

run_audit() {
  local tmp
  tmp="$(mktemp -t prd_audit.XXXXXX)"
  info "Audit tmpfile: $tmp"
  python "$AUDIT_SCRIPT" >"$tmp" 2>&1 || true
  printf "%s" "$tmp"
}

build_prompt_from_json() {
  python - <<'PY'
import json, sys
try:
    data = json.loads(sys.stdin.read())
except json.JSONDecodeError:
    data = {"missing": [], "partial": []}

missing = data.get("missing", [])

print(f"""
You are the local dev agent.
Current status: {len(missing)} MISSING items: {missing}.

FATAL ERROR IN PREVIOUS TURN: You generated a plan but DID NOT write any code.
DO NOT GENERATE A PLAN.
DO NOT SUMMARIZE.
IMMEDIATELY GENERATE SHELL COMMANDS TO CREATE FILES.

YOUR TASK: Implement F-06 (Real Data) and E-01 (Fallback) NOW.

REQUIRED OPERATIONS (Perform these using `cat <<EOF` or `sed`):
1. CREATE `src/geo_analyzer/llm.py`:
   - Must contain `SecretsManager`, `TokenBucket`, `DoubaoClient`, `DeepSeekClient`.
   - Must handle `POST /v1/chat/completions`.
2. UPDATE `src/geo_analyzer/models.py`:
   - Add `coverage` and `cache_note` fields to `SimulationMetrics`.
3. UPDATE `src/geo_analyzer/engine.py`:
   - Integrate `LLMOrchestrator`.
   - Implement the 3-strike fallback logic (E-01).
4. CREATE `tests/test_f06_llm.py`:
   - Add `# PRD: F-06` tag.
   - Test the clients and fallback logic.

EXAMPLE OF WHAT YOU MUST DO RIGHT NOW:
exec bash -c 'cat <<EOF > src/geo_analyzer/llm.py
import os
... code ...
EOF'

START WRITING FILES NOW.
""".strip())
PY
}

run_codex() {
  local prompt="$1"
  info "Running codex exec"
  printf "%s" "$prompt" | codex exec \
    -m "$CODEX_MODEL" \
    --sandbox "$CODEX_SANDBOX" \
    -C "$(pwd)" \
    -
}

main() {
  self_check
  need git
  need python
  need codex

  [[ -f "$PRD_PATH" ]] || die "Missing PRD: $PRD_PATH"
  [[ -f "$AGENTS_PATH" ]] || die "Missing AGENTS.md: $AGENTS_PATH"
  [[ -f "$AUDIT_SCRIPT" ]] || die "Missing audit script: $AUDIT_SCRIPT"
  [[ -f "$PARSER_SCRIPT" ]] || die "Missing parser script: $PARSER_SCRIPT"

  info "PRD: $PRD_PATH"
  info "Workdir: $(pwd)"
  info "Branch: $(git rev-parse --abbrev-ref HEAD)"

  for ((i=1;i<=MAX_LOOPS;i++)); do
    info "Loop $i/$MAX_LOOPS - audit"

    audit_tmp="$(run_audit)"
    cat "$audit_tmp"

    json="$(cat "$audit_tmp" | python "$PARSER_SCRIPT")"
    info "Parsed JSON: $json"

    missing_cnt="$(python -c 'import json,sys; obj=json.loads(sys.argv[1]); print(len(obj["missing"]))' "$json")"
    partial_cnt="$(python -c 'import json,sys; obj=json.loads(sys.argv[1]); print(len(obj["partial"]))' "$json")"

    if [[ "$missing_cnt" -eq 0 && "$partial_cnt" -eq 0 ]]; then
      info "Audit clean. Running pytest -q"
      pytest -q
      info "DONE"
      exit 0
    fi

    prompt="$(printf "%s" "$json" | build_prompt_from_json)"
    run_codex "$prompt"

    info "Running pytest -q"
    pytest -q
  done

  die "MAX_LOOPS reached"
}

main "$@"
