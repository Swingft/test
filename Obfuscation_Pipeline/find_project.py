"""프로젝트 파일 찾기 유틸리티"""
import os
import logging


def _trace(msg: str, *args, **kwargs) -> None:
    """디버그 추적 로그"""
    try:
        logging.trace(msg, *args, **kwargs)
    except (OSError, ValueError, TypeError, AttributeError) as e:
        # 로깅 실패 시에도 프로그램은 계속 진행
        return


def find_xcode_project(project_root: str) -> str | None:
    """
    프로젝트 루트에서 .xcodeproj 또는 .xcworkspace 파일을 찾습니다.
    
    Args:
        project_root: 프로젝트 루트 디렉토리 경로
        
    Returns:
        .xcodeproj 또는 .xcworkspace 파일의 절대 경로, 없으면 None
    """
    if not os.path.exists(project_root):
        _trace("프로젝트 루트 경로가 존재하지 않습니다: %s", project_root)
        return None
    
    if not os.path.isdir(project_root):
        _trace("프로젝트 루트가 디렉토리가 아닙니다: %s", project_root)
        return None
    
    xcodeproj_path = None
    xcworkspace_path = None
    
    # 1. 루트 디렉토리에서 먼저 찾기
    try:
        for item in os.listdir(project_root):
            item_path = os.path.join(project_root, item)
            if os.path.isdir(item_path):
                if item.endswith('.xcworkspace'):
                    xcworkspace_path = os.path.abspath(item_path)
                    break  # .xcworkspace를 우선
                elif item.endswith('.xcodeproj') and not xcodeproj_path:
                    xcodeproj_path = os.path.abspath(item_path)
    except (OSError, PermissionError) as e:
        _trace("루트 디렉토리 읽기 실패: %s", e)
    
    # .xcworkspace가 있으면 우선 사용
    if xcworkspace_path:
        return xcworkspace_path
    
    if xcodeproj_path:
        return xcodeproj_path
    
    # 2. 루트에 없으면 재귀적으로 찾기
    try:
        for root, dirs, files in os.walk(project_root):
            # .git, .build 등은 건너뛰기
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['build', 'DerivedData']]
            
            for d in dirs:
                if d.endswith('.xcworkspace'):
                    return os.path.abspath(os.path.join(root, d))
                elif d.endswith('.xcodeproj') and not xcodeproj_path:
                    xcodeproj_path = os.path.abspath(os.path.join(root, d))
        
        # .xcodeproj를 반환 (없으면 None)
        return xcodeproj_path
    except (OSError, PermissionError) as e:
        _trace("재귀적 프로젝트 파일 검색 실패: %s", e)
        return None

