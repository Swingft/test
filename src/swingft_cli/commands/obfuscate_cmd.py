import os
import sys
import subprocess
import shutil
import io
import time
import threading
import queue
import re
from collections import deque
import logging
from ..validator import check_permissions
from ..core.config_validation import _get_config_path
from ..core.config.io_reader import read_io_paths as _read_io

from ..core.tui import get_tui, progress_bar, _maybe_raise, _trace
from ..core.stream_proxy import StreamProxy
from ..core.preprocessing import (
    _should_show_preprocessing_ui,
    _run_preprocessing_stage
)
from ..core.config_validation import (
    _get_config_path,
    _create_working_config,
    _setup_preflight_echo_holder,
    _run_config_validation_and_analysis
)

# Ensure interactive redraw is visible even under partial buffering
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except AttributeError as e:
    _trace("stdout has no reconfigure: %s", e)
except OSError as e:
    logging.warning("failed to reconfigure stdout: %s", e)
    _maybe_raise(e)

_BANNER = r"""
__     ____            _              __ _
\ \   / ___|_       _ (_)_ __   __ _ / _| |_
 \ \  \___  \ \ /\ / /| | '_ \ / _` | |_| __|
 / /   ___) |\ V  V / | | | | | (_) |  _| |_
/_/___|____/  \_/\_/  |_|_| |_|\__, |_|  \__|
 |_____|                       |___/
"""

# shared TUI instance (singleton)
tui = get_tui()
tui.banner = _BANNER

# global preflight echo holder
_preflight_echo = {}

def _progress_bar(completed: int, total: int, width: int = 30) -> str:
    # kept only for local call-sites compatibility if any leftover imports expect function
    return progress_bar(completed, total, width)


def _validate_paths(input_path: str, output_path: str) -> tuple[str, str]:
    """입력과 출력 경로를 검증하고 절대 경로로 변환"""
    input_abs = os.path.abspath(input_path)
    output_abs = os.path.abspath(output_path)
    
    if input_abs == output_abs:
        print(f"[ERROR] Input and output paths are the same!")
        print(f"[ERROR] Input: {input_abs}")
        print(f"[ERROR] Output: {output_abs}")
        print(f"[ERROR] The original file may be damaged. Use a different output path.")
        sys.exit(1)
    
    if output_abs.startswith(input_abs + os.sep) or output_abs.startswith(input_abs + "/"):
        print(f"[ERROR] Output path is a subdirectory of the input!")
        print(f"[ERROR] Input: {input_abs}")
        print(f"[ERROR] Output: {output_abs}")
        print(f"[ERROR] The original file may be damaged. Use a different output path.")
        sys.exit(1)
    
    return input_abs, output_abs


def _parse_bool_env(env_var: str, default: bool = False) -> bool:
    """환경변수를 안전하게 boolean으로 변환"""
    try:
        value = os.environ.get(env_var, str(default)).strip().lower()
        return value in {"1", "true", "yes", "y", "on"}
    except (AttributeError, TypeError) as e:
        logging.trace("_env_bool failed for %s: %s", env_var, e)
        return default


def _setup_tui_initialization(input_path: str, output_path: str) -> None:
    """TUI 초기화 및 초기 상태 설정"""
    tui.print_banner()
    tui.init()
    
    show_init = _parse_bool_env("SWINGFT_TUI_SHOW_INIT", False)
    if show_init:
        tui.set_status([
            "원본 보호 확인 완료",
            f"입력:  {input_path}",
            f"출력:  {output_path}",
            "Start Swingft …",
        ])


