from __future__ import annotations

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Set
import logging
import sys
import re
from .ui_utils import supports_color as _supports_color, blue as _blue, yellow as _yellow

# strict-mode helper
try:
    from ..tui import _maybe_raise  # type: ignore
except ImportError as _imp_err:
    logging.trace("fallback _maybe_raise due to ImportError: %s", _imp_err)
    def _maybe_raise(e: BaseException) -> None:
        import os
        if os.environ.get("SWINGFT_TUI_STRICT", "").strip() == "1":
            raise e

from .ast_utils import update_ast_node_exceptions as _update_ast_node_exceptions
from .exclusions import ast_unwrap as _ast_unwrap
from .exclusions import write_feedback_to_output as _write_feedback_to_output


def _has_ui_prompt() -> bool:
    try:
        import swingft_cli.core.config as _cfg
        return getattr(_cfg, "PROMPT_PROVIDER", None) is not None
    except ImportError as e:
        logging.trace("ImportError in _has_ui_prompt: %s", e)
        return False
    except AttributeError as e:
        logging.trace("_has_ui_prompt attribute error: %s", e)
        _maybe_raise(e)
        return False


# NOTE: color helpers are imported from ui_utils as
# _supports_color, _blue, _yellow. Do NOT re-wrap them here to avoid recursion.


def _colorize_preflight_line(msg: str) -> str:
    try:
        s = str(msg)
        # Allow both legacy [preflight] and new [Warning]
        m = re.match(r"^\[(preflight|Warning)\](.*)$", s)
        if not m:
            return msg
        rest = m.group(2) or ""
        # 표시는 [Warning]으로 통일
        return _blue("[Warning]") + _yellow(rest)
    except (AttributeError, TypeError, ValueError) as e:
        logging.trace("format_warning failed: %s", e)
        return msg

def _gray(s: str) -> str:
    return f"\x1b[90m{s}\x1b[0m"


def _bold(s: str) -> str:
    return f"\x1b[1m{s}\x1b[0m"


def _preflight_print(msg: str) -> None:
    # TUI 상태와 겹치지 않도록 새 줄로 시작 (단, 메시지가 빈 줄로 시작하지 않는 경우만)
    s = str(msg).strip()
    if s and not s.startswith("\n"):
        try:
            sys.stdout.write("\n")
            sys.stdout.flush()
        except OSError as e:
            logging.trace("_preflight_print newline write failed: %s", e)
    
    if not _has_ui_prompt():
        if _supports_color():
            print(_colorize_preflight_line(msg))
        else:
            s = str(msg)
            if s.startswith("[preflight]"):
                s = "[Warning]" + s[len("[preflight]"):]
            print(s)


def _preflight_verbose() -> bool:
    v = os.environ.get("SWINGFT_PREFLIGHT_VERBOSE", "")
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _append_terminal_log(config: Dict[str, Any], lines: list[str]) -> None:
    try:
        out_dir = str((config.get("project") or {}).get("output") or "").strip()
        base = os.path.join(out_dir, "Obfuscation_Report", "preflight") if out_dir else os.path.join(os.getcwd(), "Obfuscation_Report", "preflight")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "terminal_preflight.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(datetime.utcnow().isoformat() + "Z\n")
            for ln in lines:
                f.write(str(ln) + "\n")
            f.write("\n")
    except (OSError, UnicodeError, PermissionError) as e:
        logging.trace("append_terminal_log failed: %s", e)
        _maybe_raise(e)


