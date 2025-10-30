"""
Config 검증 및 분석 관련 함수들

설정 파일 검증, LLM 분석, preflight 확인 등을 담당하는 모듈입니다.
"""

import os
import sys
import shutil
import io
import time
from contextlib import redirect_stdout, redirect_stderr
from .tui import get_tui, progress_bar
from .stream_proxy import StreamProxy
import logging

# strict-mode helper
try:
    from .tui import _maybe_raise
except ImportError as _imp_err:
    logging.trace("fallback _maybe_raise due to ImportError: %s", _imp_err)
    def _maybe_raise(e: BaseException) -> None:
        import os
        if os.environ.get("SWINGFT_TUI_STRICT", "").strip() == "1":
            raise e

def _load_config_or_exit(config_path: str):
    """Config 로드 함수 - 순환 import 방지를 위해 로컬 정의"""
    try:
        from ..config import load_config_or_exit
        return load_config_or_exit(config_path)
    except ImportError:
        # fallback: 직접 구현
        import json
        if not os.path.exists(config_path):
            logging.error("설정 파일을 찾을 수 없습니다: %s", config_path)
            sys.exit(1)
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logging.error("설정 파일 로드 실패: %s", e)
            _maybe_raise(e)
            sys.exit(1)

def _extract_rule_patterns(config):
    """Rule patterns 추출 함수 - 순환 import 방지를 위해 로컬 정의"""
    try:
        from ..config import extract_rule_patterns
        return extract_rule_patterns(config)
    except ImportError:
        # fallback: 기본 구현
        return []

def _summarize_risks_and_confirm(patterns, auto_yes=False):
    """위험 요약 및 확인 함수 - 순환 import 방지를 위해 로컬 정의"""
    try:
        from ..config import summarize_risks_and_confirm
        return summarize_risks_and_confirm(patterns, auto_yes=auto_yes)
    except ImportError:
        # fallback: 자동 승인
        return True
from .config import set_prompt_provider

# shared TUI instance (singleton)
tui = get_tui()

# global preflight echo holder
_preflight_echo = {}


def _get_config_path(args) -> str | None:
    """설정 파일 경로를 가져오거나 기본값 반환"""
    if getattr(args, 'config', None) is not None:
        if isinstance(args.config, str) and args.config.strip():
            return args.config.strip()
        else:
            return 'swingft_config.json'
    return None


def _create_working_config(config_path: str) -> str:
    """작업용 설정 파일 생성"""
    if not config_path or not os.path.exists(config_path):
        print(f"[ERROR] 설정 파일을 찾을 수 없습니다: {config_path}")
        sys.exit(1)
    
    abs_src = os.path.abspath(config_path)
    base_dir = os.path.dirname(abs_src)
    filename = os.path.basename(abs_src)
    root, ext = os.path.splitext(filename)
    if not ext:
        ext = ".json"
    working_name = f"{root}__working{ext}"
    working_path = os.path.join(base_dir, working_name)
    
    try:
        shutil.copy2(abs_src, working_path)
        return working_path
    except (OSError, IOError) as e:
        logging.error("설정 파일 복사 실패: %s", e)
        logging.error("원본: %s", abs_src)
        logging.error("대상: %s", working_path)
        _maybe_raise(e)
        sys.exit(1)


def _setup_preflight_echo_holder() -> None:
    """Preflight echo holder 설정"""
    # preflight echo holder: will contain 'include' and optional 'exclude' echo objects,
    # the current key ('include' or 'exclude'), and a stable 'proxy' used for redirect_stdout
    global _preflight_echo
    _preflight_echo = {
        "include": None,
        "exclude": None,
        "current": None,
        "proxy": None,
    }

    # install prompt provider to render interactive y/n inside status area
    _preflight_phase = {"phase": "init"}  # init | include | exclude

    def _prompt_provider(msg: str) -> str:
        try:
            text = str(msg)
            # detect include confirmation prompt
            if "Do you really want to include" in text:
                _preflight_phase["phase"] = "include"
            # detect transition to exclude prompts
            elif text.startswith("Exclude this identifier") or "Exclude this identifier" in text:
                if _preflight_phase.get("phase") != "exclude":
                    # transition: include -> exclude (or init -> exclude)
                    try:
                        include_header = ""
                        exclude_header = f"Preflight: {progress_bar(0,1)}  - | Current: Checking Exclude List"
                        # do not redraw header; keep previous (prefer Preprocessing panel)
                        # create an exclude echo (no header) and switch proxy target if possible
                        try:
                            excl = tui.make_stream_echo(header="", tail_len=10)
                            _preflight_echo["exclude"] = excl
                            # if a proxy exists, switch current to 'exclude'
                            if _preflight_echo.get("proxy") is not None:
                                _preflight_echo["current"] = "exclude"
                        except (OSError, UnicodeEncodeError) as e:
                            logging.trace("make_stream_echo failed in prompt_provider: %s", e)
                            _maybe_raise(e)
                        # best-effort: keep include echo's header intact
                    except (AttributeError, OSError) as e:
                        logging.trace("prompt_provider restore failed: %s", e)
                        _maybe_raise(e)
                _preflight_phase["phase"] = "exclude"
        except (OSError, UnicodeError) as e:
            logging.trace("prompt_provider unexpected error: %s", e)
            _maybe_raise(e)
        return tui.prompt_line(msg)

    set_prompt_provider(_prompt_provider)


