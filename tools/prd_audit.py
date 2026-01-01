#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Iterable

PRD_PATH = Path("PRD/product_prd.md")
SRC_DIR = Path("src")
TEST_DIR = Path("tests")

# Scan file types: backend + frontend
SRC_EXTS: Set[str] = {".py", ".js", ".html", ".css"}
TEST_EXTS: Set[str] = {".py"}

# ==========
# PRD parsing
# ==========
REQ_ID_RE = re.compile(r"\b((?:F|E)-\d{2}|Analytics)\b")

# PRD tag evidence: supports Python/JS comments and HTML comments.
# Examples:
#   # PRD: F-01
#   // PRD: F-06
#   <!-- PRD: F-06 -->
PRD_TAG_RE = re.compile(r"\bPRD[:\s]+((?:F|E)-\d{2}|Analytics)\b", re.IGNORECASE)

# ==========
# Evidence heuristics (implementation / UI)
# ==========
# NOTE: these are "weak semantic" keywords to detect implementation/UI traces.
IMPL_KEYWORDS: Dict[str, List[str]] = {
    "F-01": ["DiagnosisRequest", "industry", "work_email", "ValidationError"],
    "F-02": ["Simulation", "iteration", "SOV", "recommendation", "engine"],
    "F-03": ["ProcessLogger", "log(", "entries"],
    "F-04": ["ConversionCard", "CTA"],
    "F-05": ["AdviceItem", "建议"],
    "F-06": ["task_id", "platform", "coverage", "cache", "desensitize"],
    "E-01": ["fallback", "estimation", "retry"],
    "E-02": ["SensitiveContentError", "敏感"],
    "Analytics": ["AnalyticsTracker", "track", "event"],
}

# Frontend UI coverage keywords: copy / elements / API field names.
UI_KEYWORDS: Dict[str, List[str]] = {
    "F-01": [
        "该行业平均 AI 推荐率",
        "industryBenchmarks",
        "benchmark",
    ],
    "F-03": [
        "log-window",
        "progress",
        "snapshot",
        "console",
        "[system]",
        "[analysis]",
    ],
    "F-04": [
        "红色警报",
        "橙色机会",
        "蓝色护航",
        "联系铭予",
        "cta",
    ],
    "F-06": [
        "诊断结果来自豆包 & deepseek",
        "脱敏处理",
        "来自缓存",
        "based on industry estimation",
        "coverage",
        "task_id",
    ],
    "Analytics": [
        "funnel",
        "industry",
        "report",
        "analytics",
    ],
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def iter_files(root: Path, exts: Set[str]) -> Iterable[Path]:
    if not root.exists():
        return []
    return (p for p in root.rglob("*") if p.is_file() and p.suffix in exts)


def read_prd_ids() -> Set[str]:
    if not PRD_PATH.exists():
        print(f"❌ PRD not found: {PRD_PATH}", file=sys.stderr)
        sys.exit(2)

    text = read_text(PRD_PATH)
    return set(REQ_ID_RE.findall(text))


def scan_files_for_any(root: Path, exts: Set[str], keywords: List[str]) -> bool:
    """Hit any keyword => evidence (good for UI copy)."""
    if not keywords:
        return False
    kws = [k.lower() for k in keywords]

    for path in iter_files(root, exts):
        content = read_text(path).lower()
        if any(kw in content for kw in kws):
            return True
    return False


def scan_files_for_first(root: Path, exts: Set[str], keywords: List[str]) -> bool:
    """Conservative: must hit the first keyword (good for backend shape detection)."""
    if not keywords:
        return False
    first = keywords[0].lower()

    for path in iter_files(root, exts):
        content = read_text(path).lower()
        if first in content:
            return True
    return False


def has_prd_tag(root: Path, exts: Set[str], req_id: str) -> bool:
    """
    Strong evidence: PRD tags.
    We extract ALL PRD tags in a file and check if req_id is explicitly tagged.
    This avoids false positives like: file contains "PRD: F-01" and also mentions "F-06" elsewhere.
    """
    rid = req_id.lower()
    for path in iter_files(root, exts):
        content = read_text(path)
        tags = {m.group(1).lower() for m in PRD_TAG_RE.finditer(content)}
        if rid in tags:
            return True
    return False


def audit() -> Dict[str, List[str]]:
    prd_ids = sorted(read_prd_ids())

    covered: List[str] = []
    partial: List[str] = []
    missing: List[str] = []

    for rid in prd_ids:
        # Strong evidence
        src_tag_hit = has_prd_tag(SRC_DIR, SRC_EXTS, rid)
        test_tag_hit = has_prd_tag(TEST_DIR, TEST_EXTS, rid)  # pytest evidence

        # Weak evidence (implementation / UI)
        impl_hit = scan_files_for_first(SRC_DIR, SRC_EXTS, IMPL_KEYWORDS.get(rid, []))
        ui_hit = scan_files_for_any(
            SRC_DIR, {".js", ".html", ".css"}, UI_KEYWORDS.get(rid, [])
        )

        # Rating rules:
        # - COVERED: has pytest evidence (tag in tests)
        # - PARTIAL: any implementation/UI trace OR PRD tag in src
        # - MISSING: none
        if test_tag_hit:
            covered.append(rid)
        elif impl_hit or ui_hit or src_tag_hit:
            partial.append(rid)
        else:
            missing.append(rid)

    return {"COVERED": covered, "PARTIAL": partial, "MISSING": missing, "ALL": prd_ids}


def print_report(result: Dict[str, List[str]]) -> None:
    print("=== PRD Coverage Audit ===")
    print(f"PRD: {PRD_PATH}  (requirements found: {len(result['ALL'])})\n")

    for section in ("COVERED", "PARTIAL", "MISSING"):
        items = result[section]
        print(f"[{section}] ({len(items)})")
        for rid in items:
            print(f"- {rid}")
        print("")


def main() -> None:
    result = audit()
    print_report(result)

    # Exit 1 if anything remains PARTIAL/MISSING (for agent.sh loops)
    if result["PARTIAL"] or result["MISSING"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