def check_exception_conflicts(config_path: str, config: Dict[str, Any]) -> Set[str]:
    env_ast = os.environ.get("SWINGFT_AST_NODE_PATH", "").strip()
    if env_ast and os.path.exists(env_ast):
        ast_file = Path(env_ast)
    else:
        ast_candidates = [
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output", "ast_node.json"),
            os.path.join(os.getcwd(), "AST", "output", "ast_node.json"),
        ]
        ast_file = next((Path(p) for p in ast_candidates if Path(p).exists()), None)

    if not ast_file:
        # 조용히 스킵 (Stage 1 스킵 시 정상)
        return set()

    try:
        apply_cfg = str(os.environ.get("SWINGFT_APPLY_CONFIG_TO_AST", "")).strip().lower() in {"1", "true", "yes", "y", "on"}
        if apply_cfg and ast_file and ast_file.exists():
            try:
                items = config.get("exclude", {}).get("obfuscation", []) or []
            except (AttributeError, TypeError) as e:
                logging.trace("config exclude.obfuscation access failed: %s", e)
                _maybe_raise(e)
                items = []
            if isinstance(items, list) and items:
                try:
                    _update_ast_node_exceptions(
                        str(ast_file), items, is_exception=1, lock_children=True, quiet=True
                    )
                except (OSError, ValueError, TypeError) as e:
                    logging.warning("apply-config → AST failed: %s", e)
                    _maybe_raise(e)
                else:
                    if _preflight_verbose():
                        print("[preflight] apply-config → AST: applied exclude.obfuscation to isException=1")
        elif _preflight_verbose():
            print("[preflight] apply-config DRY-RUN: not applying to AST (set SWINGFT_APPLY_CONFIG_TO_AST=1 to apply)")
    except (OSError, RuntimeError, ValueError) as e:
        logging.trace("apply-config wrapper failed: %s", e)
        _maybe_raise(e)

    try:
        with open(ast_file, 'r', encoding='utf-8') as f:
            ast_list = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.trace("AST read failed: %s", e)
        _maybe_raise(e)
        return set()

    ex_names: Set[str] = set()
    CONTAINER_KEYS = ("G_members", "children", "members", "extension", "node")

    def _walk_iter(root):
        from collections import deque
        dq = deque([root])
        seen = set()
        while dq:
            o = dq.pop()
            oid = id(o)
            if oid in seen:
                continue
            seen.add(oid)

            if isinstance(o, dict):
                cur = _ast_unwrap(o)
                if isinstance(cur, dict):
                    nm = str(cur.get("A_name", "")).strip()
                    if nm and int(cur.get("isException", 0)) == 1:
                        ex_names.add(nm)

                    # enqueue container children from unwrapped dict
                    for key in CONTAINER_KEYS:
                        ch = cur.get(key)
                        if isinstance(ch, list):
                            dq.extend(ch)
                        elif isinstance(ch, dict):
                            dq.append(ch)

                    # if wrapped, also enqueue container children from original, except 'node'
                    if o is not cur:
                        for key in CONTAINER_KEYS:
                            if key == 'node':
                                continue
                            ch = o.get(key)
                            if isinstance(ch, list):
                                dq.extend(ch)
                            elif isinstance(ch, dict):
                                dq.append(ch)

                    # enqueue remaining values
                    for v in cur.values():
                        dq.append(v)
                    if o is not cur:
                        for k, v in o.items():
                            if k not in CONTAINER_KEYS:
                                dq.append(v)
                else:
                    for v in o.values():
                        dq.append(v)

            elif isinstance(o, list):
                dq.extend(o)

    _walk_iter(ast_list)
    if not ex_names:
        return set()

    # capture buffer for include session logs
    _capture: list[str] = []
    wildcard_patterns = []
    for section in ("include", "exclude"):
        for category in ("obfuscation",):
            items = config.get(section, {}).get(category, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str) and item.strip() == "*":
                        wildcard_patterns.append(f"{section}.{category}")
    if wildcard_patterns:
        _capture.append("[preflight] ⚠️  '*' 단독 패턴 사용 감지:")
        for pattern in wildcard_patterns:
            _capture.append(f"  - {pattern}: 모든 식별자에 적용됩니다")
        _capture.append("  - 이는 의도된 설정인지 확인이 필요합니다.")
        try:
            prompt_msg = "계속 진행하시겠습니까? [y/N]: "
            if _has_ui_prompt():
                import swingft_cli.core.config as _cfg
                ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt_msg)).strip().lower()
            else:
                ans = input(prompt_msg).strip().lower()
            if ans not in ("y", "yes"):
                print("사용자에 의해 취소되었습니다.")
                raise SystemExit(1)
        except (EOFError, KeyboardInterrupt):
            print("\n사용자에 의해 취소되었습니다.")
            raise SystemExit(1)

    config_names = set()
    for category in ("obfuscation",):
        items = config.get("include", {}).get(category, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str) and item.strip():
                    item = item.strip()
                    if "*" not in item and "?" not in item:
                        config_names.add(item)
                    else:
                        import fnmatch
                        for ex_name in ex_names:
                            if fnmatch.fnmatchcase(ex_name, item):
                                config_names.add(ex_name)

    conflicts = config_names & ex_names
    _capture.append(f"[preflight] Config include identifiers: {sorted(list(config_names))}")
    _capture.append(f"[preflight] Conflicts found: {len(conflicts)} items")
    _preflight_print("")  # suppress terminal spam; rely on session logs or ask mode prints
    if conflicts:
        _pf = config.get("preflight", {}) if isinstance(config.get("preflight"), dict) else {}
        policy = str(
            _pf.get("conflict_policy")
            or _pf.get("include_conflict_policy")
            or "ask"
        ).strip().lower()
        _preflight_print(f"\n[Warning] ⚠️  The provided include entries conflict with exclude rules; including them may cause conflicts:")
        sample_all = sorted(list(conflicts))
        sample = sample_all[:10]
        _preflight_print(f"  - Collision identifiers: {len(conflicts)} items (example: {', '.join(sample)})")
        try:
            if policy == "force":
                _update_ast_node_exceptions(
                    str(ast_file), conflicts, is_exception=0,
                    allowed_kinds={"function"}, lock_children=True,
                    quiet=_has_ui_prompt()
                )
                # Write force action feedback
                try:
                    out_dir = str((config.get("project") or {}).get("output") or "").strip()
                    fb = [
                        "[preflight] Include conflict forced",
                        f"Conflicts: {len(conflicts)}",
                        f"Sample: {', '.join(sample_all[:20])}",
                        f"Policy: {policy}",
                        f"Target output: {out_dir}",
                        f"AST: {str(ast_file)}",
                    ]
                    _write_feedback_to_output(config, "include_conflict_forced", "\n".join(fb))
                    _append_terminal_log(config, fb)
                    # session copy
                    try:
                        _write_feedback_to_output(config, "include_session", "\n".join(_capture + ["", *fb]))
                    except (OSError, UnicodeError, ValueError) as e:
                        logging.trace("include_session write failed: %s", e)
                        _maybe_raise(e)
                except (OSError, ValueError, TypeError) as e:
                    logging.trace("force policy handling failed: %s", e)
                    _maybe_raise(e)
            elif policy == "skip":
                # 터미널 출력 없이 파일에만 기록
                try:
                    fb = [
                        "[preflight] Include conflict skipped by policy",
                        f"Conflicts: {len(conflicts)}",
                        f"Sample: {', '.join(sample_all[:20])}",
                        f"Policy: {policy}",
                        f"Target output: {str((config.get('project') or {}).get('output') or '').strip()}",
                        f"AST: {str(ast_file)}",
                    ]
                    _write_feedback_to_output(config, "include_conflict_skipped", "\n".join(fb))
                    _append_terminal_log(config, fb)
                    try:
                        _write_feedback_to_output(config, "include_session", "\n".join(_capture + ["", *fb]))
                    except (OSError, UnicodeError, ValueError) as e:
                        logging.trace("include_session write failed: %s", e)
                        _maybe_raise(e)
                except (OSError, UnicodeError, ValueError) as e:
                    logging.trace("skip policy handling failed: %s", e)
                    _maybe_raise(e)
            else:
                if _has_ui_prompt():
                    import swingft_cli.core.config as _cfg
                    full_list = ""
                    try:
                        if sample_all:
                            if _supports_color():
                                colored = ["  " + _gray("-") + " " + _bold(_yellow(s)) for s in sample_all]
                                full_list = "\n" + "\n".join(colored)
                            else:
                                full_list = "\n  - " + "\n  - ".join(sample_all)
                    except (UnicodeError, ValueError, TypeError) as e:
                        logging.trace("full_list build failed: %s", e)
                        _maybe_raise(e)
                        full_list = ""
                    # TUI 상태와 겹치지 않도록 한 줄만 추가
                    try:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    except OSError as e:
                        logging.trace("prompt newline write failed: %s", e)
                    
                    prompt_msg = (
                        ( _colorize_preflight_line("[Warning] The provided include list may cause conflicts.")
                          if _supports_color() else
                          "[preflight] The provided include list may cause conflicts." )
                        + "\n"
                        + (full_list or "")
                        + "\n\nContinue including? [y/n]: "
                    )
                    ans = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt_msg)).strip().lower()
                    _capture.append("[Warning] The provided include list may cause conflicts.")

                    _capture.extend(["  - " + s for s in sample_all])
                else:
                    full_list = ""
                    try:
                        if sample_all:
                            if _supports_color():
                                colored = ["  " + _gray("-") + " " + _bold(_yellow(s)) for s in sample_all]
                                full_list = "\n" + "\n".join(colored)
                            else:
                                full_list = "\n  - " + "\n  - ".join(sample_all)
                    except (UnicodeError, ValueError, TypeError) as e:
                        logging.trace("full_list build failed: %s", e)
                        _maybe_raise(e)
                        full_list = ""
                    head = "[preflight] The provided include entries conflict with exclude rules.\n"
                    if _supports_color():
                        head = _blue("[preflight]") + _yellow(" The provided include entries conflict with exclude rules.\n")
                    prompt_msg = (
                        head
                        + f"  - Collision identifiers: {len(conflicts)} items"
                        + (":" if sample_all else "")
                        + (full_list or "")
                        + "\n\nContinue including? [y/n]: "
                    )
                    ans = input(prompt_msg).strip().lower()
                if ans in ("y", "yes"):
                    _update_ast_node_exceptions(
                        str(ast_file), conflicts, is_exception=0,
                        allowed_kinds={"function"}, lock_children=True,
                        quiet=_has_ui_prompt()
                    )
                try:
                    _write_feedback_to_output(config, "include_session", "\n".join(_capture))
                except (OSError, UnicodeError, ValueError) as e:
                    logging.trace("include_session write failed: %s", e)
                    _maybe_raise(e)
                if ans not in ("y", "yes"):
                    if _supports_color():
                        print(_colorize_preflight_line("[Warning] User cancelled the include removal."))
                    else:
                        print("[Warning] User cancelled the include removal.")
        except (EOFError, KeyboardInterrupt):
            print("\n사용자에 의해 취소되었습니다.")
            raise SystemExit(1)
    else:
        _preflight_print("")

    return ex_names