def _run_obfuscation_stage(input_path: str, output_path: str, pipeline_path: str, 
                          working_config_path: str | None) -> None:
    """난독화 단계 실행"""
    try:
        tui.set_status(["Obfuscation in progress…", ""])
    except (OSError, UnicodeEncodeError) as e:
        _trace("set_status warmup failed: %s", e)
        try:
            tui.set_status(["Obfuscation in progress…"])
        except (OSError, UnicodeEncodeError) as e2:
            _trace("set_status fallback failed: %s", e2)
            _maybe_raise(e2)
    
    try:
        env = os.environ.copy()
        if working_config_path:
            env["SWINGFT_WORKING_CONFIG"] = os.path.abspath(working_config_path)
        env.setdefault("PYTHONUNBUFFERED", "1")

        steps = _get_obfuscation_steps()
        detectors = _get_obfuscation_detectors()
        step_keys = [k for k, _ in steps]
        total_steps = len(steps)
        seen: set[str] = {"_bootstrap"}
        step_state: dict[str, str] = {}
        marker_rx = re.compile(r"^\s*(mapping|id-obf|cff|opaq|deadcode|encryption|cfg|debug)\s*:\s*(start|done|skip)\s*$", re.I)
        tail2 = deque(maxlen=10)

        proc = subprocess.Popen([
            "python3", pipeline_path, 
            input_path, 
            output_path,
            "--stage", "final"
        ], cwd=os.path.join(os.getcwd(), "Obfuscation_Pipeline"), 
           text=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)

        if proc.stdout is None:
            raise RuntimeError("프로세스 stdout을 가져올 수 없습니다")

        _monitor_obfuscation_progress(proc, steps, detectors, step_keys, total_steps, 
                                    seen, step_state, marker_rx, tail2)
        
        rc = proc.wait()
        if rc != 0:
            tui.set_status(["Obfuscation failed", f"exit code: {rc}"])
            sys.exit(1)
        
    except (OSError, subprocess.SubprocessError) as e:
        try:
            tui.set_status([f"Obfuscation failed: {e}"])
        except (OSError, UnicodeEncodeError) as e2:
            _trace("set_status failed: %s", e2)
            _maybe_raise(e2)
        _maybe_raise(e)
        sys.exit(1)


def _get_obfuscation_steps():
    """난독화 단계 정의"""
    return [
        ("_bootstrap", "Bootstrap"),
        ("mapping", "Identifier mapping"),
        ("id-obf", "Identifier obfuscation"),
        ("cff", "Control flow flattening"),
        ("opaq", "Opaque predicate"),
        ("deadcode", "Dead code"),
        ("encryption", "String encryption"),
        ("cfg", "Dynamic function"),
        ("debug", "Debug symbol removal"),
    ]


def _get_obfuscation_detectors():
    """난독화 단계 감지용 정규식"""
    return {
        "mapping": re.compile(r"(\\bmapping\\b.*?:|\\[mapping\\]|\\bmapping\\b.*\\bstart\\b|identifier\\s+mapping)", re.I),
        "id-obf": re.compile(r"(id[-_ ]?obf|identifier\\s+obfuscation)", re.I),
        "cff": re.compile(r"(\\bcff\\b|control\\s*flow\\s*flattening|control[- ]?flow)", re.I),
        "opaq": re.compile(r"(\\bopaq\\b|opaque\\s+predicate)", re.I),
        "deadcode": re.compile(r"(dead\\s*code|\\bdeadcode\\b)", re.I),
        "encryption": re.compile(r"(string\\s+encryption|encryption\\s+start|\\[swingft_string_encryption\\])", re.I),
        "cfg": re.compile(r"(\\bcfg\\b|dynamic\\s*function|cfg:)", re.I),
        "debug": re.compile(r"(delete\\s+debug\\s+symbols|debug:|\\bdebug\\b)", re.I),
    }


def _monitor_obfuscation_progress(proc: subprocess.Popen, steps: list, detectors: dict,
                                 step_keys: list, total_steps: int, seen: set[str],
                                 step_state: dict[str, str], marker_rx: re.Pattern,
                                 tail2: deque) -> None:
    """난독화 진행률 모니터링"""
    last_current = "준비 중"
    spinner = ["|", "/", "-", "\\"]
    sp2 = 0
    
    # queue reader
    q2: "queue.Queue[str|None]" = queue.Queue()
    def _reader2():
        try:
            for raw in proc.stdout:  # type: ignore[arg-type]
                line = (raw or "").rstrip("\n")
                q2.put(line)
        finally:
            try:
                q2.put(None)
            except queue.Full as e:
                _trace("queue sentinel put failed: %s", e)
                _maybe_raise(e)
    
    thr2 = threading.Thread(target=_reader2, daemon=True)
    thr2.start()

    eof2 = False
    while True:
        try:
            item = q2.get(timeout=0.1)
        except queue.Empty as e:
            logging.trace("queue.Empty in stream processing: %s", e)
            item = ""
        
        if item is None:
            eof2 = True
        elif isinstance(item, str) and item:
            line = item
            if line.strip():
                tail2.append(line)
                try:
                    if os.environ.get("SWINGFT_TUI_ECHO", "") == "1":
                        print(line)
                except (OSError, UnicodeEncodeError) as e:
                    _trace("echo print failed: %s", e)
                    _maybe_raise(e)
            
            low = line.lower()
            
            # 명시적 마커 처리
            m = marker_rx.match(line.strip())
            
            if m is not None:
                last_current = _handle_explicit_marker(m, steps, step_keys, seen, step_state, last_current)
                sp2 = (sp2 + 1) % len(spinner)
                bar = progress_bar(len([k for k in seen if k in step_keys]), total_steps)
                try:
                    tui.set_status([
                        f"Obfuscation: {bar}  {spinner[sp2]}",
                        f"Current: {last_current}",
                        "",
                        *list(tail2)
                    ])
                except (OSError, UnicodeEncodeError) as e:
                    _trace("set_status update failed: %s", e)
                    _maybe_raise(e)
                if eof2 and q2.empty():
                    break
                time.sleep(0.05)
                continue
            
            # 완료/스킵 처리
            if low.startswith("completed:") or low.startswith("skipped:"):
                last_current = "Finalizing"
            
            # 정규식 기반 단계 감지
            matched_key = _detect_step_by_regex(line, detectors)
            if matched_key is not None:
                last_current = _handle_detected_step(matched_key, steps, step_keys, seen, step_state, last_current)
            else:
                last_current = _handle_encryption_step(line, low, steps, seen, step_state, last_current)
                last_current = _handle_generic_steps(line, low, steps, step_keys, seen, step_state, last_current)
        
        # 주기적 리드로우
        sp2 = (sp2 + 1) % len(spinner)
        _update_final_label(step_keys, seen, step_state, steps, last_current)
        bar = progress_bar(len(seen), total_steps)
        try:
            tui.set_status([
                f"Obfuscation: {bar}  {spinner[sp2]}",
                f"Current: {last_current}",
                "",
                *list(tail2)
            ])
        except (OSError, UnicodeEncodeError) as e:
            _trace("set_status periodic update failed: %s", e)
            _maybe_raise(e)
        
        if eof2 and q2.empty():
            break
        time.sleep(0.05)


