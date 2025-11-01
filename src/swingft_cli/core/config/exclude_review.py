from __future__ import annotations

import os
import json
from datetime import datetime
import threading
import time
import textwrap
import sys
from pathlib import Path
from typing import Any, Dict, Iterable
from datetime import datetime
import logging
 # strict-mode helper
try:
    from ..tui import _maybe_raise  # type: ignore
    from ..tui import get_tui
except ImportError as _imp_err:
    logging.trace("fallback _maybe_raise due to ImportError: %s", _imp_err)
    def _maybe_raise(e: BaseException) -> None:
        import os
        if os.environ.get("SWINGFT_TUI_STRICT", "").strip() == "1":
            raise e

from .exclusions import ast_unwrap as _ast_unwrap
from .exclusions import write_feedback_to_output as _write_feedback_to_output
from .ast_utils import update_ast_node_exceptions as _update_ast_node_exceptions
from .llm_feedback import (
    find_first_swift_file_with_identifier as _find_swift_file_for_ident,
    make_snippet as _make_snippet,
    run_swift_ast_analyzer as _run_ast_analyzer,
    run_local_llm_exclude as _run_local_llm_exclude,
    resolve_ast_symbols as _resolve_ast_symbols,
)
from .ui_utils import supports_color as _supports_color, blue as _blue, yellow as _yellow, gray as _gray, bold as _bold, print_warning_block as _print_warning_block


def _preflight_verbose() -> bool:
    v = os.environ.get("SWINGFT_PREFLIGHT_VERBOSE", "")
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _append_terminal_log(config: Dict[str, Any], lines: list[str]) -> None:
    try:
        out_dir = str((config.get("project") or {}).get("output") or "").strip()
        if out_dir:
            base = os.path.join(out_dir, "Obfuscation_Report", "preflight")
        else:
            base = os.path.join(os.getcwd(), "Obfuscation_Report", "preflight")
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

def _has_ui_prompt() -> bool:
    # LLM 사용을 위해 항상 True 반환
    return True


def _supports_color() -> bool:
    try:
        v = os.environ.get("SWINGFT_TUI_COLOR", "1")
        if str(v).strip().lower() in {"0", "false", "no", "off"}:
            return False
        return sys.stdout.isatty()
    except (OSError, AttributeError) as e:
        logging.trace("supports_color check failed: %s", e)
        return False


def _blue(s: str) -> str:
    return f"\x1b[34m{s}\x1b[0m"


def _yellow(s: str) -> str:
    return f"\x1b[33m{s}\x1b[0m"


def _gray(s: str) -> str:
    return f"\x1b[90m{s}\x1b[0m"


def _bold(s: str) -> str:
    return f"\x1b[1m{s}\x1b[0m"

# deferred stdout buffer (for background phase)
_DEFERRED_STDOUT: list[str] = []


def _llm_exclude_via_subprocess(identifier: str, snippet: str, ast_symbols):
    # Deprecated: 서브프로세스 경로 비활성화 (호환용 더미)
    return _run_local_llm_exclude(identifier, snippet, ast_symbols)


def save_exclude_review_json(approved_identifiers, project_root: str | None, ast_file_path: str | None, output_dir: str | None = None) -> str | None:
    try:
        if not approved_identifiers:
            return None
        # output_dir이 제공되면 swingft_output/preflight에 저장, 아니면 기존대로 .swingft/preflight
        if output_dir:
            out_dir = os.path.join(output_dir, "swingft_output", "preflight")
        else:
            out_dir = os.path.join(os.getcwd(), ".swingft", "preflight")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"exclude_review_{ts}.json")
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "kind": "exclude_review",
            "project_input": project_root or "",
            "ast_node_path": ast_file_path or "",
            "approved_identifiers": sorted(list({str(x).strip() for x in approved_identifiers if str(x).strip()})),
            "source": "exclude_review",
            "decision_basis": "user_confirmation_only",
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        if _preflight_verbose():
            print(f"[preflight] 사용자 승인 대상 JSON 저장: {out_path}")
        return out_path
    except (OSError, UnicodeError, TypeError) as e:
        logging.error("exclude_review JSON 저장 실패: %s", e)
        _maybe_raise(e)
        return None


