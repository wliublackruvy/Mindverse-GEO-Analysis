import json
import sys

covered = []
partial = []
missing = []
current_list = None

try:
    lines = sys.stdin.readlines()
except Exception:
    lines = []

for line in lines:
    line = line.strip()
    if not line: continue

    if "[COVERED]" in line:
        current_list = covered
    elif "[PARTIAL]" in line:
        current_list = partial
    elif "[MISSING]" in line:
        current_list = missing
    elif line.startswith("-") and current_list is not None:
        parts = line.split()
        if len(parts) >= 2:
            rid = parts[1].strip(":,")
            current_list.append(rid)

print(json.dumps({"covered": covered, "partial": partial, "missing": missing}))
