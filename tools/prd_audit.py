#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set

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

# PRD tag evidence: Python/JS/HTML comments
#   # PRD: F-01
#   // PRD: F-06
#   <!-- PRD: F-06 -->
PRD_TAG_RE = re.compile(r"PRD[:\s]+((?:F|E)-\d{2}|Analytics)\b", re.IGNORECASE)

# ==========
# Weak heuristics (implementation / UI presence)
# ==========
IMPL_KEYWORDS: Dict[str, List[str]] = {
    "F-01": ["DiagnosisRequest", "industry", "work_email", "ValidationError"],
    "F-02": ["GeoSimulationEngine", "SOV", "recommendation", "simulation"],
    "F-03": ["ProcessLogger", "log(", "entries"],
    "F-04": ["ConversionCard", "CTA"],
    "F-05": ["AdviceItem", "建议"],
    "F-06": ["task_id", "platform", "coverage", "cache", "desensitize"],
    "E-01": ["fallback", "estimation", "retry"],
    "E-02": ["SensitiveContentError", "敏感"],
    "Analytics": ["AnalyticsTracker", "track", "event"],
}

UI_KEYWORDS: Dict[str, List[str]] = {
    "F-01": ["该行业平均 AI 推荐率", "industryBenchmarks", "benchmark"],
    "F-03": ["log-window", "progress", "snapshot", "[System]", "[Analysis]"],
    "F-04": ["红色警报", "橙色机会", "蓝色护航", "联系铭予", "CTA"],
    "F-06": [
        "诊断结果来自豆包 & DeepSeek",
        "脱敏处理",
        "来自缓存",
        "Based on Industry Estimation",
        "coverage",
        "task_id",
    ],
    "Analytics": ["Funnel", "Industry", "Report", "analytics"],
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


def read_prd_ids() -> List[str]:
    if not PRD_PATH.exists():
        print(f"❌ PRD not found: {PRD_PATH}", file=sys.stderr)
        sys.exit(2)
    text = read_text(PRD_PATH)
    ids = sorted(set(REQ_ID_RE.findall(text)))
    return ids


def file_has_prd_tag_for_id(path: Path, rid: str) -> bool:
    content = read_text(path)
    if not content:
        return False
    for m in PRD_TAG_RE.finditer(content):
        if m.group(1).lower() == rid.lower():
            return True
    return False


def has_prd_tag(root: Path, exts: Set[str], rid: str) -> bool:
    for path in iter_files(root, exts):
        if file_has_prd_tag_for_id(path, rid):
            return True
    return False


def scan_any_keyword(root: Path, exts: Set[str], keywords: List[str]) -> bool:
    if not keywords:
        return False
    kws = [k.lower() for k in keywords]
    for path in iter_files(root, exts):
        content = read_text(path).lower()
        if any(kw in content for kw in kws):
            return True
    return False


def scan_first_keyword(root: Path, exts: Set[str], keywords: List[str]) -> bool:
    if not keywords:
        return False
    first = keywords[0].lower()
    for path in iter_files(root, exts):
        content = read_text(path).lower()
        if first in content:
            return True
    return False


def audit() -> Dict[str, List[str]]:
    prd_ids = read_prd_ids()

    covered: List[str] = []
    partial: List[str] = []
    missing: List[str] = []

    for rid in prd_ids:
        # Strong evidence: tests contain explicit PRD tag for this rid
        test_tag_hit = has_prd_tag(TEST_DIR, TEST_EXTS, rid)

        # Implementation evidence: any PRD tag in src OR backend-ish keyword hits
        src_tag_hit = has_prd_tag(SRC_DIR, SRC_EXTS, rid)
        impl_hit = scan_first_keyword(SRC_DIR, SRC_EXTS, IMPL_KEYWORDS.get(rid, []))

        # UI evidence: frontend presence counts as implementation
        ui_hit = scan_any_keyword(SRC_DIR, {".js", ".html", ".css"}, UI_KEYWORDS.get(rid, []))

        # Rating:
        # - COVERED: pytest evidence via explicit PRD tag in tests
        # - PARTIAL: has any implementation/ui/tag evidence but no test tag yet
        # - MISSING: nothing
        if test_tag_hit:
            covered.append(rid)
        elif src_tag_hit or impl_hit or ui_hit:
            partial.append(rid)
        else:
            missing.append(rid)

    return {"ALL": prd_ids, "COVERED": covered, "PARTIAL": partial, "MISSING": missing}


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

    # If anything is PARTIAL or MISSING, fail the audit (agent should continue).
    if result["PARTIAL"] or result["MISSING"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