def save_exclude_pending_json(project_root: str | None, ast_file_path: str | None, candidates, output_dir: str | None = None) -> str | None:
    try:
        names = sorted(list({str(x).strip() for x in (candidates or []) if isinstance(x, str) and x.strip()}))
        if not names:
            return None
        # output_dir이 제공되면 swingft_output/preflight에 저장, 아니면 기존대로 .swingft/preflight
        if output_dir:
            out_dir = os.path.join(output_dir, "swingft_output", "preflight")
        else:
            out_dir = os.path.join(os.getcwd(), ".swingft", "preflight")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"exclude_pending_{ts}.json")
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "kind": "exclude_pending",
            "project_input": project_root or "",
            "ast_node_path": ast_file_path or "",
            "candidates": names,
            "source": "exclude_review",
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        if _preflight_verbose():
            print(f"[preflight] 사용자 확인 대상(PENDING) JSON 저장: {out_path}")
        return out_path
    except (OSError, UnicodeError, TypeError) as e:
        if _preflight_verbose():
            logging.trace("exclude_pending JSON 저장 실패: %s", e)
        _maybe_raise(e)
        return None


def generate_payloads_for_excludes(project_root: str | None, identifiers: list[str], output_dir: str | None = None) -> None:
    try:
        if not identifiers:
            return
        # output_dir이 제공되면 swingft_output/preflight/payloads에 저장, 아니면 기존대로 .swingft/preflight/payloads
        if output_dir:
            out_dir = os.path.join(output_dir, "swingft_output", "preflight", "payloads")
        else:
            out_dir = os.path.join(os.getcwd(), ".swingft", "preflight", "payloads")
        os.makedirs(out_dir, exist_ok=True)
        try:
            from ..preflight.find_identifiers_and_ast_dual import write_per_identifier_payload_files  # type: ignore
            write_per_identifier_payload_files(project_root or "", identifiers=identifiers, out_dir=out_dir)
            if _preflight_verbose():
                print(f"[preflight] exclude 대상 {len(identifiers)}개에 대한 payload 생성 완료: {out_dir}")
            return
        except (ImportError, OSError, UnicodeError, ValueError, TypeError) as e:
            if _preflight_verbose():
                logging.trace("preflight payload 생성기 사용 불가, 최소 JSON 생성으로 대체: %s", e)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        for ident in identifiers:
            name = str(ident).strip()
            if not name:
                continue
            payload = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "kind": "exclude_payload",
                "project_input": project_root or "",
                "identifier": name,
            }
            fn = f"{name}.payload.json"
            path = os.path.join(out_dir, fn)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        if _preflight_verbose():
            print(f"[preflight] 최소 payload 생성 완료: {len(identifiers)}개 → {out_dir}")
    except (OSError, UnicodeError, ValueError, TypeError) as e:
        if _preflight_verbose():
            logging.trace("exclude payload 생성 실패: %s", e)
        _maybe_raise(e)


