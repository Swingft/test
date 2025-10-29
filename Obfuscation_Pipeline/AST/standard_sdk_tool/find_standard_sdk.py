import subprocess
import os
import json

P_SAME_NAME = set()

def run_command(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()

# import_list.txt 읽고 중복 제거
def read_import_list():
    import_list = set()
    path = os.path.join(".", "AST", "output", "import_list.txt")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f) or []
        import_list.update(data)
    import_list.add("Swift")
    import_list.add("Foundation")

    with open(path, "w", encoding="utf-8") as f:
        for i in import_list:
            f.write(f"{i}\n")
    
    return import_list

# api 경로 확인
def find_path():
    digester_cmd = ["xcrun", "--find", "swift-api-digester"]
    digester_path = run_command(digester_cmd)
    sdk_cmd = ["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]
    sdk_path = run_command(sdk_cmd)
    return digester_path, sdk_path

# sdk api - json 추출
def dump_to_json(digester_path, sdk_path, import_list):
    output_dir = "./AST/output/sdk-json/"

    for name in import_list:
        output_path = os.path.join(output_dir, f"{name}-sdk.json")
        cmd = [
            digester_path, 
            "-dump-sdk", 
            "-sdk", sdk_path, 
            "-target", "arm64-apple-ios16.0", 
            "-module", name,
            "-o", output_path
        ]
        result = run_command(cmd)

        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        root = data.get("ABIRoot", {})
        name = root.get("name", "")
        if name == "NO_MODULE":
            os.remove(output_path)

# 멤버 타입 추출
def get_type_name(node):
    for child in node.get("children", []):
        if child.get("kind") == "TypeNominal":
            return child.get("printedName")
    return None

# 멤버 정보 추출
def get_members(children):
    members = {}
    for child in children:
        if not isinstance(child, dict):
            continue
        
        kind = child.get("kind")
        decl_kind = child.get("declKind", kind)
        name = child.get("name")
        
        if decl_kind not in {"Var", "Func", "Constructor", "Subscript", 
                             "Enum", "EnumElement", "TypeAlias", "AssociatedType"}:
            continue

        P_SAME_NAME.add(name)

        member_info = {
            "kind": decl_kind,
            "type": child.get("printedName"),
            "usr": child.get("usr", None)
        }

        type_str = member_info["type"]
        if type_str and "(" in type_str and ")" in type_str:
            param_str = type_str[type_str.find("(")+1:type_str.rfind(")")]
            for param in param_str.split(":"):
                param = param.strip()
                if param and param != "_":
                    P_SAME_NAME.add(param)

        members[name] = member_info
    return members

def parse_type(child, sdk_info):
    if not isinstance(child, dict):
        return 
    
    kind = child.get("kind")
    decl_kind = child.get("declKind", kind) 

    if kind != "TypeDecl":
        return
    
    if decl_kind in ["Class", "Struct", "Protocol", "Enum"]:
        P_SAME_NAME.add(child.get("name"))

    name = child.get("name")
    info = {
        "kind": decl_kind,
        "module": child.get("moduleName"),
        "usr": child.get("usr"),
        "members": get_members(child.get("children", []))
    }
    sdk_info[name] = info

    for c in child.get("children") or []:
        parse_type(c, sdk_info)

# sdk api의 타입 및 멤버 정보 추출
def sdk_dump_parser(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sdk_info = {}

    if not isinstance(data, dict):
        return {}
    abi_root = data.get("ABIRoot", {})
    children = abi_root.get("children") or []

    for child in children:
        if isinstance(child, dict):
            parse_type(child, sdk_info)
    
    return sdk_info

# 재 export 모듈 파악
def import_info_parser(path):
    re_import_list = set()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    abi_root = data.get("ABIRoot", {})
    children = abi_root.get("children") or []
    root_name = abi_root.get("name") or ""
    for child in children:
        if not isinstance(child, dict):
            continue
        if child.get("kind") == "Import":
            name = child.get("name") or ""
            if (root_name and name.startswith(f"{root_name}.")) or name.startswith("_"):
                continue
            if name:
                re_import_list.add(name)

    return re_import_list

def find_standard_sdk():
    digester_path, sdk_path = find_path()
    import_list = read_import_list()

    output_dir = os.path.join('.', "AST", "output", "sdk-json")
    dump_to_json(digester_path, sdk_path, import_list)
    
    re_import_list = set()
    for fileName in os.listdir(output_dir):
        file_path = os.path.join(output_dir, fileName)
        re_import_list.update(import_info_parser(file_path))

    re_import_list = list(set(re_import_list) - set(import_list))
    dump_to_json(digester_path, sdk_path, re_import_list)

    for fileName in os.listdir(output_dir):
        file_path = os.path.join(output_dir, fileName)
        
        sdk_info = sdk_dump_parser(file_path)

        if not sdk_info:
            os.remove(file_path)
        else:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(sdk_info, f, indent=2, ensure_ascii=False)
    
    return P_SAME_NAME