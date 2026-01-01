import json
import sys

# 初始化列表
covered = []
partial = []
missing = []
current_list = None

# 从标准输入读取所有行
try:
    lines = sys.stdin.readlines()
except Exception:
    lines = []

# 解析逻辑
for line in lines:
    line = line.strip()
    if not line:
        continue

    # 简单的字符串匹配
    if "[COVERED]" in line:
        current_list = covered
    elif "[PARTIAL]" in line:
        current_list = partial
    elif "[MISSING]" in line:
        current_list = missing
    elif line.startswith("-") and current_list is not None:
        # 提取 ID (例如 "- F-06")
        parts = line.split()
        if len(parts) >= 2:
            rid = parts[1].strip(":,")
            current_list.append(rid)

# 构建结果字典
result = {
    "covered": covered,
    "partial": partial,
    "missing": missing
}

# 输出 JSON
print(json.dumps(result))
