import os  
from datetime import datetime
import json

def make_dump_file_id(original_project_dir, obf_project_dir):
    type_file_path = os.path.join(".", "type_info.json")
    mapping_file_path = os.path.join(".", "mapping_result.json")
    if not os.path.exists(type_file_path) or not os.path.exists(mapping_file_path):
        return
    
    # 식별자 타입 정보 저장
    with open(type_file_path, "r", encoding="utf-8") as f:
        type_info = json.load(f)

    # 매핑 정보 저장
    mapping_info = {}
    if os.path.exists(mapping_file_path):
        with open(mapping_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        for _, entries in data.items():
            if isinstance(entries, list):
                for entry in entries:
                    before = entry.get("target")
                    after = entry.get("replacement")
                    if before and after:
                        mapping_info[before] = after
    
    result = {}
    for category, targets in type_info.items():
        result[category] = {}
        for target in targets:
            replacement = mapping_info.get(target)
            if replacement:
                result[category][target] = replacement
    
    # 결과 파일들을 swingft_output 디렉토리에 저장
    output_dir = os.path.join(obf_project_dir, "swingft_output")
    os.makedirs(output_dir, exist_ok=True)
    dump_path = os.path.join(output_dir, "Swingft_ID_Obfuscation_Dump.json")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    json_data = {
        "original_file_path": original_project_dir,
        "obfuscated_file_path": obf_project_dir,
        "timestamp": timestamp,
        "identifier_obfuscation": result,
    }
    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)