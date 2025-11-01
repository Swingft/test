"""임시 파일 정리 모듈"""
import os
import shutil
from .tui import _trace


def cleanup_before_obfuscation(output_path: str) -> None:
    """난독화 시작 전 임시 파일 정리 (obfuscate_cmd.py용)"""
    try:
        # 프로젝트 루트 디렉토리
        project_root = os.getcwd()
        # Obfuscation_Pipeline 디렉토리
        pipeline_dir = os.path.join(project_root, "Obfuscation_Pipeline")
        
        # AST/output 디렉토리 삭제
        ast_output = os.path.join(pipeline_dir, "AST", "output")
        if os.path.isdir(ast_output):
            shutil.rmtree(ast_output)
        
        # Mapping/output 디렉토리 삭제
        mapping_output = os.path.join(pipeline_dir, "Mapping", "output")
        if os.path.isdir(mapping_output):
            shutil.rmtree(mapping_output)
        
        # obf_project_dir_cfg 디렉토리 삭제
        obf_project_dir_cfg = os.path.join(os.path.dirname(output_path), "cfg")
        if os.path.isdir(obf_project_dir_cfg):
            shutil.rmtree(obf_project_dir_cfg)
        
        # 루트 .swingft 폴더 삭제
        swingft_dir = os.path.join(project_root, ".swingft")
        if os.path.isdir(swingft_dir):
            shutil.rmtree(swingft_dir)
        
        # externals/obfuscation-analyzer/analysis_output 디렉토리 삭제
        analyzer_output_dir = os.path.join(project_root, "externals", "obfuscation-analyzer", "analysis_output")
        if os.path.isdir(analyzer_output_dir):
            shutil.rmtree(analyzer_output_dir)
        
        # String_Encryption 디렉토리의 JSON 파일들 삭제
        se_dir = os.path.join(pipeline_dir, "String_Encryption")
        se_strings = os.path.join(se_dir, "strings.json")
        if os.path.exists(se_strings):
            os.remove(se_strings)
        se_targets = os.path.join(se_dir, "targets_swift_paths.json")
        if os.path.exists(se_targets):
            os.remove(se_targets)
        
        # 루트 디렉토리의 JSON 파일들 삭제
        root_json_files = [
            "mapping_result.json",
            "mapping_result_s.json",
            "type_info.json",
            "swift_file_list.txt",
            "targets_swift_paths.json"
        ]
        for filename in root_json_files:
            file_path = os.path.join(pipeline_dir, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        
        _trace("이전 임시 파일 정리 완료")
    except Exception as e:
        _trace("임시 파일 정리 실패 (계속 진행): %s", e)

