import json
import re
import os

VISITED_NODE = set()
MATCHED_LIST = []
STORYBOARD_AND_XC_WRAP_NAME = []

# 제외 대상 MATCHED_LIST에 추가
def in_matched_list(node):
    if node not in MATCHED_LIST:
        MATCHED_LIST.append(node)

# 스토리보드, xcassets
def get_storyboard_and_xc_wrapper_info():
    storyboard_path = os.path.join(".", "AST", "output", "storyboard_list.txt")
    if os.path.exists(storyboard_path):
        with open(storyboard_path, "r", encoding="utf-8") as f:
            for name in f:
                name = name.strip()
                if name:
                    STORYBOARD_AND_XC_WRAP_NAME.append(name)

    xc_path = os.path.join(".", "AST", "output", "xc_list.txt")
    if os.path.exists(xc_path):
        with open(xc_path, "r", encoding="utf-8") as f:
            for name in f:
                name = name.strip()
                if name:
                    STORYBOARD_AND_XC_WRAP_NAME.append(name)
    
    wrapper_path = os.path.join(".", "AST", "output", "wrapper_list.txt")
    if os.path.exists(wrapper_path):
        with open(wrapper_path, "r", encoding="utf-8") as f:
            for name in f:
                name = name.strip()
                if name:
                    STORYBOARD_AND_XC_WRAP_NAME.append(name)
    
    keyword_path = os.path.join(".", "AST", "output", "keyword_list.txt")
    if os.path.exists(keyword_path):
        with open(keyword_path, "r", encoding="utf-8") as f:
            for name in f:
                name = name.strip()
                if name:
                    STORYBOARD_AND_XC_WRAP_NAME.append(name)

def check_attribute(node, p_same_name):
    """Apply attribute-based matching on a single node.
    Returns a list of member nodes that should be visited next.
    """
    if not isinstance(node, dict):
        return []

    attributes = node.get("D_attributes", [])
    adopted = node.get("E_adoptedClassProtocols", [])
    members = node.get("G_members", [])

    name = node.get("A_name")

    # 스토리보드, assets, wrapper 식별자
    if node.get("A_name") in STORYBOARD_AND_XC_WRAP_NAME:
        in_matched_list(node)

    # 앱 진입점
    if ("main" in attributes or "UIApplicationMain" in attributes or
        "UIApplicationDelegate" in adopted or "UIWindowSceneDelegate" in adopted or
        "App" in adopted):
        in_matched_list(node)
        for member in members:
            if member.get("B_kind") == "variable" and member.get("A_name") == "body":
                in_matched_list(member)
            if member.get("B_kind") == "function" and member.get("A_name") == "main":
                in_matched_list(member)

    # ui
    skip_attrs = {"IBOutlet", "IBAction", "IBInspectable", "IBDesignable",  "State", "StateObject"}
    if any(attr in skip_attrs for attr in attributes):
        in_matched_list(node)
    
    # 런타임 참조
    if "objc" in attributes or "dynamic" in attributes or "NSManaged" in attributes:
        in_matched_list(node)

    if "objcMembers" in attributes:
        in_matched_list(node)
        for member in members:
            in_matched_list(member)
    
    # 데이터베이스
    if "Model" in attributes:
        in_matched_list(node)
        for member in members:
            if member.get("B_kind") == "variable": 
                in_matched_list(member)

    # actor
    if "globalActor" in attributes:
        in_matched_list(node)
        for member in members:
            if member.get("A_name") == "shared" and member.get("B_kind") == "variable":
                in_matched_list(member)

    if name in ["get", "set", "willSet", "didSet", "init"]:
        in_matched_list(node)

    if isinstance(name, str) and name.startswith("`") and name.endswith("`"):
        name = name[1:-1]
    if name in p_same_name:
        in_matched_list(node)

    return members

# Iterative DFS over AST containers; avoids recursion depth limits
def find_node(data, p_same_name):
    from collections import deque
    stack = deque()

    # seed
    if isinstance(data, list):
        stack.extend(data)
    elif isinstance(data, dict):
        # when a dict mapping name->node is provided, walk its values
        if "node" in data or "children" in data or "extension" in data:
            stack.append(data)
        else:
            stack.extend(data.values())
    else:
        return

    while stack:
        cur = stack.pop()
        if cur is None:
            continue

        # normalize container vs node
        container = cur if isinstance(cur, dict) else {}
        node = container.get("node") or container
        if not isinstance(node, dict):
            continue

        nid = id(node)
        if nid in VISITED_NODE:
            continue
        VISITED_NODE.add(nid)

        # apply attribute checks and enqueue members for further checks
        members = check_attribute(node, p_same_name) or []
        for m in members:
            if isinstance(m, dict):
                stack.append(m)

        # traverse structural containers if present
        extensions = container.get("extension", [])
        children = container.get("children", [])
        if isinstance(extensions, list):
            stack.extend(extensions)
        if isinstance(children, list):
            stack.extend(children)

def find_exception_target(p_same_name):
    input_file_1 = os.path.join(".", "AST", "output", "inheritance_node.json")
    input_file_2 = os.path.join(".", "AST", "output", "no_inheritance_node.json")
    output_file_1 = os.path.join(".", "AST", "output", "internal_exception_list.json")

    get_storyboard_and_xc_wrapper_info()

    # normalize p_same_name to a set of strings
    if isinstance(p_same_name, (set, list, tuple)):
        p_same_name = {str(x) for x in p_same_name if x is not None}
    else:
        p_same_name = set()
    
    if os.path.exists(input_file_1):
        with open(input_file_1, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        if isinstance(nodes, (list, dict)):
            find_node(nodes, p_same_name)
    if os.path.exists(input_file_2):
        with open(input_file_2, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        if isinstance(nodes, (list, dict)):
            find_node(nodes, p_same_name)
    
    with open(output_file_1, "w", encoding="utf-8") as f:
        json.dump(MATCHED_LIST, f, indent=2, ensure_ascii=False)
    
    temp = os.path.join(".", "AST", "output", "external_name.txt")
    with open(temp, "w", encoding="utf-8") as f:
        for name in p_same_name:
            f.write(f"{name}\n")