def _run_config_validation_and_analysis(working_config_path: str | None, args) -> None:
    """Config 검증 및 LLM 분석 실행"""
    if not working_config_path:
        return
    
    # Analyzer 적용
    try:
        analyzer_root = os.environ.get("SWINGFT_ANALYZER_ROOT", os.path.join(os.getcwd(), "externals", "obfuscation-analyzer")).strip()
        proj_in = args.input
        ast_path = os.environ.get("SWINGFT_AST_NODE_PATH", "")
        from ..core.config.loader import _apply_analyzer_exclusions_to_ast_and_config as _apply_anl
        _apply_anl(analyzer_root, proj_in, ast_path, working_config_path, {})
    except (ImportError, OSError, KeyError) as e:
        logging.warning("Analyzer 적용 실패: %s", e)
        _maybe_raise(e)
    
    # Config 검증 및 사용자 확인
    try:
        auto_yes = getattr(args, 'yes', False)
        if auto_yes:
            _run_auto_config_validation(working_config_path)
        else:
            _run_interactive_config_validation(working_config_path)
    except (RuntimeError, OSError, KeyError) as e:
        logging.error("설정 검증 실패: %s", e)
        tui.set_status([f"설정 검증 실패: {e}"])
        _maybe_raise(e)
        sys.exit(1)


def _run_auto_config_validation(working_config_path: str) -> None:
    """자동 모드에서 Config 검증 실행"""
    buf_out1, buf_err1 = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out1), redirect_stderr(buf_err1):
        config = _load_config_or_exit(working_config_path)
    patterns = _extract_rule_patterns(config)
    buf_out2, buf_err2 = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out2), redirect_stderr(buf_err2):
        ok = _summarize_risks_and_confirm(patterns, auto_yes=True)
    
    if ok is False:
        sys.stdout.write(buf_out1.getvalue() + buf_err1.getvalue() + buf_out2.getvalue() + buf_err2.getvalue())
        sys.stdout.flush()
        raise RuntimeError("사용자 취소")
    
    tui.set_status(["설정 검증 완료"])
    _show_preflight_completion_screen()


def _run_interactive_config_validation(working_config_path: str) -> None:
    """대화형 모드에서 Config 검증 실행"""
    config = _load_config_or_exit(working_config_path)
    patterns = _extract_rule_patterns(config)
    
    # TUI echo 설정
    try:
        # LLM 분석 단계 진입: 배너는 유지하고 헤더만 LLM 분석으로 설정
        try:
            tui.set_status(["LLM analysis in progress…", ""])  # banner below header only
        except (OSError, UnicodeEncodeError) as _e:
            logging.trace("set_status LLM header failed: %s", _e)
            _maybe_raise(_e)
        include_echo = tui.make_stream_echo(header="LLM analysis", tail_len=10)
    except (OSError, UnicodeEncodeError) as e:
        logging.trace("make_stream_echo failed: %s", e)
        include_echo = None
        _maybe_raise(e)
    
    _preflight_echo["include"] = include_echo
    _preflight_echo["current"] = "include"
    
    # Proxy 설정
    if _preflight_echo.get("proxy") is None:
        _preflight_echo["proxy"] = StreamProxy(_preflight_echo)

    if _preflight_echo.get("include") is not None:
        try:
            with redirect_stdout(_preflight_echo["proxy"]), redirect_stderr(_preflight_echo["proxy"]):
                ok = _summarize_risks_and_confirm(patterns, auto_yes=False)
        finally:
            _preflight_echo["current"] = "include"
        
        _show_preflight_result(ok)
    else:
        try:
            ok = _summarize_risks_and_confirm(patterns, auto_yes=False)
        except (RuntimeError, OSError) as e:
            logging.error("interactive validation failed: %s", e)
            tui.set_status([f"설정 검증 실패: {e}"])
            _maybe_raise(e)
            sys.exit(1)


def _show_preflight_completion_screen() -> None:
    """Preflight 완료 화면 표시"""
    try:
        tui.show_exact_screen([
            "Preflight confirmation received",
            "Proceeding to obfuscation…",
        ])
    except (OSError, UnicodeEncodeError) as e:
        logging.trace("show_exact_screen failed: %s", e)
        try:
            tui.set_status(["Preflight confirmation received", "Proceeding to obfuscation…"])  
        except (OSError, UnicodeEncodeError) as e2:
            logging.trace("set_status failed: %s", e2)
            _maybe_raise(e2)
        _maybe_raise(e)
    try:
        time.sleep(0.2)
    except OSError as e:
        logging.trace("sleep failed: %s", e)
        _maybe_raise(e)


def _show_preflight_result(ok: bool) -> None:
    """Preflight 결과 표시"""
    try:
        if ok is False:
            tui.show_exact_screen(["Preflight aborted by user"])  
        else:
            tui.show_exact_screen([
                "Preflight confirmation received",
                "Proceeding to obfuscation…",
            ])
    except (OSError, UnicodeEncodeError) as e:
        logging.trace("show_exact_screen failed: %s", e)
        try:
            if ok is False:
                tui.set_status(["Preflight aborted by user"])  
            else:
                tui.set_status(["Preflight confirmation received", "Proceeding to obfuscation…"])  
        except (OSError, UnicodeEncodeError) as e2:
            logging.trace("set_status failed: %s", e2)
            _maybe_raise(e2)
        _maybe_raise(e)
    try:
        time.sleep(0.2)
    except OSError as e:
        logging.trace("sleep failed: %s", e)
        _maybe_raise(e)
