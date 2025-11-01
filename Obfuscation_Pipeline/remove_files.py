import os, shutil, subprocess

# 파일 삭제
def remove_files(obf_project_dir, obf_project_dir_cfg):
    # Obfuscation_Pipeline 디렉토리 기준 (현재 스크립트 위치)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 프로젝트 루트 디렉토리 (Obfuscation_Pipeline의 부모)
    project_root = os.path.dirname(script_dir)
    
    file_path = os.path.join(".", "AST", "output")
    if os.path.isdir(file_path):
        shutil.rmtree(file_path)
    file_path = os.path.join(".", "Mapping", "output")
    if os.path.isdir(file_path):
        shutil.rmtree(file_path)
    file_path = obf_project_dir_cfg
    if os.path.isdir(file_path):
        shutil.rmtree(file_path)
    
    # 루트 .swingft 폴더 삭제
    swingft_dir = os.path.join(project_root, ".swingft")
    if os.path.isdir(swingft_dir):
        shutil.rmtree(swingft_dir)
    
    # externals/obfuscation-analyzer/analysis_output 디렉토리 삭제
    analyzer_output_dir = os.path.join(project_root, "externals", "obfuscation-analyzer", "analysis_output")
    if os.path.isdir(analyzer_output_dir):
        shutil.rmtree(analyzer_output_dir)
    
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