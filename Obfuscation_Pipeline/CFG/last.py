#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
last.py
- Minimal scaffold for per-file dynamic-call obfuscation.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple, Set
from fnmatch import fnmatchcase

# Import the new swift_scanner module
from swift_scanner import scan_swift_functions, iter_swift_files, is_ui_path, _strip_comments, _find_protocol_blocks, _func_key, FUNC_DECL_RE, TYPE_DECL_RE, _has_param_default, _split_params_top, _param_external_labels_list

# Import the new code_injector module
from code_injector import inject_per_file

# Import the new utils module
from utils import log, fail, read_text, write_text, dump_json, dump_text, copy_project_tree

# Import OBF constants from code_injector

from code_injector import OBF_BEGIN, OBF_END

import logging

# local trace/strict helpers
def _trace(msg: str, *args, **kwargs) -> None:
    try:
        logging.trace(msg, *args, **kwargs)
    except (OSError, ValueError, TypeError, AttributeError) as e:
        # 로깅 실패 시에도 프로그램은 계속 진행
        return

def _maybe_raise(e: BaseException) -> None:
    try:
        if str(os.environ.get("SWINGFT_TUI_STRICT", "")).strip() == "1":
            raise e
    except (OSError, ValueError, TypeError, AttributeError) as e:
        # 환경변수 읽기 실패 시에는 무시하고 계속 진행
        return




# ---------- argument parsing ----------
def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Per-file dynamic-call obfuscation tool.")
    ap.add_argument("--src", required=True, help="Source project root.")
    ap.add_argument("--dst", required=True, help="Output project root.")
    ap.add_argument("--exceptions", nargs='+', help="JSON exception files.")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing destination.")
    ap.add_argument("--config", help="Swingft_config.json path (optional)")
    ap.add_argument("--debug", action="store_true", help="Verbose logging.")
    ap.add_argument("--perfile-inject", action="store_true", help="Enable code injection.")
    ap.add_argument("--dry-run", action="store_true", help="Scan only, no file edits.")
    ap.add_argument("--no-skip-ui", action="store_true", help="Do not skip UI-related files (default: skip UI files).")
    ap.add_argument("--max-params", type=int, default=10, help="Max params for generated wrappers (default: 5)")
    ap.add_argument("--dump-funcs-json", help="Dump all discovered functions to a JSON file.")
    ap.add_argument("--dump-funcs-txt", help="Dump all discovered functions to a text file.")
    ap.add_argument("--dump-funcs-json-clean", help="Dump functions after removing exceptions (JSON).")
    ap.add_argument("--dump-funcs-txt-clean", help="Dump functions after removing exceptions (text).")
    ap.add_argument("--dump-funcs-json-excluded", help="Dump only excluded functions (JSON).")
    ap.add_argument("--dump-funcs-txt-excluded", help="Dump only excluded functions (text).")
    ap.add_argument("--dump-funcs-json-safe", help="Dump risk-filtered safe functions (JSON).")
    ap.add_argument("--dump-funcs-txt-safe", help="Dump risk-filtered safe functions (text).")
    ap.add_argument("--dump-funcs-json-risky", help="Dump risky functions (JSON).")
    ap.add_argument("--dump-funcs-txt-risky", help="Dump risky functions (text).")
    ap.add_argument("--risk-keep-overrides", action="store_true", help="Keep 'override' methods in SAFE set.")
    ap.add_argument("--include-packages", action="store_true", help="Include local Swift Packages (directories containing Package.swift) in scanning and injection (default: skipped)")
    ap.add_argument("--skip-external-extensions", dest="skip_external_extensions", action="store_true", help="Skip functions declared in extensions whose parent type is NOT declared in this project.")
    ap.add_argument("--allow-external-extensions", dest="skip_external_extensions", action="store_false", help="Allow functions in extensions of types not declared in this project.")
    ap.add_argument("--skip-external-protocol-reqs", action="store_true", help="Skip functions that implement requirements of protocols declared OUTSIDE this project (default: on).")
    ap.add_argument("--allow-internal-protocol-reqs", action="store_true", help="Allow functions that implement requirements of protocols declared INSIDE this project (default: off).")
    ap.add_argument("--skip-external-protocol-extension-members", action="store_true", help="When an extension adds conformance to an EXTERNAL protocol (extension T: P), skip all functions in that extension (default: on).")
    ap.set_defaults(
        skip_external_extensions=True,
        skip_external_protocol_reqs=True,
        allow_internal_protocol_reqs=True,
        skip_external_protocol_extension_members=True,
        perfile_inject=True,
        overwrite=True,
        include_packages=True,
        no_skip_ui=True
    )
    return ap
