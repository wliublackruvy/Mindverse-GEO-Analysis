#!/usr/bin/env bash
set -euo pipefail

# =========================
# GEO-Analyzer: Sync-Type Agent (Strict Exit)
# Acts as Source-of-Truth enforcer.
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
  info "Running structural audit..."
  python "$AUDIT_SCRIPT" >"$tmp" 2>&1 || true
  printf "%s" "$tmp"
}

# --- 核心：动态 Prompt 生成器 (修复版) ---
build_sync_prompt() {
  local json_input="$1"
  local mode="$2"

  python -c "
import json, sys

data = json.loads('''$json_input''')
missing = data.get('missing', [])
partial = data.get('partial', [])
covered = data.get('covered', [])
mode = '$mode'

print(f'''
You are the Lead Developer for GEO-Analyzer.
Current Mode: {mode}

SOURCE OF TRUTH: PRD/product_prd.md

STATUS:
- MISSING: {missing}
- PARTIAL: {partial}
- COVERED: {covered}

ANTI-LOOP RULES (CRITICAL):
1. DO NOT OUTPUT A PLAN.
2. DO NOT OUTPUT BULLET POINTS OF WHAT YOU \"WILL\" DO.
3. DO NOT SUMMARIZE.
4. ACTION ONLY.

INSTRUCTIONS:

IF MODE == \"IMPLEMENT\":
  - Fix MISSING/PARTIAL items immediately using \`exec bash -c 'cat <<EOF...'\`.

IF MODE == \"VERIFY\":
  - Your job is to READ the code (using \`cat\`) and CHECK if it matches PRD logic.
  - IF CODE IS WRONG: Output shell commands to fix it immediately.
  - IF CODE IS RIGHT: Output exactly the string \"NO_CHANGES_NEEDED\".

You must choose ONE path:
Path A: Write Code (if drift found)
Path B: Output \"NO_CHANGES_NEEDED\" (if synced)

If you verify and find no issues, you MUST say \"NO_CHANGES_NEEDED\" or the system will crash.

ACT NOW.
'''.strip())"
}

run_codex() {
  local prompt="$1"
  info "Thinking & Coding..."
  
  local output
  output=$(printf "%s" "$prompt" | codex exec \
    -m "$CODEX_MODEL" \
    --sandbox "$CODEX_SANDBOX" \
    -C "$(pwd)" \
    -)
  
  echo "$output"
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
  info "Branch: $(git rev-parse --abbrev-ref HEAD)"

  for ((i=1;i<=MAX_LOOPS;i++)); do
    info "=== Loop $i/$MAX_LOOPS ==="

    audit_tmp="$(run_audit)"
    cat "$audit_tmp"
    json="$(cat "$audit_tmp" | python "$PARSER_SCRIPT")"

    missing_cnt="$(python -c 'import json,sys; obj=json.loads(sys.argv[1]); print(len(obj["missing"]))' "$json")"
    partial_cnt="$(python -c 'import json,sys; obj=json.loads(sys.argv[1]); print(len(obj["partial"]))' "$json")"

    mode="VERIFY"
    if [[ "$missing_cnt" -gt 0 || "$partial_cnt" -gt 0 ]]; then
      mode="IMPLEMENT"
    fi
    
    info "Current Mode: $mode"

    prompt="$(build_sync_prompt "$json" "$mode")"
    output="$(run_codex "$prompt")"
    
    # Check for Sync Completion
    if [[ "$mode" == "VERIFY" ]] && echo "$output" | grep -q "NO_CHANGES_NEEDED"; then
      info "✅ SYSTEM SYNCED. All code matches PRD logic."
      info "Final sanity check..."
      pytest -q
      exit 0
    fi

    info "Verifying changes with pytest..."
    if ! pytest -q; then
      info "⚠️ Tests failed. Agent will retry in next loop to fix them."
    else
      info "Tests passed. (Agent did not exit, retrying verify loop...)"
    fi
    
  done

  die "MAX_LOOPS reached without full sync."
}

main "$@"
