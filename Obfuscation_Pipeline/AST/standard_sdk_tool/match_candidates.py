import json
import os

MATCHED_LIST = []
SDK_SIGNATURE = {}

# SDK 요소 MATCHED_LIST에 추가
def in_matched_list(node):
    if node not in MATCHED_LIST:
        MATCHED_LIST.append(node)

# enum case 제외
def repeat_extension_enum(in_node):
    node = in_node.get("node")
    if not node:
        node = in_node
    members = node.get("G_members", [])
    for member in members:
        if member.get("B_kind") == "case":
            in_matched_list(member)
    extensions = in_node.get("extension", [])
    for extension in extensions:
        repeat_extension_enum(extension)

# "Decodable", "Encodable", "Codable", "NSCoding", "NSSecureCoding"의 멤버변수 제외
def add_var_member(node):
    members = node.get("G_members", []) if node else []
    for member in members:
        in_matched_list(member)

def match_member(node, sdk_node):
    members = node.get("G_members", [])
    sdk_members = sdk_node.get("members", {})

    for member in members:
        name = member.get("A_name")
        name = name.split(".")[-1]
        kind = member.get("B_kind")
        
        if kind in ["struct", "protocol", "class", "enum"]:
            match_sdk_name(member)
            continue
 
        name = member.get("A_name")
        name = name.split(".")[-1]
        if name in sdk_members:
            sdk_member = sdk_members[name]
            sdk_kind = sdk_member.get("kind", "").lower()
            if sdk_kind == "var":
                sdk_kind = "variable"
            elif sdk_kind == "enumelement":
                sdk_kind = "case"
            elif sdk_kind == "func":
                sdk_kind = "function"

            if kind == sdk_kind:  
                in_matched_list(member)
                if kind == "function":
                    match_member(member, sdk_member)

# 자식 노드가 자식 노드를 가지는 경우
def repeat_match_member(in_node, sdk_sig):
    if in_node is None: 
        return
    node = in_node.get("node", in_node)
    extensions = in_node.get("extension", [])
    children = in_node.get("children", [])

    match_member(node, sdk_sig)
    for extension in extensions:
        repeat_match_member(extension, sdk_sig)
    for child in children:
        repeat_match_member(child, sdk_sig)

# extension 이름 확인
def repeat_extension(in_node, name):
    node = in_node.get("node")
    if not node:
        node = in_node
    c_name = node.get("A_name")
    c_name = c_name.split(".")[-1]
    if c_name == name:
        in_matched_list(node)
        extensions = in_node.get("extension", [])
        for extension in extensions:
            repeat_extension(extension, name)

# SDK 요소 식별
def match_sdk_name(data):
    if isinstance(data, list):
        for item in data:
            match_sdk_name(item)
    elif isinstance(data, dict):
        node = data.get("node")
        if node:
            extensions = data.get("extension", [])
            children = data.get("children", [])
        else:
            node = data
            extensions = []
            children = []
        
        name = node.get("A_name")
        name = name.split(".")[-1]
       
        # extention x {}
        if name in SDK_SIGNATURE and node.get("B_kind") == "extension":
            sdk_list = SDK_SIGNATURE[name]
            if isinstance(sdk_list, list):
                for sdk in sdk_list:
                    repeat_match_member(data, sdk)
            else:
                repeat_match_member(data, sdk_list)
            repeat_extension(data, name)
        
        adopted = node.get("E_adoptedClassProtocols", [])
        if "Codable" in adopted:
            if "Decodable" not in adopted:
                adopted.append("Decodable")
            if "Encodable" not in adopted:
                adopted.append("Encodable")
            
        for ad in adopted:
            if ad in SDK_SIGNATURE:
                if node.get("B_kind") == "enum":
                    if ad in ["String", "Int", "UInt", "Double", "Float", "Character", "CaseIterable", "Decodable", "Encodable", "Codable", "NSCoding", "NSSecureCoding"]:
                        repeat_extension_enum(data)
                if ad in ["Decodable", "Encodable", "NSCoding", "NSSecureCoding"]:
                    add_var_member(node)
                    for extension in extensions:
                        add_var_member(extension)
                    for child in children:
                        add_var_member(child)
                if ad  == "UIViewController" or ad == "UITableViewController":
                    in_matched_list(node)
                
                if "UI" in ad and ("View" in ad or "Controller" in ad):
                    in_matched_list(node)
                    
                sdk_list = SDK_SIGNATURE[ad]
                if isinstance(sdk_list, list):
                    for sdk in sdk_list:
                        repeat_match_member(data, sdk)
                else:
                    repeat_match_member(data, sdk_list)

# SDK 노드 정보 추출 및 결과 저장
def match_and_save(candidate_path, sdk_file_path):
    if os.path.exists(candidate_path):
        with open(candidate_path, "r", encoding="utf-8") as f:
            candidates = json.load(f)

        for file in os.listdir(sdk_file_path):
            file_path = os.path.join(sdk_file_path, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for name, info in data.items():
                    if name not in SDK_SIGNATURE:
                        SDK_SIGNATURE[name] = []
                    SDK_SIGNATURE[name].append(info)
            except Exception as e:
                print(e)

        match_sdk_name(candidates)
        matched_output_path = "./AST/output/standard_list.json"
        with open(matched_output_path, "w", encoding="utf-8") as f:
            json.dump(MATCHED_LIST, f, indent=2, ensure_ascii=False)


def match_candidates_sdk():
    candidate_path = "./AST/output/external_candidates.json"
    sdk_file_path = "./AST/output/sdk-json/"

    match_and_save(candidate_path, sdk_file_path)
