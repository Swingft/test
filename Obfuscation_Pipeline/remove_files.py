import os, shutil, subprocess

# 파일 삭제
def remove_files(obf_project_dir, obf_project_dir_cfg):
    file_path = os.path.join(".", "AST", "output")
    if os.path.isdir(file_path):
        shutil.rmtree(file_path)
    file_path = os.path.join(".", "Mapping", "output")
    if os.path.isdir(file_path):
        shutil.rmtree(file_path)
    file_path = obf_project_dir_cfg
    if os.path.isdir(file_path):
        shutil.rmtree(file_path)
    file_path = os.path.join(obf_project_dir, "_dyn_obf_scan_dumps")
    if os.path.isdir(file_path):
        shutil.rmtree(file_path)
    if os.path.exists(file_path):
        os.remove(file_path)
    file_path = os.path.join(".", "String_Encryption", "strings.json")
    if os.path.exists(file_path):
        os.remove(file_path)
    file_path = os.path.join(".", "String_Encryption", "targets_swift_paths.json")
    if os.path.exists(file_path):
        os.remove(file_path)
    file_path = os.path.join(".", "mapping_result.json")
    if os.path.exists(file_path):
        os.remove(file_path)
    file_path = os.path.join(".", "mapping_result_s.json")
    if os.path.exists(file_path):
        os.remove(file_path)
    file_path = os.path.join(".", "type_info.json")
    if os.path.exists(file_path):
        os.remove(file_path)
    file_path = os.path.join(".", "swift_file_list.txt")
    if os.path.exists(file_path):
        os.remove(file_path)
    file_path = os.path.join(".", "targets_swift_paths.json")
    if os.path.exists(file_path):
        os.remove(file_path)