# ---------- new: collect local declared types ----------
def collect_local_declared_types(project_root: str, *, include_packages: bool, debug: bool) -> set:
    """
    Collect names of types (class/struct/enum/actor) declared in *this project* (dst tree).
    We intentionally exclude 'extension' and 'protocol' from this set.
    Only top-level type names are recorded (heuristic is sufficient for external-extension detection).
    """
    local_types: set = set()
    files = iter_swift_files(project_root, skip_ui=False, debug=debug, exclude_file_globs=None, include_packages=include_packages)
    # Reuse TYPE_DECL_RE but filter by kind
    for abs_path in files:
        try:
            text = read_text(abs_path)
        except (OSError, UnicodeError) as e:
            _trace("collect_local_declared_types read failed %s: %s", abs_path, e)
            _maybe_raise(e)
            continue
        for m in TYPE_DECL_RE.finditer(text):
            kind = m.group('tkind')
            name = m.group('type_name')
            if kind in ('class', 'struct', 'enum', 'actor'):
                local_types.add(name)
    if debug:
        log(f"prepass: local declared types={len(local_types)}")
    return local_types

# ---------- core logic ----------


def load_exceptions(paths: Optional[List[str]]) -> List[Dict]:
    if not paths: return []
    all_rules: List[Dict] = []
    for path in paths:
        if not os.path.exists(path): fail(f"exceptions file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                all_rules.extend(data)
            elif isinstance(data, dict):
                rules = data.get("rules")
                if isinstance(rules, list):
                    all_rules.extend(rules)
                else:
                    fail(f"exceptions file must be a JSON list or {{'rules': [...]}}: {path}")
            else:
                fail(f"exceptions file must be a JSON list or {{'rules': [...]}}: {path}")
        except (OSError, json.JSONDecodeError, UnicodeError, TypeError, ValueError) as e:
            _trace("load_exceptions failed %s: %s", path, e)
            _maybe_raise(e)
            fail(f"error reading exceptions file {path}: {e}")
    return all_rules

# --- File exclusion helpers ---
def build_file_exclude_patterns(exceptions: List[Dict]) -> List[str]:
    """
    Collect file/path glob patterns from exceptions.
    Accepted keys per rule: 'file', 'path', 'glob' OR kind=='file' with 'name'/'A_name'.
    Patterns are matched case-insensitively against the *relative* path from project root.
    """
    patterns: List[str] = []
    for r in exceptions or []:
        kind = (r.get("B_kind") or r.get("kind") or "").lower()
        name = (r.get("A_name") or r.get("name") or "")
        # Direct keys
        for key in ("file", "path", "glob"):
            val = r.get(key)
            if isinstance(val, str) and val.strip():
                patterns.append(val.replace("\\", "/").lower())
        # kind-based
        if kind == "file" and isinstance(name, str) and name.strip():
            patterns.append(name.replace("\\", "/").lower())
    return patterns




def collect_local_protocol_requirements(project_root: str, *, include_packages: bool, debug: bool) -> Dict[str, Set[Tuple[str, int, Tuple[str, ...]]]]:
    """
    Build a map: protocolName -> set of requirement keys (name, arity, labels).
    Only protocols declared inside this project (dst) are included.
    """
    reqs: Dict[str, Set[Tuple[str, int, Tuple[str, ...]]]] = {}
    files = iter_swift_files(project_root, skip_ui=False, debug=debug, exclude_file_globs=None, include_packages=include_packages)
    for abs_path in files:
        try:
            text = read_text(abs_path)
        except (OSError, UnicodeError) as e:
            _trace("collect_local_protocol_requirements read failed %s: %s", abs_path, e)
            _maybe_raise(e)
            continue
        scrub = _strip_comments(text)
        for pb in _find_protocol_blocks(scrub):
            proto = pb["name"]
            body = pb["body"]
            for fm in FUNC_DECL_RE.finditer(body):
                name = fm.group("name")
                params_src = fm.group("params") or ""
                key = _func_key(name, params_src)
                reqs.setdefault(proto, set()).add(key)
    if debug:
        log(f"prepass: local protocols={len(reqs)} (with requirements)")
    return reqs



def collect_actor_and_global_types(project_root: str, *, include_packages: bool, debug: bool) -> Tuple[set, set]:
    """
    Pre-scan all Swift files to collect:
      - actor types declared as: 'actor TypeName { ... }'
      - types annotated with a global actor, e.g. '@MainActor class TypeName { ... }'
        (supports attribute on the same line or immediately preceding line)
    Returns (actor_types, global_actor_types).
    """
    actor_types: set = set()
    global_actor_types: set = set()

    files = iter_swift_files(project_root, skip_ui=False, debug=debug, exclude_file_globs=None, include_packages=include_packages)
    # Simple line-based scan with 'pending actor attribute' heuristic
    for abs_path in files:
        try:
            text = read_text(abs_path)
        except (OSError, UnicodeError) as e:
            _trace("collect_actor_and_global_types read failed %s: %s", abs_path, e)
            _maybe_raise(e)
            continue
        pending_actor_attr = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            # Detect global-actor attribute tokens
            if re.search(r"@\w+Actor\b", line):
                # If the type decl is on the same line, record immediately; otherwise mark pending for next decl.
                if re.search(r"\b(class|struct|enum)\s+([A-Za-z_]\w*)\b", line):
                    m = re.search(r"\b(class|struct|enum)\s+([A-Za-z_]\w*)\b", line)
                    if m: global_actor_types.add(m.group(2))
                    pending_actor_attr = False
                else:
                    pending_actor_attr = True
                continue

            # Actor type declaration
            m_actor = re.match(r"^\s*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?actor\s+([A-Za-z_]\w*)\b", raw)
            if m_actor:
                actor_types.add(m_actor.group(1))
                pending_actor_attr = False
                continue

            # Regular type declaration; if we had a pending global-actor attribute, attach it now
            if pending_actor_attr:
                m_type = re.match(r"^\s*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?(class|struct|enum)\s+([A-Za-z_]\w*)\b", raw)
                if m_type:
                    global_actor_types.add(m_type.group(2))
                    pending_actor_attr = False
                else:
                    # keep pending only if the line looks like an attribute continuation
                    if not raw.lstrip().startswith("@"):
                        pending_actor_attr = False
    if debug:
        log(f"prepass: actors={len(actor_types)} global-actors={len(global_actor_types)}")
    return actor_types, global_actor_types

def _rule_name(rule: Dict) -> Optional[str]: return rule.get("A_name") or rule.get("name")
def _rule_kind(rule: Dict) -> Optional[str]: return (rule.get("B_kind") or rule.get("kind") or "").lower() or None

def rule_matches_function(rule: Dict, fn: Dict) -> bool:
    rname, rkind, fname, fparent = _rule_name(rule) or "", _rule_kind(rule), fn.get("name") or "", fn.get("parent_type") or ""
    matches = lambda p, v: bool(p) and (p == v or fnmatchcase(v, p))
    if rkind == "function": return matches(rname, fname)
    if rkind in ["class", "struct", "enum", "protocol", "extension", "actor"]: return matches(rname, fparent)
    return matches(rname, fname) or matches(rname, fparent)

def partition_by_exceptions(funcs: List[Dict], exceptions: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    if not exceptions: return funcs, []
    included, excluded = [], []
    for fn in funcs:
        (excluded if any(rule_matches_function(r, fn) for r in exceptions) else included).append(fn)
    return included, excluded

def is_risky_function(fn: Dict, *, skip_overrides: bool = True) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    src = fn.get("params_src") or ""
    ret = (fn.get("return_type") or "").strip()
    param_types = fn.get("param_types") or []

    # 1) Closure params or escaping/inout are tricky for wrapper generation
    if "->" in src or "@escaping" in src:
        reasons.append("closure_param_or_escaping")
    if "inout" in src:
        reasons.append("inout_param")

    # 2) Any parameter default at top level (conservative; align with generate_exceptions)
    if _has_param_default(src):
        reasons.append("param_default")

    # 3) Opaque return types `some ...` are not representable in function-type casts
    if re.search(r"^some\b|\bsome\b", ret):
        reasons.append("opaque_return_some")

    # 4) Return Self at file scope is ambiguous
    if re.search(r"\bSelf\b", ret):
        reasons.append("return_Self")

    # 5) Context-associated identifiers (e.g., LabelStyle.Configuration) used unqualified
    if any(re.search(r"\bConfiguration\b", t) for t in param_types):
        reasons.append("context_assoc_type_in_params")

    # 6) Overrides (optional policy)
    if skip_overrides and "override" in (fn.get("modifiers") or []):
        reasons.append("override_method")

    return (len(reasons) > 0, reasons)

def partition_risky(funcs: List[Dict], *, skip_overrides: bool = True) -> Tuple[List[Dict], List[Dict]]:
    safe, risky = [], []
    for f in funcs:
        is_risky, reasons = is_risky_function(f, skip_overrides=skip_overrides)
        if is_risky:
            f["risk_reasons"] = reasons
            risky.append(f)
        else:
            safe.append(f)
    return safe, risky
    

def copy_StringSecurity_folder(source_root: str) -> None:
    """StringSecurity 폴더를 프로젝트에 복사 (암호화 기능과 동일)"""
    import shutil
    import os
    import subprocess
    
    # StringSecurity 폴더 경로 (CFG 디렉토리 기준)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(script_dir, "..", "String_Encryption", "StringSecurity")
    
    if not os.path.exists(local_path):
        return 1
    
    # 프로젝트 루트에서 .xcodeproj 또는 .xcworkspace 찾기
    target_path = None
    for dirpath, dirnames, _ in os.walk(source_root):
        for d in dirnames:
            if d.endswith(('.xcodeproj', '.xcworkspace')):
                target_path = os.path.join(dirpath, "StringSecurity")
                break
        if target_path:
            break
    
    if not target_path:
        return 1
    
    # StringSecurity 폴더 복사 (이미 존재하면 스킵)
    if not os.path.exists(target_path):
        try:
            shutil.copytree(local_path, target_path)
        except (OSError, shutil.Error) as e:
            _trace("StringSecurity copytree failed: %s", e)
            _maybe_raise(e)
            return 1
    else:
        # 이미 존재하는 경우 빌드만 확인
        ...
    
    # StringSecurity 빌드 (암호화 기능과 동일한 빌드 캐시 방식)
    try:
        # 빌드 경로 기반 캐시 (타깃 프로젝트 기준): 최초 1회만 빌드, 이후 재사용
        marker_dir = os.path.join(target_path, ".build")
        os.makedirs(marker_dir, exist_ok=True)
        build_marker_file = os.path.join(marker_dir, "build_path.txt")

        previous_build_path = ""
        if os.path.exists(build_marker_file):
            try:
                with open(build_marker_file, "r", encoding="utf-8") as f:
                    previous_build_path = f.read().strip()
            except (OSError, UnicodeError) as e:
                _trace("build_marker_file read failed: %s", e)
                previous_build_path = ""

        current_build_path = os.path.abspath(os.path.join(target_path, ".build"))

        need_build = (previous_build_path != current_build_path) or (previous_build_path == "")

        # 추가 안전장치: 산출물 폴더가 비어 있으면 빌드
        artifacts_missing = not os.path.isdir(current_build_path)

        if need_build or artifacts_missing:
            cwd = os.getcwd()
            try:
                os.chdir(target_path)
                subprocess.run(["swift", "package", "clean"], check=True)
                shutil.rmtree(".build", ignore_errors=True)
                subprocess.run(["swift", "build"], check=True)
            finally:
                os.chdir(cwd)
            # 동일 경로를 타깃 기준으로 기록
            with open(build_marker_file, "w", encoding="utf-8") as f:
                f.write(current_build_path)
    except (OSError, subprocess.CalledProcessError) as e:
        _trace("StringSecurity build failed: %s", e)
        _maybe_raise(e)
        try:
            os.chdir(script_dir)
        except OSError as e:
            _trace("os.chdir(script_dir) failed: %s", e)
        return 1



def main() -> None:
    ap = build_arg_parser()
    args = ap.parse_args()
    # src와 dst가 같으면 인플레이스 모드로 동작: 복사 생략
    try:
        src_real = os.path.abspath(args.src)
        dst_real = os.path.abspath(args.dst)
        same_target = os.path.samefile(src_real, dst_real)
    except (OSError, FileNotFoundError):
        src_real = os.path.abspath(args.src)
        dst_real = os.path.abspath(args.dst)
        same_target = (src_real == dst_real)

    if not same_target:
        copy_project_tree(args.src, args.dst, overwrite=args.overwrite)
    
    # 구성 파일을 읽어 CFG 자체 스킵 여부 결정
    # run_pipeline에서 이미 게이트됨. last.py에서는 별도 스킵 게이트를 두지 않음

    # StringSecurity 폴더 복사 (암호화 기능과 동일)
    copy_StringSecurity_folder(args.dst)
    
    exceptions = load_exceptions(args.exceptions)
    log(f"loaded {len(exceptions)} exception rules")

    file_excludes = build_file_exclude_patterns(exceptions)
    if args.debug:
        log(f"file exclusion patterns: {len(file_excludes)}")

    skip_ui = not args.no_skip_ui
    # Prepass: collect actor/global-actor types across the project (for extension resolution)
    actor_types, global_actor_types = collect_actor_and_global_types(args.dst, include_packages=args.include_packages, debug=args.debug)
    local_declared_types = collect_local_declared_types(args.dst, include_packages=args.include_packages, debug=args.debug)
    local_protocol_reqs = collect_local_protocol_requirements(args.dst, include_packages=args.include_packages, debug=args.debug)
    funcs = scan_swift_functions(
        args.dst,
        skip_ui=skip_ui,
        debug=args.debug,
        exclude_file_globs=file_excludes,
        args_include_packages=args.include_packages,
        known_actor_types=actor_types,
        known_global_actor_types=global_actor_types,
        local_declared_types=local_declared_types,
        local_protocol_reqs=local_protocol_reqs,
    )
    log(f"discovered {len(funcs)} functions{' (UI files skipped)' if skip_ui else ''}")

    included, excluded = partition_by_exceptions(funcs, exceptions)
    safe, risky = partition_risky(included, skip_overrides=not args.risk_keep_overrides)

    log(f"found {len(safe)} safe functions to obfuscate")

    if args.perfile_inject:
        by_file: Dict[str, List[Dict]] = {}
        for f in safe: by_file.setdefault(f["file"], []).append(f)

        all_swift_files = iter_swift_files(args.dst, skip_ui=False, debug=args.debug, exclude_file_globs=file_excludes, include_packages=args.include_packages)
        if args.debug and file_excludes:
            log("Note: Files matching exclusion patterns are skipped from scanning and injection.")
        touched_files, wrapped_total = 0, 0

        for abs_path in all_swift_files:
            rel = os.path.relpath(abs_path, args.dst)
            if skip_ui and is_ui_path(rel): continue

            targets = by_file.get(rel, [])
            if not targets: continue

            touched, wrapped = inject_per_file(
                abs_path, rel, targets,
                debug=args.debug,
                dry_run=args.dry_run,
                max_params=args.max_params,
                skip_external_extensions=args.skip_external_extensions,
                skip_external_protocol_reqs=args.skip_external_protocol_reqs,
                allow_internal_protocol_reqs=args.allow_internal_protocol_reqs,
                skip_external_protocol_extension_members=args.skip_external_protocol_extension_members,
            )
            if touched: touched_files += 1
            wrapped_total += wrapped
        log(f"in-file injection complete: files_touched={touched_files}, wrapped_funcs={wrapped_total}")
    log(f"output project: {os.path.abspath(args.dst)}")

if __name__ == "__main__":
    main()