def _handle_explicit_marker(m: re.Match, steps: list, step_keys: list, seen: set[str],
                         step_state: dict[str, str], last_current: str) -> str:
    """명시적 마커 처리"""
    key = m.group(1).lower()
    action = m.group(2).lower()
    
    if action == "start":
        try:
            idx = step_keys.index(key)
            last_current = steps[idx][1]
        except ValueError as e:
            _trace("unknown step key in explicit marker: %s", e)
            _maybe_raise(e)
        step_state[key] = "start"
    else:
        if key in step_keys:
            seen.add(key)
        step_state[key] = action
        last_current = _advance_to_next_step(key, steps, step_keys, seen, step_state, last_current)
    return last_current


def _detect_step_by_regex(line: str, detectors: dict) -> str | None:
    """정규식으로 단계 감지"""
    for key, rx in detectors.items():
        if rx.search(line):
            return key
    return None


def _handle_detected_step(matched_key: str, steps: list, step_keys: list, seen: set[str],
                       step_state: dict[str, str], last_current: str) -> str:
    """감지된 단계 처리"""
    for k, lbl in steps:
        if k == matched_key:
            seen.add(k)
            last_current = _update_current_label(k, steps, step_keys, seen, step_state, last_current)
            break
    return last_current


def _handle_encryption_step(line: str, low: str, steps: list, seen: set[str],
                          step_state: dict[str, str], last_current: str) -> str:
    """암호화 단계 특별 처리"""
    for key, label in steps:
        if key == "encryption":
            if "[swingft_string_encryption] encryption_strings is true" in low:
                last_current = label
            if (low.startswith("encryption:") or " encryption:" in low or
                "[swingft_string_encryption] done" in low or
                low.endswith("[swingft_string_encryption] done.")):
                seen.add(key)
                step_state[key] = "done"
                last_current = label
    return last_current


def _handle_generic_steps(line: str, low: str, steps: list, step_keys: list, seen: set[str],
                        step_state: dict[str, str], last_current: str) -> str:
    """일반적인 단계 처리"""
    for key, label in steps:
        if key != "encryption":
            if (low.startswith(f"{key}:") or f" {key}:" in low or
                f"[{key}]" in low or low.startswith(f"{key} start")):
                seen.add(key)
                last_current = _update_current_label(key, steps, step_keys, seen, step_state, last_current)
    return last_current


def _advance_to_next_step(key: str, steps: list, step_keys: list, seen: set[str],
                         step_state: dict[str, str], last_current: str) -> str:
    """다음 단계로 진행"""
    try:
        primary_keys = [k for k in step_keys if k != "_bootstrap"]
        if all(k in seen for k in primary_keys):
            last_done_label = None
            for k2 in reversed(step_keys):
                if k2 in seen and k2 != "_bootstrap" and step_state.get(k2) == "done":
                    try:
                        idx2 = step_keys.index(k2)
                        last_done_label = steps[idx2][1]
                        break
                    except ValueError as e:
                        _trace("step index lookup failed: %s", e)
                        _maybe_raise(e)
            if last_done_label:
                last_current = last_done_label
            else:
                idx = step_keys.index(key)
                last_current = steps[idx][1]
        else:
            for k2, lbl2 in steps:
                if k2 not in seen:
                    last_current = lbl2
                    break
    except (ValueError, IndexError) as e:
        _trace("advance_to_next_step failed: %s", e)
        _maybe_raise(e)
    return last_current


