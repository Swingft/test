import shutil
import os
import json
import logging

from .run_swift_syntax import run_swift_syntax
from .internal_tool.find_internal_files import find_internal_files
from .internal_tool.integration_ast import integration_ast
from .internal_tool.find_wrapper_candidates import find_wrapper_candidates
from .internal_tool.find_keyword import find_keyword
from .internal_tool.find_exception_target import find_exception_target
from .external_library_tool.find_external_files import find_external_files
from .external_library_tool.find_external_candidates import find_external_candidates
from .external_library_tool.match_candidates import match_candidates_external
from .standard_sdk_tool.find_standard_sdk import find_standard_sdk
from .standard_sdk_tool.match_candidates import match_candidates_sdk
from .obfuscation_tool.get_external_name import get_external_name
from .obfuscation_tool.merge_exception_list import merge_exception_list
from .obfuscation_tool.exception_tagging import exception_tagging


def _trace(msg: str, *args, **kwargs) -> None:
    """디버그 추적 로그"""
    try:
        logging.log(10, msg, *args, **kwargs)
    except (OSError, ValueError, TypeError) as e:
        # 로깅 실패 시에도 프로그램은 계속 진행
        print(f"[DEBUG] {msg % args if args else msg}")


def _log_warning(msg: str, *args, **kwargs) -> None:
    """경고 메시지 (사용자에게 표시 + 디버그 로그)"""
    try:
        logging.warning(msg, *args, **kwargs)
    except (OSError, ValueError, TypeError) as e:
        # 로깅 실패 시에도 사용자에게는 메시지 표시
        print(f"[WARNING] 로깅 실패: {e}")
    print(f"⚠️  경고: {msg % args if args else msg}")


def _log_error(msg: str, *args, **kwargs) -> None:
    """오류 메시지 (사용자에게 표시 + 디버그 로그)"""
    try:
        logging.error(msg, *args, **kwargs)
    except (OSError, ValueError, TypeError) as e:
        # 로깅 실패 시에도 사용자에게는 메시지 표시
        print(f"[ERROR] 로깅 실패: {e}")
    print(f"❌ 오류: {msg % args if args else msg}")


def _maybe_raise(e: BaseException) -> None:
    """엄격 모드에서 예외 재발생"""
    try:
        if str(os.environ.get("SWINGFT_TUI_STRICT", "")).strip() == "1":
            raise e
    except (OSError, ValueError, TypeError) as env_error:
        # 환경변수 읽기 실패 시에는 무시하고 계속 진행
        print(f"[DEBUG] 환경변수 읽기 실패: {env_error}")

def run_ast(code_project_dir):
    # 구성 파일을 읽어 Obfuscation_identifiers 옵션이 꺼져 있으면 스킵
    try:
        # 우선 환경변수 우선
        cfg_path = os.environ.get("SWINGFT_WORKING_CONFIG")
        if not cfg_path:
            # 기본 경로: Obfuscation_Pipeline/Swingft_config.json
            script_dir = os.path.dirname(os.path.abspath(__file__))
            obf_root = os.path.abspath(os.path.join(script_dir, os.pardir))
            cfg_path = os.path.join(obf_root, "Swingft_config.json")
        cfg_json = {}
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg_json = json.load(f)
        def _to_bool(v, default=True):
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in {"1","true","yes","y","on"}
            if isinstance(v, (int, float)):
                return bool(v)
            return default
        # 옵션 키는 상위 호환: 루트 혹은 options 아래 둘 다 지원
        opt_map = cfg_json.get("options") if isinstance(cfg_json.get("options"), dict) else cfg_json
        safe_map = opt_map if isinstance(opt_map, dict) else {}
        flag_val = safe_map.get("Obfuscation_identifiers", True)
        if not _to_bool(flag_val, True):
            print("[AST] Obfuscation_identifiers=false → AST 분석 스킵")
            return
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        _trace("Config load failed: %s", e)
        _maybe_raise(e)
        _log_warning("설정 파일 로드 실패 - %s", e)
        # 설정 로드 실패 시에는 기존 동작 유지
    except (RuntimeError, MemoryError, SystemError) as e:
        _trace("Unexpected error loading config: %s", e)
        _maybe_raise(e)
        _log_error("설정 로드 중 예상치 못한 오류 - %s", e)
        # 예상치 못한 오류는 계속 진행
    original_dir = os.getcwd()  

    # 필요한 디렉토리 생성
    try:
        os.makedirs("./AST/output/source_json/", exist_ok=True) 
        os.makedirs("./AST/output/typealias_json/", exist_ok=True)
        os.makedirs("./AST/output/external_to_ast/", exist_ok=True)
        os.makedirs("./AST/output/sdk-json/", exist_ok=True)
    except (OSError, PermissionError) as e:
        _trace("Failed to create output directories: %s", e)
        _maybe_raise(e)
        _log_error("출력 디렉토리 생성 실패 - %s", e)
        return
    except (RuntimeError, MemoryError, SystemError) as e:
        _trace("Unexpected error creating directories: %s", e)
        _maybe_raise(e)
        _log_error("디렉토리 생성 중 예상치 못한 오류 - %s", e)
        return

    # 소스코드 & 외부 라이브러리 파일 위치 수집 
    try:
        find_internal_files(code_project_dir)
        find_external_files(code_project_dir)
    except (RuntimeError, MemoryError, SystemError) as e:
        _trace("Failed to find files: %s", e)
        _maybe_raise(e)
        _log_warning("파일 수집 실패 - %s", e)

    # 소스코드, 외부 라이브러리 AST 파싱 & 소스코드 AST 선언부 통합
    try:
        run_swift_syntax()
        os.chdir(original_dir)
        integration_ast()
    except (RuntimeError, MemoryError, SystemError) as e:
        _trace("Failed to run Swift syntax analysis: %s", e)
        _maybe_raise(e)
        _log_error("Swift 구문 분석 실패 - %s", e)
        return

    # 외부 라이브러리 / 표준 SDK 후보 추출 & 외부 라이브러리 요소 식별
    try:
        find_external_candidates()
        match_candidates_external()
    except (RuntimeError, MemoryError, SystemError) as e:
        _trace("Failed to process external candidates: %s", e)
        _maybe_raise(e)
        _log_warning("외부 후보 처리 실패 - %s", e)

    p_same_name = set()
    # 표준 SDK 정보 추출 & 표준 SDK 요소 식별
    try:
        path = "./AST/output/import_list.txt"
        if os.path.exists(path):
            p_same_name = find_standard_sdk()
            match_candidates_sdk()
    except (RuntimeError, MemoryError, SystemError) as e:
        _trace("Failed to process standard SDK: %s", e)
        _maybe_raise(e)
        _log_warning("표준 SDK 처리 실패 - %s", e)
    
    # 래퍼 후보 추출 & 내부 제외 대상 식별 
    try:
        find_wrapper_candidates()
        find_keyword()
        p_same_name.update(get_external_name())
        find_exception_target(p_same_name)
    except (RuntimeError, MemoryError, SystemError) as e:
        _trace("Failed to process wrapper candidates and exceptions: %s", e)
        _maybe_raise(e)
        _log_warning("래퍼 후보 및 예외 처리 실패 - %s", e)

    # 제외 대상 리스트 병합
    try:
        merge_exception_list()
        exception_tagging()
    except (RuntimeError, MemoryError, SystemError) as e:
        _trace("Failed to merge exception list and tagging: %s", e)
        _maybe_raise(e)
        _log_error("예외 리스트 병합 및 태깅 실패 - %s", e)
        return
