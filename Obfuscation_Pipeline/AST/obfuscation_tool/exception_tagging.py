import json
import os

NODE = []
EXCEPTION_NODE = []

def add_tagging(node):
    location = node.get("F_location")
    is_exception_node = 0
    for exception_node in EXCEPTION_NODE:
        ex_location = exception_node.get("F_location")
        if location == ex_location:
            is_exception_node = 1
    node["isException"] = is_exception_node
    
def repeat_match_member(data):
    def repeat_member(node):
        members = node.get("G_members", [])
        for member in members:
            repeat_member(member)
            add_tagging(member)
    def repeat(item):
        if item is None: 
            return
        node = item.get("node", item)
        extensions = item.get("extension", [])
        children = item.get("children", [])

        add_tagging(node)
        repeat_member(node)
        for extension in extensions:
            repeat(extension)
        for child in children:
            repeat(child)

    if isinstance(data, list):
        for item in data:
            repeat(item)
    else:
        repeat(data)

# 외부 라이브러리 / 표준 SDK 노드 없이 트리 구성
def re_make_tree(data):
    if data is None: 
        return
    node = data.get("node", data)
    extensions = data.get("extension", [])
    children = data.get("children", [])

    if node.get("B_kind") is None:
        for extension in extensions:
            if extension not in NODE:
                NODE.append(extension)
        for child in children:
            if child not in NODE:
                NODE.append(child)
    else:
        if data not in NODE:
            NODE.append(data)
        for extension in extensions:
            if extension in NODE:
                NODE.remove(extension)
        for child in children:
            if child in NODE:
                NODE.remove(child)

# node 처리
def find_node(data):
    if isinstance(data, list):
        for item in data:
            re_make_tree(item)
    elif isinstance(data, dict):
        for _, node in data.items():
            re_make_tree(node)
            
def exception_tagging():
    input_file_1 = "./AST/output/inheritance_node.json"
    input_file_2 = "./AST/output/no_inheritance_node.json"
    exception_file = "./AST/output/exception_list.json"
    output_file = "./AST/output/ast_node.json"

    if os.path.exists(input_file_1):
        with open(input_file_1, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        find_node(nodes)
    
    if os.path.exists(input_file_2):
        with open(input_file_2, "r", encoding="utf-8") as f:
            nodes = json.load(f)
        find_node(nodes)

    if os.path.exists(exception_file):
        with open(exception_file, "r", encoding="utf-8") as f:
            exception_nodes = json.load(f)
        if isinstance(exception_nodes, list):
            for node in exception_nodes:
                EXCEPTION_NODE.append(node)
    
    repeat_match_member(NODE)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(NODE, f, indent=2, ensure_ascii=False)