import os
import json

large_identifiers = []
small_identifiers = []

def read_identifier_list():
    global large_identifiers, small_identifiers
    id_path = os.path.join(".", "DeadCode", "identifiers.txt")
    mapping_path = "mapping_result.json"
    used_id = []

    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for _, items in data.items():
            for item in items:
                if item is None:
                    continue

                before = item.get("target")
                after = item.get("replacement")
                if before:
                    used_id.append(before)
                if after:
                    used_id.append(after)

    if os.path.exists(id_path):
        with open(id_path, "r", encoding="utf-8") as f:
            for line in f:
                item = line
                if not isinstance(item, str):
                    continue
                s = item.strip()
                if not s:
                    continue
                if len(s) < 5 or "_" in s or s in used_id:
                    continue
                first_char = s[0] if s else ""
                if first_char.isupper():
                    large_identifiers.append(s)
                else:
                    small_identifiers.append(s)