def process_exclude_sensitive_identifiers(config_path: str, config: Dict[str, Any], ex_names) -> None:
    """Orchestrate exclude candidates check/review and reflect to AST (isException=1)."""
    from .rules import scan_swift_identifiers
    project_root = config.get("project", {}).get("input")
    if not project_root or not os.path.isdir(project_root):
        print("[preflight] project.input 경로가 없어 프로젝트 식별자 스캔을 건너뜁니다.")
        return

    project_identifiers = set(scan_swift_identifiers(project_root))
    if not project_identifiers:
        print("[preflight] 프로젝트에서 식별자를 찾지 못했습니다.")
        return

    # Build candidates from config.exclude.obfuscation
    exclude_candidates = set()
    items = (config.get("exclude", {}) or {}).get("obfuscation", []) or []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, str) or not item.strip():
                continue
            name = item.strip()
            if "*" not in name and "?" not in name:
                if name in project_identifiers:
                    exclude_candidates.add(name)
            else:
                import fnmatch
                for proj_id in project_identifiers:
                    if fnmatch.fnmatchcase(proj_id, name):
                        exclude_candidates.add(proj_id)

    # Policy 확인 (exclude_candidates가 비어있어도 skip 모드에서는 충돌 체크 필요)
    _pf = config.get("preflight", {}) if isinstance(config.get("preflight"), dict) else {}
    ex_policy = str(
        _pf.get("conflict_policy")
        or _pf.get("exclude_candidate_policy")
        or "ask"
    ).strip().lower()
    
    # skip 모드가 아니고 exclude_candidates가 비어있으면 return
    if not exclude_candidates and ex_policy != "skip":
        #print("[preflight] Exclude(obfuscation) 후보 중 AST(excluded) 기준으로 새로 반영할 식별자 없음 ✅")
        return

    #print(f"\n[preflight] Exclude(obfuscation) candidates found: {len(exclude_candidates)}")

    # Locate ast_node.json
    env_ast = os.environ.get("SWINGFT_AST_NODE_PATH", "").strip()
    if env_ast and os.path.exists(env_ast):
        ast_file = Path(env_ast)
    else:
        ast_candidates = [
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output", "ast_node.json"),
            os.path.join(os.getcwd(), "AST", "output", "ast_node.json"),
        ]
        ast_file = next((Path(p) for p in ast_candidates if Path(p).exists()), None)

    # Collect existing names in AST
    existing_names = set()
    if ast_file and ast_file.exists():
        try:
            with open(ast_file, 'r', encoding='utf-8') as f:
                ast_list = json.load(f)
            CONTAINER_KEYS = ("G_members", "children", "members", "extension", "node")

            def _collect_names_iter(root):
                from collections import deque
                dq = deque([root])
                seen = set()
                while dq:
                    obj = dq.pop()  # DFS; use popleft() for BFS
                    oid = id(obj)
                    if oid in seen:
                        continue
                    seen.add(oid)

                    if isinstance(obj, dict):
                        cur = _ast_unwrap(obj)
                        if isinstance(cur, dict):
                            nm = str(cur.get("A_name", "")).strip()
                            if nm:
                                existing_names.add(nm)

                            # children from unwrapped dict
                            for key in CONTAINER_KEYS:
                                ch = cur.get(key)
                                if isinstance(ch, list):
                                    dq.extend(ch)
                                elif isinstance(ch, dict):
                                    dq.append(ch)

                            # if wrapped, also check original dict but skip 'node'
                            if obj is not cur:
                                for key in CONTAINER_KEYS:
                                    if key == 'node':
                                        continue
                                    ch = obj.get(key)
                                    if isinstance(ch, list):
                                        dq.extend(ch)
                                    elif isinstance(ch, dict):
                                        dq.append(ch)

                            # other values
                            for v in cur.values():
                                dq.append(v)
                            if obj is not cur:
                                for k, v in obj.items():
                                    if k not in CONTAINER_KEYS:
                                        dq.append(v)
                        else:
                            for v in obj.values():
                                dq.append(v)
                    elif isinstance(obj, list):
                        dq.extend(obj)

            _collect_names_iter(ast_list)
        except (OSError, json.JSONDecodeError, UnicodeError) as e:
            logging.trace("AST load for existing_names failed: %s", e)
            _maybe_raise(e)

    # capture buffer for external session log
    _capture: list[str] = []

    duplicates = exclude_candidates & existing_names
    if duplicates:
        _list = sorted(list(duplicates))
        _capture.append("[Warning] Exclude candidates may cause security issues.")
        for nm in _list:
            _capture.append(f"  - {nm}")
        if (ex_policy == "ask"):
            _print_warning_block("Exclude candidates may cause security issues.", _list)
            try:
                print("")
            except (OSError, UnicodeEncodeError) as e:
                logging.trace("print empty line failed in exclude review: %s", e)

    # Persist pending set (ask 모드에서만)
    output_dir = config.get("project", {}).get("output")
    if ex_policy == "ask":
        try:
            save_exclude_pending_json(project_root, str(ast_file) if ast_file else None, sorted(list(exclude_candidates)), output_dir)
        except (OSError, UnicodeError, ValueError, TypeError) as _e:
            logging.trace("exclude_pending JSON 저장 경고: %s", _e)
            _maybe_raise(_e)

    # Create PENDING payloads before y/N (ask 모드에서만)
    if ex_policy == "ask":
        try:
            from ..preflight.find_identifiers_and_ast_dual import write_per_identifier_payload_files  # type: ignore
            # output_dir이 제공되면 swingft_output/preflight/payloads/pending에 저장, 아니면 기존대로
            if output_dir:
                _pending_dir = os.path.join(output_dir, "swingft_output", "preflight", "payloads", "pending")
            else:
                _pending_dir = os.path.join(os.getcwd(), ".swingft", "preflight", "payloads", "pending")
            os.makedirs(_pending_dir, exist_ok=True)
            write_per_identifier_payload_files(
                project_root or "",
                identifiers=sorted(list(exclude_candidates)),
                out_dir=_pending_dir,
            )
            if _preflight_verbose():
                print(f"[preflight] PENDING payloads 생성 완료: {len(exclude_candidates)}개 → {_pending_dir}")
        except (ImportError, OSError, UnicodeError, ValueError, TypeError) as _e:
            logging.trace("PENDING payloads 생성 경고: %s", _e)
            _maybe_raise(_e)

    # Decision gathering
    decided_to_exclude = set()
    if ex_policy == "skip":
        # conflicts.py로 충돌 검증 먼저 수행
        from .conflicts import check_exception_conflicts
        try:
            check_exception_conflicts(config_path, config)
        except SystemExit:
            raise
        except Exception as e:
            logging.trace("conflicts check failed in skip mode: %s", e)
            # 계속 진행
        
        # ask 모드와 동일하게 LLM 분석 수행 (exclude_candidates가 있을 때만)
        use_llm = str(os.environ.get("SWINGFT_PREFLIGHT_EXCLUDE_USE_LLM", "1")).strip().lower() in {"1","true","yes","y","on"}
        llm_results = {}  # {identifier: {"llm_suggestion": str, "llm_reason": str, "llm_exclude": bool}}
        
        # exclude_candidates가 있을 때만 LLM 분석 수행
        if exclude_candidates:
            for ident in sorted(list(exclude_candidates)):
                try:
                    if _has_ui_prompt():
                        import swingft_cli.core.config as _cfg
                        llm_note = ""
                        if use_llm and isinstance(project_root, str) and project_root.strip():
                            # 스니펫 및 AST 심볼 정보 수집
                            found = _find_swift_file_for_ident(project_root, ident)
                            swift_path, swift_text = (found or (None, None)) if isinstance(found, tuple) else (None, None)
                            snippet = _make_snippet(swift_text or "", ident) if swift_text else ""
                            ast_info = _resolve_ast_symbols(project_root, swift_path, ident)
                            # LLM 호출 (스피너 표시)
                            _tui = None
                            stop_flag = {"stop": False}
                            try:
                                _tui = get_tui()
                            except (ImportError, AttributeError, RuntimeError) as e:
                                logging.trace("get_tui() failed in skip mode exclude review: %s", e)
                                _tui = None

                            def _spin():
                                spinner = ["|", "/", "-", "\\"]
                                idx = 0
                                while not stop_flag["stop"]:
                                    try:
                                        sys.stdout.write("\r\x1b[2K" + f"LLM Analysis: {ident}  {spinner[idx]}")
                                        sys.stdout.flush()
                                    except (OSError, UnicodeEncodeError, BrokenPipeError) as e:
                                        logging.trace("spinner stdout write failed: %s", e)
                                    idx = (idx + 1) % len(spinner)
                                    time.sleep(0.1)

                            th = None
                            try:
                                if _tui is not None:
                                    th = threading.Thread(target=_spin, daemon=True)
                                    th.start()
                            except (RuntimeError, OSError) as e:
                                logging.trace("spinner thread start failed: %s", e)
                                th = None

                            # LLM 실행
                            try:
                                llm_res = _run_local_llm_exclude(ident, snippet, ast_info)
                            except (RuntimeError, OSError, ValueError, TypeError) as _llm_e:
                                logging.trace("LLM 이슈: %s", _llm_e)
                                llm_res = None
                            finally:
                                try:
                                    stop_flag["stop"] = True
                                    if th is not None:
                                        th.join()
                                except (RuntimeError, OSError) as e:
                                    logging.trace("spinner thread join failed: %s", e)
                                try:
                                    sys.stdout.write("\r\x1b[2K")
                                    sys.stdout.flush()
                                    time.sleep(0.02)
                                except (OSError, UnicodeEncodeError, BrokenPipeError) as e:
                                    logging.trace("spinner cleanup failed: %s", e)
                            
                            # 판정 요약
                            if isinstance(llm_res, list) and llm_res:
                                first = llm_res[0]
                                is_ex = bool(first.get("exclude", True))
                                reason = str(first.get("reason", "")).strip()
                                # LLM 결과 저장
                                llm_results[ident] = {
                                    "llm_suggestion": "include obfuscation" if is_ex else "keep",
                                    "llm_reason": reason,
                                    "llm_exclude": is_ex
                                }
                                # LLM이 비민감(keep)으로 판단 시 자동으로 제외하지 않음
                                if not is_ex:
                                    _capture.append(f"[preflight] LLM auto-skip (keep): {ident}")
                                    if reason:
                                        _capture.append(f"  - reason: {reason}")
                                    continue
                                # 이유를 한 줄로 붙여 출력
                                if isinstance(reason, str) and reason.strip():
                                    reason_block = " ".join(reason.split())
                                else:
                                    reason_block = ""
                                llm_note = (
                                    f"\n  - LLM suggests: {'include obfuscation' if is_ex else 'keep'}\n"
                                    f"  - reason: {reason_block}"
                                )
                            else:
                                llm_results[ident] = {
                                    "llm_suggestion": "no_result",
                                    "llm_reason": "LLM analysis returned no result",
                                    "llm_exclude": None
                                }
                        
                        # skip 모드: 프롬프트 없이 자동으로 'n' (거부) 처리
                        _capture.append("[preflight]")
                        _capture.append(f"Security issue detected.\n  - identifier: {ident}")
                        if llm_note:
                            _capture.append(llm_note.strip())
                        # 자동으로 'n' 처리 - decided_to_exclude에 추가하지 않음
                except (EOFError, KeyboardInterrupt):
                    print("\n사용자에 의해 취소되었습니다.")
                    raise SystemExit(1)
        
        # skip 모드: 모든 식별자 자동 거부
        decided_to_exclude = set()
        
        # Config에서 exclude와 include 정보 수집
        exclude_config_items = (config.get("exclude", {}) or {}).get("obfuscation", []) or []
        include_config_items = (config.get("include", {}) or {}).get("obfuscation", []) or []
        
        # Include 정책에서 실제 프로젝트 식별자와 매칭된 식별자 수집
        include_matched = set()
        if isinstance(include_config_items, list) and include_config_items:
            import fnmatch
            for item in include_config_items:
                if isinstance(item, str) and item.strip():
                    name = item.strip()
                    if "*" not in name and "?" not in name:
                        if name in project_identifiers:
                            include_matched.add(name)
                    else:
                        for proj_id in project_identifiers:
                            if fnmatch.fnmatchcase(proj_id, name):
                                include_matched.add(proj_id)
        
        # 충돌 정보 수집 (include/exclude로 명확히 구분)
        # Exclude 정책 관련 충돌
        exclude_with_ast_conflicts = exclude_candidates & existing_names if exclude_candidates else set()
        exclude_with_include_conflicts = exclude_candidates & include_matched if exclude_candidates else set()
        
        # Include 정책 관련 충돌
        include_with_ast_conflicts = include_matched & existing_names
        include_with_exclude_conflicts = include_matched & exclude_candidates if exclude_candidates else set()
        
        # skip 모드 결과 JSON 파일 저장 (간단한 구조로)
        output_dir = config.get("project", {}).get("output")
        try:
            if output_dir:
                out_dir = os.path.join(output_dir, "swingft_output", "preflight")
            else:
                out_dir = os.path.join(os.getcwd(), ".swingft", "preflight")
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(out_dir, f"exclude_review_skip_{ts}.json")
            
            # Exclude 충돌 항목만 수집
            exclude_items = []
            for ident in sorted(list(exclude_with_ast_conflicts)):
                item = {
                    "identifier": ident,
                    "ast_conflict": True,
                    "decision": "auto_rejected"
                }
                if ident in llm_results:
                    llm_result = llm_results[ident]
                    item["llm_suggestion"] = llm_result.get("llm_suggestion", "")
                    item["llm_reason"] = llm_result.get("llm_reason", "")
                exclude_items.append(item)
            
            exclude_warning = None
            if exclude_with_ast_conflicts:
                count = len(exclude_with_ast_conflicts)
                exclude_warning = f"{count} exclude item{'s' if count > 1 else ''} conflict with AST-excluded identifiers. Security risk if unresolved."
            
            # Include 충돌 항목만 수집
            include_items = []
            for ident in sorted(list(include_with_ast_conflicts)):
                item = {
                    "identifier": ident,
                    "ast_conflict": True,
                    "decision": "rejected_due_to_conflict"
                }
                include_items.append(item)
            
            include_warning = None
            if include_with_ast_conflicts:
                count = len(include_with_ast_conflicts)
                include_warning = f"Include candidate conflict{'s' if count > 1 else ''} with AST-excluded identifiers. May cause build errors if forced."
            
            payload = {
                "policy": ex_policy,
                "exclude": {
                    "items": exclude_items,
                },
                "include": {
                    "items": include_items,
                },
            }
            
            if exclude_warning:
                payload["exclude"]["warning"] = exclude_warning
            if include_warning:
                payload["include"]["warning"] = include_warning
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            if _preflight_verbose():
                print(f"[preflight] Skip mode 결과 JSON 저장: {out_path}")
        except (OSError, UnicodeError, TypeError, ValueError, AttributeError) as e:
            logging.trace("skip mode 결과 JSON 저장 실패: %s", e)
            _maybe_raise(e)
        
        return
    elif ex_policy == "force":
        # conflicts.py로 충돌 검증 먼저 수행
        from .conflicts import check_exception_conflicts
        try:
            check_exception_conflicts(config_path, config)
        except SystemExit:
            raise
        except Exception as e:
            logging.trace("conflicts check failed in force mode: %s", e)
            # 계속 진행
        
        decided_to_exclude = set(exclude_candidates)
        
        # Config에서 exclude와 include 정보 수집
        exclude_config_items = (config.get("exclude", {}) or {}).get("obfuscation", []) or []
        include_config_items = (config.get("include", {}) or {}).get("obfuscation", []) or []
        
        # Include 정책에서 실제 프로젝트 식별자와 매칭된 식별자 수집
        include_matched = set()
        if isinstance(include_config_items, list) and include_config_items:
            import fnmatch
            for item in include_config_items:
                if isinstance(item, str) and item.strip():
                    name = item.strip()
                    if "*" not in name and "?" not in name:
                        if name in project_identifiers:
                            include_matched.add(name)
                    else:
                        for proj_id in project_identifiers:
                            if fnmatch.fnmatchcase(proj_id, name):
                                include_matched.add(proj_id)
        
        # 충돌 정보 수집 (include/exclude로 명확히 구분)
        exclude_with_ast_conflicts = exclude_candidates & existing_names if exclude_candidates else set()
        include_with_ast_conflicts = include_matched & existing_names
        
        # force 모드 결과 JSON 파일 저장 (간단한 구조로, LLM 제외)
        output_dir = config.get("project", {}).get("output")
        try:
            if output_dir:
                out_dir = os.path.join(output_dir, "swingft_output", "preflight")
            else:
                out_dir = os.path.join(os.getcwd(), ".swingft", "preflight")
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(out_dir, f"exclude_review_force_{ts}.json")
            
            # Exclude 충돌 항목만 수집 (LLM 제외)
            exclude_items = []
            for ident in sorted(list(exclude_with_ast_conflicts)):
                item = {
                    "identifier": ident,
                    "ast_conflict": True,
                    "decision": "forced"
                }
                exclude_items.append(item)
            
            exclude_warning = None
            if exclude_with_ast_conflicts:
                count = len(exclude_with_ast_conflicts)
                exclude_warning = f"{count} exclude item{'s' if count > 1 else ''} conflict with AST-excluded identifiers. Security risk if unresolved."
            
            # Include 충돌 항목만 수집
            include_items = []
            for ident in sorted(list(include_with_ast_conflicts)):
                item = {
                    "identifier": ident,
                    "ast_conflict": True,
                    "decision": "rejected_due_to_conflict"
                }
                include_items.append(item)
            
            include_warning = None
            if include_with_ast_conflicts:
                count = len(include_with_ast_conflicts)
                include_warning = f"Include candidate conflict{'s' if count > 1 else ''} with AST-excluded identifiers. May cause build errors if forced."
            
            payload = {
                "policy": ex_policy,
                "exclude": {
                    "items": exclude_items,
                },
                "include": {
                    "items": include_items,
                },
            }
            
            if exclude_warning:
                payload["exclude"]["warning"] = exclude_warning
            if include_warning:
                payload["include"]["warning"] = include_warning
            
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            if _preflight_verbose():
                print(f"[preflight] Force mode 결과 JSON 저장: {out_path}")
        except (OSError, UnicodeError, TypeError, ValueError, AttributeError) as e:
            logging.trace("force mode 결과 JSON 저장 실패: %s", e)
            _maybe_raise(e)
    else:
        # ask 모드에서 LLM 판정과 사용자 확인을 함께 수행
        use_llm = str(os.environ.get("SWINGFT_PREFLIGHT_EXCLUDE_USE_LLM", "1")).strip().lower() in {"1","true","yes","y","on"}
        pending_confirm: list[tuple[str, str]] = []  # (identifier, llm_note)
        _defer_prompt = False
        # print(f"[TRACE] use_llm: {use_llm}, project_root: {project_root}, _has_ui_prompt(): {_has_ui_prompt()}")
        for ident in sorted(list(exclude_candidates)):
            try:
                if _has_ui_prompt():
                    import swingft_cli.core.config as _cfg
                    llm_note = ""
                    if use_llm and isinstance(project_root, str) and project_root.strip():
                        # 스니펫 및 AST 심볼 정보 수집
                        found = _find_swift_file_for_ident(project_root, ident)
                        swift_path, swift_text = (found or (None, None)) if isinstance(found, tuple) else (None, None)
                        snippet = _make_snippet(swift_text or "", ident) if swift_text else ""
                        ast_info = _resolve_ast_symbols(project_root, swift_path, ident)
                        # LLM 호출 (스피너 표시)
                        _tui = None
                        stop_flag = {"stop": False}
                        _defer_prompt_flag = False
                        try:
                            _tui = get_tui()
                        except (ImportError, AttributeError, RuntimeError) as e:
                            logging.trace("get_tui() failed in exclude review: %s", e)
                            _tui = None

                        def _spin():
                            spinner = ["|", "/", "-", "\\"]
                            idx = 0
                            while not stop_flag["stop"]:
                                try:
                                    # 단일 라인 스피너: 줄바꿈 없이 동일 라인 덮어쓰기
                                    sys.stdout.write("\r\x1b[2K" + f"LLM Analysis: {ident}  {spinner[idx]}")
                                    sys.stdout.flush()
                                except (OSError, UnicodeEncodeError, BrokenPipeError) as e:
                                    logging.trace("spinner stdout write failed: %s", e)
                                idx = (idx + 1) % len(spinner)
                                time.sleep(0.1)

                        th = None
                        try:
                            if _tui is not None:
                                th = threading.Thread(target=_spin, daemon=True)
                                th.start()
                        except (RuntimeError, OSError) as e:
                            logging.trace("spinner thread start failed: %s", e)
                            th = None

                        # 백그라운드(동일 프로세스)에서 직접 LLM 실행
                        try:
                            llm_res = _run_local_llm_exclude(ident, snippet, ast_info)
                        except (RuntimeError, OSError, ValueError, TypeError) as _llm_e:
                            logging.trace("LLM 이슈: %s", _llm_e)
                            _maybe_raise(_llm_e)
                            llm_res = None
                        finally:
                            try:
                                stop_flag["stop"] = True
                                if th is not None:
                                    th.join()  # 스피너 완전 종료 대기
                            except (RuntimeError, OSError) as e:
                                logging.trace("spinner thread join failed: %s", e)
                            try:
                                # 스피너 라인 지우기
                                sys.stdout.write("\r\x1b[2K")
                                sys.stdout.flush()
                                time.sleep(0.02)
                            except (OSError, UnicodeEncodeError, BrokenPipeError) as e:
                                logging.trace("spinner cleanup failed: %s", e)
                        # 판정 요약
                        if isinstance(llm_res, list) and llm_res:
                            first = llm_res[0]
                            is_ex = bool(first.get("exclude", True))
                            reason = str(first.get("reason", "")).strip()
                            # LLM이 비민감(keep)으로 판단 시 사용자 프롬프트 생략
                            if not is_ex:
                                _capture.append(f"[preflight] LLM auto-skip (keep): {ident}")
                                if reason:
                                    _capture.append(f"  - reason: {reason}")
                                # 이 항목은 제외하지 않음 → 다음 식별자로 진행
                                continue
                            # 이유를 한 줄로 붙여 출력 (개행/과도한 공백 제거)
                            if isinstance(reason, str) and reason.strip():
                                reason_block = " ".join(reason.split())
                            else:
                                reason_block = ""
                            llm_note = (
                                f"\n  - LLM suggests: {'include obfuscation' if is_ex else 'keep'}\n"
                                f"  - reason: {reason_block}"
                            )
                    # 즉시 묻지 않고 일괄 확인을 위해 수집 (포그라운드에서도 일괄 확인)
                    _capture.append("[preflight]")
                    _capture.append(f"Security issue detected.\n  - identifier: {ident}")
                    if llm_note:
                        _capture.append(llm_note.strip())
                    pending_confirm.append((ident, llm_note))
                    ans = ""
                else:
                    ans = input(f"식별자 '{ident}'를 난독화에서 제외할까요? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n사용자에 의해 취소되었습니다.")
                raise SystemExit(1)
            if ans in ("y", "yes"):
                decided_to_exclude.add(ident)

        # 모든 분석이 끝난 뒤, 제외 후보에 대해 일괄 y/n 확인
        if _DEFERRED_STDOUT:
            try:
                for ln in _DEFERRED_STDOUT:
                    print(ln)
            finally:
                _DEFERRED_STDOUT.clear()

        if pending_confirm:
            import swingft_cli.core.config as _cfg
            for ident, llm_note in pending_confirm:
                try:
                    # TUI 상태와 겹치지 않도록 새 줄로 시작
                    try:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    except OSError as e:
                        logging.trace("exclude review prompt newline failed: %s", e)
                    
                    if _supports_color():
                        head = _blue("[Warning]") + _yellow(" Exclude candidate detected.\n")
                        # labels bold only, gray '-' bullet
                        lab_ident = "  " + _gray("-") + " " + _bold("identifier") + ": " + str(ident)
                        llm_block = llm_note or ""
                        if llm_block:
                            llm_block = llm_block.replace(
                                "  - LLM suggests:",
                                "  " + _gray("-") + " " + _bold("LLM suggests") + ":",
                            )
                            llm_block = llm_block.replace(
                                "  - reason:",
                                "  " + _gray("-") + " " + _bold("reason") + ":",
                            )
                        prompt = (
                            head + lab_ident + (llm_block if llm_block else "") + "\n\n" +
                            "Continue excluding? [y/n]: "
                        )
                    else:
                        prompt = (
                            f"[Warning]\n"
                            f"Security issue detected.\n"
                            f"  - identifier: {ident}{llm_note}\n\n"
                            f"Continue excluding? [y/n]: "
                        )
                    ans2 = str(getattr(_cfg, "PROMPT_PROVIDER")(prompt)).strip().lower()
                    if ans2 in ("y", "yes"):
                        decided_to_exclude.add(ident)
                except (EOFError, KeyboardInterrupt):
                    print("\n사용자에 의해 취소되었습니다.")
                    raise SystemExit(1)
        # 포그라운드 모드: 계속 진행

    if decided_to_exclude:
        #print(f"\n[preflight] 사용자 승인 완료: 제외로 반영 {len(decided_to_exclude)}개")
        #_capture.append(f"[preflight] 사용자 승인 완료: 제외로 반영 {len(decided_to_exclude)}개")
        output_dir = config.get("project", {}).get("output")
        # exclude_review_{timestamp}.json 파일은 더 이상 생성하지 않음 (skip/force 모드는 각각 별도 파일 생성)
        try:
            generate_payloads_for_excludes(project_root, sorted(list(decided_to_exclude)), output_dir)
        except (OSError, UnicodeError, ValueError, TypeError) as _e:
            logging.trace("exclude_review/save payload 경고: %s", _e)
            _maybe_raise(_e)

    # ask 모드 세션 로그 저장
    try:
        if ex_policy == "ask":
            _write_feedback_to_output(config, "exclude_session", "\n".join(_capture))
    except (OSError, UnicodeError, ValueError) as e:
        logging.trace("exclude_session 저장 실패: %s", e)
        _maybe_raise(e)

    if not ast_file:
        # 조용히 스킵 (Stage 1 스킵 시 정상)
        return

    try:
        _update_ast_node_exceptions(str(ast_file), sorted(list(decided_to_exclude)), is_exception=1, allowed_kinds=None, lock_children=False)
        #print("  - 처리: ast_node.json 반영 완료 (isException=1)")
    except (OSError, ValueError, TypeError) as e:
        logging.warning("ast_node.json 반영 중 오류: %s", e)
        _maybe_raise(e)