def _update_current_label(key: str, steps: list, step_keys: list, seen: set[str],
                        step_state: dict[str, str], last_current: str) -> str:
    """현재 라벨 업데이트"""
    primary_keys = [kk for kk in step_keys if kk != "_bootstrap"]
    if all(kk in seen for kk in primary_keys):
        last_done_label = None
        for k2 in reversed(step_keys):
            if k2 in seen and k2 != "_bootstrap" and step_state.get(k2) == "done":
                try:
                    idx2 = step_keys.index(k2)
                    last_done_label = steps[idx2][1]
                    break
                except ValueError as e:
                    _trace("update_current_label index failed: %s", e)
                    _maybe_raise(e)
        last_current = last_done_label or steps[step_keys.index(key)][1]
    else:
        idx = step_keys.index(key)
        mv = None
        for j in range(idx + 1, len(steps)):
            if steps[j][0] not in seen:
                mv = steps[j][1]
                break
        last_current = mv or steps[idx][1]
    return last_current


def _update_final_label(step_keys: list, seen: set[str], step_state: dict[str, str],
                       steps: list, last_current: str) -> str:
    """최종 라벨 업데이트"""
    primary_keys = [k for k in step_keys if k != "_bootstrap"]
    if all(k in seen for k in primary_keys):
        last_done_label = None
        for k in reversed(step_keys):
            if k in seen and k != "_bootstrap" and step_state.get(k) == "done":
                try:
                    idx = step_keys.index(k)
                    last_done_label = steps[idx][1]
                    break
                except ValueError as e:
                    _trace("update_final_label index failed: %s", e)
                    _maybe_raise(e)
        if last_done_label:
            last_current = last_done_label
    return last_current


def handle_obfuscate(args):
    """난독화 프로세스 실행"""
    # Load I/O from config file only (no CLI I/O)
    cfg_path = _get_config_path(args) or 'swingft_config.json'
    try:
        effective_in, effective_out = _read_io(cfg_path)
    except SystemExit:
        raise
    except (OSError, ValueError, TypeError, KeyError) as e:
        logging.error("Failed to read config I/O: %s: %s", cfg_path, e)
        print(f"[ERROR] Failed to read config I/O: {cfg_path}: {e}")
        sys.exit(1)

    if not effective_in or not effective_out:
        print("[ERROR] Missing project.input/project.output in config. Set them in the config JSON (use swingft --json to generate a template).")
        sys.exit(1)

    # permissions check uses resolved paths
    check_permissions(effective_in, effective_out)

    # 경로 검증 및 절대 경로 변환
    input_path, output_path = _validate_paths(effective_in, effective_out)

    # propagate resolved values back to args for downstream stages
    args.input = input_path
    args.output = output_path
    
    # TUI 초기화
    _setup_tui_initialization(input_path, output_path)

    # preflight echo stream holder 설정
    _setup_preflight_echo_holder()

    # 파이프라인 경로 확인
    pipeline_path = os.path.join(os.getcwd(), "Obfuscation_Pipeline", "obf_pipeline.py")
    if not os.path.exists(pipeline_path):
        print(f"[ERROR] 파이프라인 파일을 찾을 수 없습니다: {pipeline_path}")
        sys.exit(1)

    # Config 파일 처리
    config_path = _get_config_path(args)
    working_config_path = _create_working_config(config_path) if config_path else None

    # 전처리 단계 실행
    show_pre_ui = _should_show_preprocessing_ui(working_config_path)
    _run_preprocessing_stage(input_path, output_path, pipeline_path, working_config_path, show_pre_ui)

    # 1단계: Config 검증 및 LLM 분석 (난독화 이전에 수행)
    _run_config_validation_and_analysis(working_config_path, args)

    # 2단계: 최종 난독화 실행 (배너는 초기 1회만 출력, 이후 헤더만 갱신)
    _run_obfuscation_stage(input_path, output_path, pipeline_path, working_config_path)

    # 완료 메시지
    try:
        sys.stdout.write("\nObfuscation completed\n")
        sys.stdout.flush()
    except OSError as e:
        _trace("stdout completion message failed: %s", e)
        try:
            tui.set_status(["Obfuscation completed"])
        except (OSError, UnicodeEncodeError) as e2:
            _trace("fallback completion status failed: %s", e2)
            _maybe_raise(e2)