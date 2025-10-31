#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
swift_scanner.py
- Swift 함수 스캔 기능을 담당하는 모듈
- scan_swift_functions 함수와 관련 유틸리티들을 포함
"""
from __future__ import annotations
import os
import re
import sys
import logging
from typing import Dict, List, Optional, Tuple, Set

# Import the utils module for logging and file I/O
from utils import log, read_text, DEFAULT_SKIP_DIRS

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

# ---------- 정규식 패턴 (모듈 스코프) ----------
TYPE_DECL_RE = re.compile(r"^\s*(?:@[\w:]+\s*)*\s*(?P<mods>(?:\w+\s+)*)(?P<tkind>class|struct|enum|actor|extension|protocol)\s+(?P<type_name>\w+)(?P<generics>\s*<[^>]+>)?", re.MULTILINE)
FUNC_DECL_RE = re.compile(r"^\s*(?:@[\w:]+\s*)*\s*(?P<mods>(?:\w+\s+)*)func\s+(?P<name>\w+)\s*(?:<[^>]+>)?\s*\((?P<params>[^)]*)\)\s*(?:(?:async|re?throws)\s*)*(?:->\s*(?P<ret>[^\{]+))?")

def is_ui_path(rel_path: str) -> bool:
    p = rel_path.replace("\\", "/").lower()
    if any(seg in p for seg in ("/view/", "/views/", "viewcontroller")): 
        return True
    base = os.path.basename(p)
    return base.endswith("view.swift") or base.endswith("viewcontroller.swift")

def iter_swift_files(root: str, skip_ui: bool, debug: bool, exclude_file_globs: Optional[List[str]] = None, include_packages: bool = False) -> List[str]:
    """Swift 파일들을 반복하는 함수"""
    from fnmatch import fnmatchcase
    
    results: List[str] = []
    root_abs = os.path.abspath(root)
    
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_SKIP_DIRS and not d.startswith(".")]
        # If include_packages is False, skip local Swift Package directories (contain Package.swift)
        if 'Package.swift' in filenames and not include_packages:
            if debug: 
                log(f"Skipping Swift Package directory: {os.path.relpath(dirpath, root_abs)}")
            dirnames[:] = []  # stop descending into package subdirectories
            continue

        for fn in filenames:
            if not fn.endswith(".swift"): 
                continue
            abs_path = os.path.join(dirpath, fn)
            rel_path = os.path.relpath(abs_path, root_abs)

            # Exclude by exceptions (file/path globs)
            if exclude_file_globs:
                p = rel_path.replace("\\", "/").lower()
                base = os.path.basename(p)
                for g in exclude_file_globs:
                    if fnmatchcase(p, g) or fnmatchcase(base, g):
                        if debug: 
                            log(f"Skipping by exceptions (file): {rel_path}")
                        break
                else:
                    continue

            if skip_ui and is_ui_path(rel_path):
                if debug: 
                    log(f"Skipping UI file: {rel_path}")
                continue
                

            results.append(abs_path)
    return results

# ---------- 파라미터 파싱 헬퍼들 ----------
_def_default_re = re.compile(r"=\s*[^,\)\r\n]+")

def _strip_param_defaults(params_src: str) -> str:
    """Remove default-value fragments (e.g., `= nil`, `= 0`, `= compute()`) from a
    raw Swift parameter list source so that type extraction is not polluted by
    defaults. This is *only* for type signature building, not for wrapper header.
    """
    return _def_default_re.sub("", params_src or "")

def _split_params_top(params_src: str) -> List[str]:
    """Split a Swift parameter list by top-level commas (ignoring commas inside (), [], <>).
    This lets us examine each parameter segment reliably even when the list spans lines
    or contains function types/tuples/generics.
    """
    parts: List[str] = []
    if not params_src:
        return parts
    buf = []
    d_par = d_brk = d_ang = 0
    i = 0
    while i < len(params_src):
        ch = params_src[i]
        if ch == '(': d_par += 1
        elif ch == ')': d_par = max(0, d_par - 1)
        elif ch == '[': d_brk += 1
        elif ch == ']': d_brk = max(0, d_brk - 1)
        elif ch == '<': d_ang += 1
        elif ch == '>': d_ang = max(0, d_ang - 1)
        if ch == ',' and d_par == 0 and d_brk == 0 and d_ang == 0:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        parts.append(''.join(buf))
    return parts

def _has_param_default(params_src: str) -> bool:
    """Return True if any top-level parameter has a default value (contains '=' at top level).
    This avoids false positives from nested expressions and works across newlines.
    """
    for seg in _split_params_top(params_src or ""):
        if '=' in seg:
            return True
    return False

# ---------- 프로토콜 헬퍼들 ----------
def _strip_comments(text: str) -> str:
    # remove /* ... */ then // ...
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    return text

def _strip_comments_preserve_layout(text: str) -> str:
    """
    Remove comments but preserve newlines/character positions so brace depth and
    line-based parsing remain stable. Non-newline characters inside comments are
    replaced with spaces. This helps the scanner ignore any 'func ...' patterns
    that appear inside comments without breaking depth tracking.
    """
    # Block comments: keep '\n', replace other characters with spaces
    def _repl_block(m: re.Match) -> str:
        s = m.group(0)
        return "".join("\n" if ch == "\n" else " " for ch in s)
    text = re.sub(r"/\*.*?\*/", _repl_block, text, flags=re.DOTALL)

    # Line comments: replace everything from '//' to end-of-line with spaces (preserve newline)
    def _repl_line(m: re.Match) -> str:
        s = m.group(0)
        # Preserve the ending newline if present; otherwise make an equal-length spaces run
        if s.endswith("\n"):
            return " " * (len(s) - 1) + "\n"
        return " " * len(s)

    text = re.sub(r"//.*?$", _repl_line, text, flags=re.MULTILINE)
    return text

def _find_protocol_blocks(text: str) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for m in re.finditer(r"\bprotocol\s+([A-Za-z_]\w*)\b[^\\{]*\{", text):
        name = m.group(1)
        i = m.end() - 1
        depth = 0
        start_body = i + 1
        j = i
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    results.append({"name": name, "body": text[start_body:j]})
                    break
            j += 1
    return results

def _param_external_labels_list(params_src: str) -> List[str]:
    labels: List[str] = []
    for seg in _split_params_top(params_src or ""):
        seg = seg.strip()
        if not seg:
            continue
        left = seg.split(":", 1)[0].strip()
        if not left:
            labels.append("_")
            continue
        toks = [t for t in re.split(r"\s+", left) if t and t != "_"]
        if left.startswith("_"):
            labels.append("_")
        elif len(toks) >= 2:
            labels.append(toks[0])
        else:
            labels.append(toks[0] if toks else "_")
    return labels

def _func_key(name: str, params_src: str) -> Tuple[str, int, Tuple[str, ...]]:
    labels = _param_external_labels_list(params_src)
    return (name, len(labels), tuple(labels))

# ---------- 메인 스캔 함수 ----------
def scan_swift_functions(
    project_root: str,
    skip_ui: bool,
    debug: bool,
    exclude_file_globs: Optional[List[str]],
    args_include_packages: bool,
    known_actor_types: Optional[set] = None,
    known_global_actor_types: Optional[set] = None,
    local_declared_types: Optional[set] = None,
    local_protocol_reqs: Optional[Dict[str, Set[Tuple[str, int, Tuple[str, ...]]]]] = None,
) -> List[Dict]:
    """
    Swift 프로젝트에서 함수들을 스캔하는 메인 함수
    
    Args:
        project_root: 프로젝트 루트 경로
        skip_ui: UI 파일 스킵 여부
        debug: 디버그 모드 여부
        exclude_file_globs: 제외할 파일 패턴들
        args_include_packages: 패키지 포함 여부
        known_actor_types: 알려진 actor 타입들
        known_global_actor_types: 알려진 global actor 타입들
        local_declared_types: 로컬에서 선언된 타입들
        local_protocol_reqs: 로컬 프로토콜 요구사항들
        
    Returns:
        스캔된 함수들의 리스트
    """
    files = iter_swift_files(project_root, skip_ui=skip_ui, debug=debug, exclude_file_globs=exclude_file_globs, include_packages=args_include_packages)
    # Use precompiled patterns
    type_decl_re = TYPE_DECL_RE
    func_decl_re = FUNC_DECL_RE
    results: List[Dict] = []
    pending_attrs: List[str] = []  # carries attributes like @MainActor that may precede declarations
    
    for abs_path in files:
        rel_path = os.path.relpath(abs_path, project_root)
        try:
            content = read_text(abs_path)
        except (OSError, UnicodeError) as e:
            _trace("swift_scanner: read_text failed for %s: %s", abs_path, e)
            _maybe_raise(e)
            continue
        # Use a comment-stripped view for scanning so any 'func ...' inside comments is ignored.
        # Newlines/positions are preserved to keep brace-depth tracking stable.
        scan_text = _strip_comments_preserve_layout(content)

        brace, type_stack = 0, []
        for line in scan_text.splitlines():
            stripped = line.strip()
            # capture any leading attributes like @MainActor on this line
            attrs_on_line = re.findall(r"@([\w:]+)", line)
            # merge with any pending attributes from previous lines
            attrs = pending_attrs + attrs_on_line
            mtype = type_decl_re.match(line)
            if mtype:
                gens_raw = (mtype.group('generics') or '').strip()
                gens_list: List[str] = []
                if gens_raw:
                    # strip angle brackets and split by commas, keep only the identifier before any ':' constraint
                    inner = gens_raw[gens_raw.find('<')+1:gens_raw.rfind('>')]
                    for tok in [t.strip() for t in inner.split(',') if t.strip()]:
                        name = tok.split(':', 1)[0].strip()
                        # defensive: only simple identifiers
                        if re.match(r"^[A-Za-z_]\w*$", name):
                            gens_list.append(name)
                # detect global-actor on the type (e.g., @MainActor)
                has_global_actor = any(a.endswith('Actor') for a in attrs)
                ext_where = False
                trailing = line[mtype.end():]
                conforms: List[str] = []
                colon = trailing.find(':')
                if colon != -1:
                    inherits_part = trailing[colon+1:]
                    lb = inherits_part.find('{')
                    if lb != -1:
                        inherits_part = inherits_part[:lb]
                    for raw_item in inherits_part.split(','):
                        item = raw_item.strip()
                        if not item:
                            continue
                        if '<' in item:
                            item = item.split('<', 1)[0].strip()
                        item = item.split('where', 1)[0].strip()
                        m_id = re.match(r"^[A-Za-z_]\w*$", item)
                        if m_id:
                            conforms.append(item)
                if mtype.group('tkind') == "extension":
                    # Heuristic: if 'where' appears in the extension header line, treat as constrained extension
                    if re.search(r"\bwhere\b", trailing):
                        ext_where = True
                type_stack.append((mtype.group('type_name'), brace, gens_list, mtype.group('tkind'), has_global_actor, ext_where, conforms))
                pending_attrs = []
            mfunc = func_decl_re.match(line)
            if mfunc:
                # If inside a protocol body, these are requirement signatures, not implementations → skip
                if type_stack and type_stack[-1][3] == "protocol":
                    brace += line.count("{") - line.count("}")
                    while type_stack and brace <= type_stack[-1][1]:
                        type_stack.pop()
                    continue

                # Compute depth after accounting for any braces present on THIS line.
                open_cnt = line.count("{")
                close_cnt = line.count("}")
                brace_after = brace + open_cnt - close_cnt
                same_line_opens_body = ("{" in line)

                if type_stack:
                    type_depth = type_stack[-1][1]
                    # Accept if either:
                    #  - current depth is exactly inside the type body, OR
                    #  - after applying this line's braces it becomes exactly inside, OR
                    #  - we're at the type header line depth and this line opens the body.
                    if not (
                        brace == type_depth + 1
                        or brace_after == type_depth + 1
                        or (brace == type_depth and same_line_opens_body)
                    ):
                        # Not at the immediate type body → treat as nested/local and skip
                        brace = brace_after
                        while type_stack and brace <= type_stack[-1][1]:
                            type_stack.pop()
                        continue
                else:
                    # No enclosing type: allow only true file top-level functions
                    if not (brace == 0 or brace_after == 0 or (brace == 0 and same_line_opens_body)):
                        brace = brace_after
                        while type_stack and brace <= type_stack[-1][1]:
                            type_stack.pop()
                        continue
                mods = (mfunc.group('mods') or '').split()
                name, raw_params, ret = mfunc.group('name'), mfunc.group('params') or "", (mfunc.group('ret') or '').strip() or None
                # --- NEW: detect function-level global-actor annotation
                func_has_global_actor = any(a.endswith('Actor') for a in attrs)
                # Build param types from a version of params with defaults stripped,
                # so things like `= nil` do not leak into type signatures.
                clean_params = _strip_param_defaults(raw_params)
                param_types = []
                for part in clean_params.split(","):
                    if not part.strip():
                        continue
                    # take everything after ':' as the type annotation
                    if ":" in part:
                        type_part = part.split(":", 1)[1]
                    else:
                        # no explicit type (rare in func decl) – keep as-is
                        type_part = part
                    param_types.append(type_part.strip())
                parent = type_stack[-1][0] if type_stack else None
                parent_depth = len(type_stack)
                parent_qual = ".".join([t[0] for t in type_stack]) if type_stack else None
                # Also extract generics for parent type, if any
                parent_generics = type_stack[-1][2] if type_stack else []
                parent_kind     = type_stack[-1][3] if type_stack else None
                parent_has_global_actor_attr = type_stack[-1][4] if type_stack else False
                is_parent_extension = (parent_kind == "extension")
                is_parent_extension_constrained = (type_stack[-1][5] if (type_stack and is_parent_extension and len(type_stack[-1]) >= 6) else False)
                parent_conforms = type_stack[-1][6] if (type_stack and len(type_stack[-1]) >= 7) else []
                is_parent_generic = bool(parent_generics)
                # Parent actor/global-actor resolution:
                base_parent = parent or ""
                known_actor_types = known_actor_types or set()
                known_global_actor_types = known_global_actor_types or set()
                is_parent_actor = (parent_kind == "actor") or (is_parent_extension and base_parent in known_actor_types)
                parent_has_global_actor = bool(parent_has_global_actor_attr or (is_parent_extension and base_parent in known_global_actor_types))
                route_key = f"{parent+'.' if parent else ''}{name}({', '.join(param_types)})"
                if ret: route_key += f" -> {ret}"
                is_parent_local_declared = bool(parent) and (parent in (local_declared_types or set()))
                proto_reqs = local_protocol_reqs or {}
                func_key = _func_key(name, raw_params)
                matched_internal_protocols: List[str] = []
                external_protocols_in_scope: List[str] = []
                for p in (parent_conforms or []):
                    if p in proto_reqs:
                        if func_key in proto_reqs[p]:
                            matched_internal_protocols.append(p)
                    else:
                        external_protocols_in_scope.append(p)
                is_protocol_req_impl = len(matched_internal_protocols) > 0
                results.append({
                    "file": rel_path,
                    "parent_type": parent,
                    "name": name,
                    "params_src": raw_params,
                    "param_types": param_types,
                    "return_type": ret,
                    "is_static": any(tok in ('static', 'class') for tok in mods),
                    "modifiers": mods,
                    "route_key": route_key,
                    "parent_depth": parent_depth,
                    "parent_qual": parent_qual,
                    "parent_generics": parent_generics,
                    "is_parent_generic": is_parent_generic,
                    "is_parent_actor": is_parent_actor,
                    "is_parent_extension": bool(is_parent_extension),
                    "is_parent_extension_constrained": bool(is_parent_extension_constrained),
                    "is_parent_global_actor": bool(parent_has_global_actor),
                    "is_func_global_actor": bool(func_has_global_actor),
                    "is_parent_declared_in_project": bool(is_parent_local_declared),
                    "parent_conforms": parent_conforms,
                    "is_protocol_req_impl": bool(is_protocol_req_impl),
                    "matched_internal_protocols": matched_internal_protocols,
                    "has_external_protocols_in_scope": bool(external_protocols_in_scope),
                })
            pending_attrs = []
            # If this line is only attributes (starts with '@') and we didn't match a decl yet, keep them pending
            if stripped.startswith('@') and not mtype and not mfunc:
                pending_attrs = attrs_on_line or pending_attrs
            brace += line.count("{") - line.count("}")
            while type_stack and brace <= type_stack[-1][1]: 
                type_stack.pop()
    return results
