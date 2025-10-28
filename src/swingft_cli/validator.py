"""
validator.py: Swingft CLI 입출력 경로 권한 검사 유틸리티
"""

import os
import sys
import logging

def _strict_mode() -> bool:
    return os.environ.get("SWINGFT_TUI_STRICT", "").strip() == "1"

def _maybe_raise(e: BaseException) -> None:
    if _strict_mode():
        raise e

def check_permissions(input_path: str, output_path: str) -> None:
    """
    입력 경로가 존재하고 읽기 권한이 있는지,
    출력 경로(또는 그 부모 디렉터리)가 쓰기 권한이 있는지 검사합니다.
    실패 시 오류 메시지를 출력하고 종료합니다.
    """
    # 입력 경로 검사
    if not os.path.exists(input_path):
        logging.error(f"입력 경로가 존재하지 않습니다: {input_path}")
        sys.exit(1)
    if not os.access(input_path, os.R_OK):
        logging.error(f"입력 경로에 접근할 수 없습니다: {input_path}")
        sys.exit(1)

    # 출력 경로 준비
    parent_dir = os.path.dirname(output_path) or "."
    if not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except (OSError, PermissionError) as e:
            logging.error(f"출력 디렉토리를 생성할 수 없습니다: {parent_dir} ({e})")
            _maybe_raise(e)
            sys.exit(1)
    # 출력 권한 검사
    if os.path.exists(output_path):
        if not os.access(output_path, os.W_OK):
            logging.error(f"출력 경로에 쓰기 권한이 없습니다: {output_path}")
            sys.exit(1)
    else:
        if not os.access(parent_dir, os.W_OK):
            logging.error(f"출력 디렉토리에 쓰기 권한이 없습니다: {parent_dir}")
            sys.exit(1)