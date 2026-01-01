#!/usr/bin/env bash
set -euo pipefail

# =========================
# Local Agent Runner (Codex)
# - PRD is source of truth
# - Python stack, pytest only
# - Enforces: read PRD -> plan -> implement -> pytest loop -> PRD Trace
# =========================

PRD_PATH="PRD/product_prd.md"

# Optional: ensure we're in a git repo (non-fatal)
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IN_GIT_REPO=true
else
  IN_GIT_REPO=false
fi

# 1) Ensure PRD exists
if [ ! -f "$PRD_PATH" ]; then
  echo "❌ PRD not found: $PRD_PATH"
  echo "   Expected path: $PRD_PATH"
  exit 1
fi

# 2) Optional: work on a new branch each run (safe default)
if [ "$IN_GIT_REPO" = true ]; then
  BRANCH="agent/$(date +%Y%m%d-%H%M%S)"
  # If already on a detached head or branch creation fails, continue anyway
  git checkout -b "$BRANCH" >/dev/null 2>&1 || true
  echo "🌿 Working on branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "$BRANCH")"
fi

# 3) Helpful preflight info (non-fatal)
echo "📄 PRD: $PRD_PATH"
echo "🧪 Test: pytest (configured by pytest.ini if present)"
[ -f "pytest.ini" ] && echo "✅ Found pytest.ini (project test conventions will apply)" || echo "⚠️  No pytest.ini found (recommended to add one)"

# 4) Run Codex with a strict, repeatable instruction set
PROMPT=$'你是本项目的本地开发代理（Python 项目）。必须严格遵守仓库根目录的 AGENTS.md。\nPRD 是唯一真相（source of truth）：PRD/product_prd.md\n\n【硬性流程（必须按顺序执行）】\n1) 打开并完整阅读 PRD/product_prd.md（不要跳过）。\n2) 输出三部分（必须引用 PRD 的 REQ 编号或小节标题）：\n   A. 需求清单与验收标准（按 REQ-XXX 逐条列出，含关键边界条件）\n   B. in-scope / out-of-scope（明确哪些做、哪些不做）\n   C. 实施计划（分步骤，每一步都引用对应的 REQ-XXX 或 PRD 小节）\n3) 开始修改代码实现 in-scope 的需求：\n   - 每完成一个小步（或每个 REQ），都运行：pytest\n     * pytest 的默认行为由 pytest.ini（如果存在）定义，必须遵守\n     * 不要随意追加 pytest 参数，除非明确需要定位问题（定位完成后回到 `pytest`）\n   - 如果 pytest 失败：分析失败原因 -> 修复 -> 再跑 pytest，直到通过\n   - 如果 PRD 的 REQ-XXX 没有可验证的测试：补 pytest 测试覆盖验收标准\n   - 测试命名建议：test_req_xxx_*，并在测试函数/注释里标注对应 REQ-XXX\n4) 遇到 PRD 含糊/矛盾/缺少关键数据：立刻提出具体问题并停止猜测实现\n5) 最终输出：PRD Trace（REQ-XXX -> 修改文件 -> pytest 测试函数名）+ 如何运行测试（pytest）\n\n【重要约束】\n- 任何实现决策必须可追溯到 PRD（REQ-XXX 或小节标题）。\n- PRD 与现有代码行为冲突时，以 PRD 为准。\n- 只使用 pytest 作为测试框架。\n'

# 非交互脚本化执行（推荐）
codex exec "$PROMPT"


echo "✅ Done. Review changes and run pytest locally if needed."
if [ "$IN_GIT_REPO" = true ]; then
  echo "🔎 Tip: use 'git status' and 'git diff' to review. Commit when satisfied."
fi
