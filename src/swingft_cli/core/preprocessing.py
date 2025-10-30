"""
전처리 단계 관련 함수들

AST 분석 및 전처리 단계를 담당하는 모듈입니다.
"""

import os
import sys
import subprocess
import time
import threading
import queue
import json
from collections import deque
import logging
from .tui import get_tui, progress_bar, _maybe_raise

# shared TUI instance (singleton)
tui = get_tui()




def _should_show_preprocessing_ui(working_config_path: str | None) -> bool:
    """식별자 난독화 옵션에 따라 Preprocessing UI 표시 여부 결정"""
    try:
        if working_config_path and os.path.isfile(working_config_path):
            with open(working_config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            src = cfg.get("options") if isinstance(cfg.get("options"), dict) else cfg
            val = (src or {}).get("Obfuscation_identifiers", True)
            if isinstance(val, str):
                return val.strip().lower() in {"1", "true", "yes", "y", "on"}
            else:
                return bool(val)
    except (OSError, IOError, json.JSONDecodeError, KeyError) as e:
        logging.trace("_should_show_preprocessing_ui: config read failed: %s", e)
        # non-fatal; default True
    return True


def _get_preprocessing_milestones():
    """전처리 단계의 milestones 정의"""
    return [
        ("external_file_list.txt", lambda base: os.path.isfile(os.path.join(base, "external_file_list.txt"))),
        ("external_list.json", lambda base: os.path.isfile(os.path.join(base, "external_list.json"))),
        ("external_name.txt", lambda base: os.path.isfile(os.path.join(base, "external_name.txt"))),
        ("import_list.txt", lambda base: os.path.isfile(os.path.join(base, "import_list.txt"))),
        ("keyword_list.txt", lambda base: os.path.isfile(os.path.join(base, "keyword_list.txt"))),
        ("standard_list.json", lambda base: os.path.isfile(os.path.join(base, "standard_list.json"))),
        ("wrapper_list.txt", lambda base: os.path.isfile(os.path.join(base, "wrapper_list.txt"))),
        ("xc_list.txt", lambda base: os.path.isfile(os.path.join(base, "xc_list.txt"))),
        ("inheritance_node.json", lambda base: os.path.isfile(os.path.join(base, "inheritance_node.json"))),
        ("no_inheritance_node.json", lambda base: os.path.isfile(os.path.join(base, "no_inheritance_node.json"))),
        ("internal_exception_list.json", lambda base: os.path.isfile(os.path.join(base, "internal_exception_list.json"))),
        ("external_candidates.json", lambda base: os.path.isfile(os.path.join(base, "external_candidates.json"))),
        ("source_json/", lambda base: (os.path.isdir(os.path.join(base, "source_json")) and any(True for _r,_d,f in os.walk(os.path.join(base, "source_json")) for _ in f))),
        ("typealias_json/", lambda base: (os.path.isdir(os.path.join(base, "typealias_json")) and any(True for _r,_d,f in os.walk(os.path.join(base, "typealias_json")) for _ in f))),
        ("sdk-json/", lambda base: (os.path.isdir(os.path.join(base, "sdk-json")) and any(True for _r,_d,f in os.walk(os.path.join(base, "sdk-json")) for _ in f))),
        ("external_to_ast/", lambda base: (os.path.isdir(os.path.join(base, "external_to_ast")) and any(True for _r,_d,f in os.walk(os.path.join(base, "external_to_ast")) for _ in f))),
        ("exception_list.json", lambda base: os.path.isfile(os.path.join(base, "exception_list.json"))),
        ("ast_node.json", lambda base: os.path.isfile(os.path.join(base, "ast_node.json"))),
    ]


def _run_preprocessing_stage(input_path: str, output_path: str, pipeline_path: str, 
                            working_config_path: str | None, show_pre_ui: bool) -> None:
    """전처리 단계 실행"""
    # 진행률 모드 설정
    preflight_progress_mode = str(os.environ.get("SWINGFT_PREFLIGHT_PROGRESS_MODE", "milestones")).strip().lower()
    preflight_progress_files = (str(os.environ.get("SWINGFT_PREFLIGHT_PROGRESS_FILES", "1")).strip().lower() not in {"0", "false", "no"})
    
    milestones = _get_preprocessing_milestones()
    
    # 예상 파일 수 계산
    try:
        if preflight_progress_mode == "files":
            expected_total_files = 0
            for root_dir, _dirs, files in os.walk(input_path):
                for fn in files:
                    if fn.endswith(".swift"):
                        expected_total_files += 1
        else:
            expected_total_files = len(milestones)
    except OSError as e:
        logging.trace("expected_total_files calc failed: %s", e)
        expected_total_files = len(milestones) if preflight_progress_mode != "files" else 0
    
    ast_output_dir = os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output")
    last_scan_ts = 0.0
    current_files_count = 0
    
    if show_pre_ui:
        tui.set_status([f"Preprocessing: {progress_bar(0, max(1, expected_total_files))}"])
    
    try:
        # 환경변수 설정
        env1 = os.environ.copy()
        if working_config_path:
            env1["SWINGFT_WORKING_CONFIG"] = os.path.abspath(working_config_path)
        env1.setdefault("PYTHONUNBUFFERED", "1")

        # 프로세스 실행
        proc1 = subprocess.Popen([
            "python3", pipeline_path, 
            input_path, 
            output_path,
            "--stage", "preprocessing"
        ], cwd=os.path.join(os.getcwd(), "Obfuscation_Pipeline"), 
           text=True, env=env1, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        
        if proc1.stdout is None:
            raise RuntimeError("프로세스 stdout을 가져올 수 없습니다")
        
        # 진행률 모니터링 실행
        _monitor_preprocessing_progress(proc1, ast_output_dir, milestones, 
                                      preflight_progress_mode, preflight_progress_files,
                                      expected_total_files, show_pre_ui)
        
        rc1 = proc1.wait()
        if rc1 != 0:
            logging.error("전처리 단계 실패 (종료 코드: %s)", rc1)
            _maybe_raise(RuntimeError(f"preprocessing failed rc={rc1}"))
            sys.exit(1)

    except subprocess.TimeoutExpired as e:
        logging.error("전처리 단계 타임아웃: %s", e)
        _maybe_raise(e)
        sys.exit(1)
    except (OSError, subprocess.SubprocessError) as e:
        logging.error("전처리 단계 실행 실패: %s", e)
        _maybe_raise(e)
        sys.exit(1)


def _monitor_preprocessing_progress(proc: subprocess.Popen, ast_output_dir: str, milestones: list,
                                  progress_mode: str, progress_files: bool, 
                                  expected_total: int, show_ui: bool) -> None:
    """전처리 진행률 모니터링"""
    spinner = ["|", "/", "-", "\\"]
    sp_idx = 0
    done_ast = False
    tail1 = deque(maxlen=10)
    last_scan_ts = 0.0
    current_files_count = 0
    
    # 비동기 리더 설정
    line_queue: "queue.Queue[str|None]" = queue.Queue()

    def _reader():
        try:
            for raw_line in proc.stdout:  # type: ignore[arg-type]
                line = (raw_line or "").rstrip("\n")
                line_queue.put(line)
        finally:
            try:
                line_queue.put(None)
            except (OSError, ValueError, TypeError, RuntimeError, UnicodeError) as e:
                logging.trace("unhandled exception caught: %s", e)
                _maybe_raise(e)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    eof = False
    while True:
        try:
            item = line_queue.get(timeout=0.1)
        except queue.Empty:
            item = ""
        
        if item is None:
            eof = True
        elif isinstance(item, str) and item:
            if item.strip():
                tail1.append(item)
            
            # 디버그 출력
            try:
                if os.environ.get("SWINGFT_TUI_ECHO", "") == "1":
                    print(item)
            except (OSError, UnicodeEncodeError) as e:
                logging.trace("echo print failed: %s", e)
                _maybe_raise(e)
            
            low = item.lower()
            if low.startswith("ast:") or " ast:" in low:
                done_ast = True

        # 진행률 업데이트
        if progress_files and expected_total > 0:
            now_ts = time.time()
            if now_ts - last_scan_ts >= 0.2:
                last_scan_ts = now_ts
                try:
                    if progress_mode == "files":
                        cnt = 0
                        if os.path.isdir(ast_output_dir):
                            for _r, _d, fns in os.walk(ast_output_dir):
                                for _fn in fns:
                                    cnt += 1
                        current_files_count = max(current_files_count, cnt)
                    else:
                        reached = 0
                        if os.path.isdir(ast_output_dir):
                            for _name, checker in milestones:
                                try:
                                    if checker(ast_output_dir):
                                        reached += 1
                                except OSError as e:
                                    logging.trace("milestone check failed: %s", e)
                                    _maybe_raise(e)
                        current_files_count = max(current_files_count, reached)
                except OSError as e:
                    logging.trace("progress scan failed: %s", e)
                    _maybe_raise(e)
        
        sp_idx = (sp_idx + 1) % len(spinner)
        if progress_files and expected_total > 0:
            bar = progress_bar(min(current_files_count, expected_total), expected_total)
        else:
            bar = progress_bar(1 if done_ast else 0, 1)
        
        if show_ui:
            try:
                tui.set_status([f"Preprocessing: {bar}  {spinner[sp_idx]}"])
            except (OSError, UnicodeEncodeError) as e:
                logging.trace("tui.set_status failed: %s", e)
                _maybe_raise(e)

        if eof and line_queue.empty():
            break
        time.sleep(0.05)
    
    # 최종 100% 표시
    try:
        done_ast = True
        if progress_files and expected_total > 0:
            current_files_count = max(current_files_count, expected_total)
            bar = progress_bar(expected_total, expected_total)
        else:
            bar = progress_bar(1, 1)
        
        sp_idx = (sp_idx + 1) % len(spinner)
        if show_ui:
            try:
                tui.set_status([f"Preprocessing: {bar}  {spinner[sp_idx]}"])
            except (OSError, UnicodeEncodeError) as e:
                logging.trace("tui.set_status final failed: %s", e)
                _maybe_raise(e)
    except OSError as e:
        logging.trace("final status update failed: %s", e)
        _maybe_raise(e)
    
    # 로그 정리
    try:
        tail1.clear()
    except (AttributeError, RuntimeError, TypeError) as e:
        logging.trace("tail clear failed: %s", e)
        _maybe_raise(e)
