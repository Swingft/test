#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
code_injector.py
- 코드 인젝션 기능을 담당하는 모듈
- inject_per_file 함수와 관련 유틸리티들을 포함
"""
from __future__ import annotations
import os
import re
import hashlib
import logging
from typing import Dict, List, Optional, Tuple, Set

from utils import log, read_text, write_text

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

# ---------- 전역 설정 ----------
OBF_BEGIN, OBF_END = "", ""

# ---------- 유틸리티 함수들 ----------
def _file_scoped_id(rel_path: str) -> str:
    # Use SHA-256 for better security, uppercased, first 10 chars
    h = hashlib.sha256(rel_path.encode("utf-8")).hexdigest().upper()
    return h[:10]

def _swift_type(t: Optional[str]) -> str:
    t = (t or "").strip()
    return t if t else "Void"

def _param_var_names(params_src: str) -> List[str]:
    from swift_scanner import _split_params_top, _param_external_labels_list
    
    out: List[str] = []
    labels = _param_external_labels_list(params_src)
    for i, part in enumerate([p.strip() for p in _split_params_top(params_src or "") if p.strip()]):
        if ":" not in part:
            toks = [x for x in re.split(r"\s+", part) if x and x != "_"]
            out.append(toks[-1] if toks else "arg")
            continue
        left = part.split(":", 1)[0].strip()
        toks = [x for x in re.split(r"\s+", left) if x and x != "_"]
        if len(toks) >= 2: out.append(toks[-1])
        elif toks: out.append(toks[0])
        else: out.append("arg")
    return out

def build_perfile_runtime(file_id: str, routes: List[str], max_params: int = 10) -> str:
    enum_name = f"OBFF{file_id}"
    
    # CFGWrappingUtils를 활용한 간단한 actor 생성
    lines = [
        OBF_BEGIN,
        f"enum {enum_name} {{",
        "  static private var routes: [String: ([Any]) throws -> Any] = [:]",
        "  static private var didInstall = false",
        "  static private func install() {"] + [f"    {r}" for r in routes] + [
        "  }",
        "  static private func ensure() { if !didInstall { didInstall = true; install() } }",
        "",
        "  @discardableResult",
        "  static func register(_ key: String, _ fn: @escaping ([Any]) throws -> Any, overwrite: Bool = false) -> Bool {",
        "    if !overwrite, routes[key] != nil { return false }",
        "    routes[key] = fn",
        "    return true",
        "  }",
        "  static func call<R>(_ key: String, _ args: Any...) throws -> R {",
        "    ensure()",
        "    guard let fn = routes[key] else { preconditionFailure(\"[OBF] missing key: \\(key)\") }",
        "    let res = try fn(args)",
        "    guard let cast = res as? R else { preconditionFailure(\"[OBF] bad return for \\(key)\") }",
        "    return cast",
        "  }",
        "  static func callVoid(_ key: String, _ args: Any...) throws {",
        "    ensure()",
        "    guard let fn = routes[key] else { preconditionFailure(\"[OBF] missing key: \\(key)\") }",
        "    _ = try fn(args)",
        "  }",
        ""
    ]
    
    # (static wrapper functions removed)
    lines.extend(["}"])
    
    return "\n".join(lines)

def inject_or_replace_block(original_text: str, block_text: str) -> str:
    start = original_text.find(OBF_BEGIN) if OBF_BEGIN else -1
    end = original_text.find(OBF_END, start + len(OBF_BEGIN)) if (OBF_BEGIN and start != -1) else -1
    if start != -1 and end != -1:
        return original_text[:start] + block_text + original_text[end + len(OBF_END):]
    
    # StringSecurity import 처리
    if "import StringSecurity" in original_text:
        # 이미 import가 있으면 맨 위로 이동
        lines = original_text.split('\n')
        import_lines = [line for line in lines if "import StringSecurity" in line]
        other_lines = [line for line in lines if "import StringSecurity" not in line]
        
        # 맨 위에 import 배치
        result_lines = import_lines + [""] + other_lines
        original_text = '\n'.join(result_lines)
    else:
        # import가 없으면 block_text에 추가
        import_line = "import StringSecurity\n"
        block_text = import_line + block_text
    
    return block_text + "\n\n" + original_text

def _rename_and_add_wrapper(src: str, *, name: str, parent_type: Optional[str], is_static: bool, params_src: str, return_type: Optional[str], route_key: str, file_id: str, modifiers: List[str]) -> Tuple[str, bool]:
    """
    Preserve declaration-leading attributes (e.g., @IBAction, @IBSegueAction, @...Actor) by re-applying them to the
    generated wrapper function, while removing them from the implementation function. This version is careful to:
      - Extract attribute *tokens* only (e.g., "@IBAction"), not whole lines.
      - Never touch parameter attributes such as `@escaping` or `@Sendable`.
      - Preserve line breaks when removing attribute lines to avoid token concatenation like `@bescaping`.
    """
    lines = src.splitlines(keepends=True)
    # func decl matcher: allow any number of attribute tokens immediately before `func`
    func_pat = re.compile(r"^\s*(?:@[\w:]+\s*)*\s*func\s+" + re.escape(name) + r"\s*\(")
    func_idx = -1
    for i, line in enumerate(lines):
        if func_pat.match(line):
            func_idx = i
            break
    if func_idx == -1:
        impl = f"obfImpl_{name}"
        func_pat2 = re.compile(r"^\s*(?:@[\w:]+\s*)*\s*func\s+" + re.escape(impl) + r"\s*\(")
        for i, line in enumerate(lines):
            if func_pat2.match(line):
                return src, False
        return src, False

    # --- Collect declaration-leading attribute *tokens* ---
    def _attr_tokens_from_line(s: str) -> List[str]:
        # Capture full attribute segments like '@IBAction', '@IBSegueAction', '@MainActor', and '@objc' with optional parentheses: '@objc(name)'
        return re.findall(r"(?:(?<=^)@|(?<=\s)@)[\w:]+(?:\s*\([^)]*\))?", s)

    def _is_spacer_line(s: str) -> bool:
        st = s.strip()
        # empty, doc-comments and conditional-compilation lines are considered spacers
        return (not st) or st.startswith('///') or st.startswith('/**') or st.startswith('*') or st.startswith('*/') or st.startswith('#if') or st.startswith('#endif') or st.startswith('#else')

    # tokens on the same line as `func`
    inline_tokens = _attr_tokens_from_line(lines[func_idx])

    # tokens on the lines immediately above the function decl (pure-attribute lines)
    # We allow up to 12 lines lookback and skip over doc-comments / conditional compilation lines.
    above_tokens: List[str] = []
    above_attr_lines: Dict[int, List[str]] = {}
    for j in range(func_idx - 1, max(-1, func_idx - 13), -1):
        raw = lines[j]
        stripped = raw.strip()
        if _is_spacer_line(raw):
            # spacer lines do not stop the scan; continue scanning upward
            continue
        if stripped.startswith("@"):
            # Attribute-only line (no declarations like `@Published var`)
            if re.match(r"^\s*@[\w:]+(?:\s*\([^)]*\))?\s*$", stripped):
                toks = _attr_tokens_from_line(raw)
                if toks:
                    above_tokens.extend(toks)
                    above_attr_lines[j] = toks
                    continue
            # Otherwise it's an attribute preceding a different declaration → stop
            break
        # non-attribute, non-spacer content → stop
        break

    # We only preserve declaration-leading attributes that should stay on the wrapper
    def _is_preserved(tok: str) -> bool:
        # Preserve UI/runtime/actor attributes and Objective-C exposure
        # - Keep @objc and @objc(...) so selectors keep working after wrapping
        # - Keep IBAction/IBSegueAction and any global-actor (…Actor)
        base = tok.strip()
        return base.startswith("@objc") or base in ("@IBAction", "@IBSegueAction") or base.endswith("Actor")

    preserved = [t for t in (above_tokens + inline_tokens) if _is_preserved(t)]

    # --- Build the implementation function line: remove only the preserved tokens from the decl line
    orig_func_line = lines[func_idx]
    new_func_line = orig_func_line
    for tok in preserved:
        # Replace token with a single space boundary-safe; keep surrounding whitespace
        new_func_line = re.sub(rf"(?:(?<=^)\s*|\s+){re.escape(tok)}(?=\s|$)", " ", new_func_line)

    # Rename to obfImpl_<name>
    impl = f"obfImpl_{name}"
    if re.search(r"\bfunc\s+" + re.escape(impl) + r"\s*\(", src, re.MULTILINE):
        return src, False
    new_func_line_renamed, nsubs = re.subn(r"(\bfunc\s+)" + re.escape(name) + r"(\s*\()", r"\1" + impl + r"\2", new_func_line, count=1)
    if nsubs == 0:
        return src, False

    # Reconstruct lines: replace function line; for attribute-only lines above, remove only those containing preserved tokens
    new_lines: List[str] = []
    to_delete_idx: Set[int] = set()
    # Only delete attribute-only lines that contain preserved tokens; keep others (e.g., @available)
    for idx, toks in above_attr_lines.items():
        if any(t in preserved for t in toks):
            to_delete_idx.add(idx)

    for idx, l in enumerate(lines):
        if idx == func_idx:
            new_lines.append(new_func_line_renamed)
        elif idx in to_delete_idx:
            new_lines.append("\n" if l.endswith("\n") else l[:0])
        else:
            new_lines.append(l)
    new_src = "".join(new_lines)

    # If access modifier is `private`, relax to `fileprivate` for the impl (same heuristic as before)
    m2 = re.search(r"(\bfunc\s+)" + re.escape(impl) + r"(\s*\()", new_src, re.MULTILINE)
    if not m2:
        return src, False
    if 'private' in modifiers:
        prev_brace_pos = new_src.rfind('}', 0, m2.start(1))
        search_start = prev_brace_pos + 1 if prev_brace_pos != -1 else 0
        modifier_block = new_src[search_start:m2.start(1)]
        new_modifier_block, rep = re.subn(r"\bprivate\b", "fileprivate", modifier_block)
        if rep > 0:
            new_src = new_src[:search_start] + new_modifier_block + new_src[m2.start(1):]
            m2 = re.search(r"(\bfunc\s+)" + re.escape(impl) + r"(\s*\()", new_src, re.MULTILINE)
            if not m2:
                return src, False

    # Figure out insertion point (closing brace of the parent type body)
    insert_at = -1
    if parent_type:
        impl_pos = m2.start(1)
        type_pat = re.compile(
            rf"^\s*(?:@[\w:]+\s*)*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?"
            rf"(class|struct|enum|actor|extension)\s+{re.escape(parent_type)}\b[\s\S]*?\{{",
            re.MULTILINE | re.DOTALL,
        )
        for match in type_pat.finditer(new_src):
            open_brace_pos = match.end() - 1
            depth, k = 1, open_brace_pos + 1
            body_start_pos = k
            body_end_pos = -1
            while k < len(new_src):
                ch = new_src[k]
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        body_end_pos = k
                        break
                k += 1
            if body_end_pos != -1 and body_start_pos <= impl_pos < body_end_pos:
                insert_at = body_end_pos
                break
    if insert_at == -1:
        return src, False

    ret = _swift_type(return_type)
    access = next((t for t in modifiers if t in {"public","internal","fileprivate","private","open"}), "")
    wrapper_hdr = f"{access+' ' if access else ''}{'static ' if is_static and parent_type else ''}func {name}({params_src})"
    if ret != "Void":
        wrapper_hdr += f" -> {ret}"

    arg_names = _param_var_names(params_src)
    call_args = (["self"] if parent_type and not is_static else []) + arg_names
    call_joined = ", ".join(call_args)
    call_prefix = f'("{route_key}"{", " if call_joined else ""}{call_joined})'

    if ret != "Void":
        body = f"{{\n  return try! OBFF{file_id}.call{call_prefix}\n}}"
    else:
        body = f"{{\n  try! OBFF{file_id}.callVoid{call_prefix}\n}}"

    # Reconstruct preserved attribute *text* from the original source lines when possible
    preserved_line_texts: List[str] = []
    # If there were attribute-only lines above the func that we decided to delete, take their exact text
    for idx in sorted(to_delete_idx):
        # keep the original line as-is (it already contains its newline)
        preserved_line_texts.append(lines[idx])
    # If some preserved tokens were inline on the func line (e.g., '@objc' on the same line),
    # synthesize a single-line attribute string from those tokens and prefer it before the above lines.
    inline_preserved = [t for t in inline_tokens if _is_preserved(t)]
    if inline_preserved:
        synthesized = "".join(t + "\n" for t in inline_preserved)
        # put synthesized inline attrs before the collected above-lines so order resembles original intent
        preserved_line_texts.insert(0, synthesized)
    attrs_prefix = "".join(preserved_line_texts)
    wrapper = f"\n\n{attrs_prefix}{wrapper_hdr}\n{body}\n"
    return new_src[:insert_at] + wrapper + new_src[insert_at:], True

# ---------- 메인 인젝션 함수 ----------
def inject_per_file(file_abs: str, file_rel: str, targets: List[Dict], *, debug: bool, dry_run: bool, max_params: int, skip_external_extensions: bool, skip_external_protocol_reqs: bool, allow_internal_protocol_reqs: bool, skip_external_protocol_extension_members: bool) -> Tuple[bool, int]:
    """
    파일에 코드 인젝션을 수행하는 메인 함수
    
    Args:
        file_abs: 파일의 절대 경로
        file_rel: 파일의 상대 경로
        targets: 인젝션할 함수들의 리스트
        debug: 디버그 모드 여부
        dry_run: 실제 파일 수정 없이 테스트만 수행
        max_params: 최대 파라미터 수
        skip_external_extensions: 외부 확장 스킵 여부
        skip_external_protocol_reqs: 외부 프로토콜 요구사항 스킵 여부
        allow_internal_protocol_reqs: 내부 프로토콜 요구사항 허용 여부
        skip_external_protocol_extension_members: 외부 프로토콜 확장 멤버 스킵 여부
        
    Returns:
        (성공 여부, 래핑된 함수 수) 튜플
    """
    if not targets:
        return (False, 0)
    try:
        original = read_text(file_abs)
    except (OSError, UnicodeError) as e:
        _trace("inject_per_file: read_text failed for %s: %s", file_abs, e)
        _maybe_raise(e)
        return (False, 0)
    file_id, text, routes, wrapped_count = _file_scoped_id(file_rel), original, [], 0
    # --- helpers for conservative skipping of bare nested types (lowest risk) ---
    nested_type_cache: Dict[str, set] = {}

    def _strip_type_tokens(tp: Optional[str]) -> str:
        tp = (tp or "").strip()
        # remove optional/implicitly-unwrapped marks
        tp = tp.rstrip("?!")
        # strip array/dictionary sugar in a conservative way
        if tp.startswith("[") and tp.endswith("]"):
            tp = tp[1:-1].strip()
        # take the base identifier before generics
        if '<' in tp:
            tp = tp.split('<', 1)[0].strip()
        return tp

    def _find_parent_body(src: str, parent_name: str) -> Optional[str]:
        # find the top-level declaration of the parent type and return its body text
        m = re.search(
            rf'^\s*(?:@[\w:]+\s*)*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?'
            rf'(?:class|struct|enum|actor|extension)\s+{re.escape(parent_name)}\b.*?\{{',
            src,
            re.MULTILINE | re.DOTALL,
        )
        if not m:
            return None
        i = m.end() - 1  # at '{'
        depth, j = 0, i
        start = i + 1
        while j < len(src):
            ch = src[j]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return src[start:j]
            j += 1
        return None

    def _collect_nested_types_for_parent(src: str, parent_name: str) -> set:
        key = parent_name
        if key in nested_type_cache:
            return nested_type_cache[key]
        body = _find_parent_body(src, parent_name)
        names: set = set()
        if body:
            for mt in re.finditer(r"\b(class|struct|enum|actor)\s+([A-Za-z_]\w*)\b", body):
                names.add(mt.group(2))
        nested_type_cache[key] = names
        return names

    def _uses_bare_nested_type(t: Dict) -> bool:
        parent = t.get("parent_type")
        if not parent:
            return False
        nested = _collect_nested_types_for_parent(original, parent)
        if not nested:
            return False
        # examine param types and return type for bare identifiers that equal a nested type name
        for p in (t.get("param_types") or []):
            base = _strip_type_tokens(p)
            # skip qualified types like Parent.Node
            if not base or '.' in base:
                continue
            if base in nested:
                return True
        ret = _strip_type_tokens(t.get("return_type"))
        if ret and '.' not in ret and ret in nested:
            return True
        return False

    # --- additional conservative guard: bare Capitalized identifier that isn't a top-level type in this file ---
    _top_level_types: Optional[set] = None

    def _collect_top_level_types(src: str) -> set:
        nonlocal _top_level_types
        if _top_level_types is not None:
            return _top_level_types
        names: set = set()
        depth = 0
        for line in src.splitlines():
            # update depth first to ignore inner/nested declarations
            open_cnt, close_cnt = line.count('{'), line.count('}')
            if depth == 0:
                m = re.match(r"^\s*(?:@[\w:]+\s*)*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?(class|struct|enum|actor|protocol|typealias)\s+([A-Za-z_]\w*)\b", line)
                if m:
                    names.add(m.group(2))
            depth += open_cnt - close_cnt
            if depth < 0:
                depth = 0
        _top_level_types = names
        return names

    def _uses_bare_unknown_capitalized_type(t: Dict) -> bool:
        # If a parameter/return type is a single Capitalized identifier without qualification (no '.')
        # and that identifier is NOT declared as a top-level type in this file, conservatively skip.
        parent = t.get("parent_type")
        if not parent:
            return False
        toplv = _collect_top_level_types(original)
        std_whitelist = {"String", "Int", "Double", "Float", "Bool", "Character", "UInt", "UInt8", "UInt16", "UInt32", "UInt64", "Int8", "Int16", "Int32", "Int64", "Date", "Data", "URL", "UUID", "Any", "AnyObject", "Never", "Void"}
        def is_bare_cap(tok: str) -> bool:
            return tok and tok[0].isupper() and '.' not in tok and '[' not in tok and ']' not in tok
        # params
        for p in (t.get("param_types") or []):
            base = _strip_type_tokens(p)
            if is_bare_cap(base) and base not in toplv and base not in std_whitelist:
                return True
        # return type
        base_r = _strip_type_tokens(t.get("return_type"))
        if is_bare_cap(base_r) and base_r not in toplv and base_r not in std_whitelist:
            return True
        return False
    
    for t in targets:
        if len(t.get("param_types") or []) > max_params:
            continue

        parent = t.get("parent_type")

        # SAFETY FILTERS
        if parent:
            # 1) Skip generic parent types entirely for instance methods (e.g., DoublyLinkedList<T>)
            if t.get("is_parent_generic") and not t.get("is_static"):
                continue
            # Legacy angle-bracket heuristic (defensive)
            if "<" in parent or ">" in parent:
                continue
            # 2) Skip members of nested types (e.g., Outer.Inner) until fully-qualified injection is implemented
            if (t.get("parent_depth") or 1) > 1:
                continue
            # 3) Ensure this file actually declares or extends the parent type at top level
            if not re.search(rf'^\s*(?:@[\w:]+\s*)*(?:public|internal|fileprivate|private|open)?\s*(?:final\s+)?(?:class|struct|enum|actor|extension)\s+{re.escape(parent)}\b', original, re.MULTILINE):
                continue
        # (A) If this is an extension that adds conformance to EXTERNAL protocol(s), optionally skip all members in that extension
        if skip_external_protocol_extension_members and t.get("is_parent_extension") and t.get("has_external_protocols_in_scope"):
            continue

        # (B) Implementations of INTERNAL protocol requirements → skip unless explicitly allowed
        if t.get("is_protocol_req_impl"):
            if not allow_internal_protocol_reqs:
                continue
        else:
            # (C) If there are EXTERNAL protocols in scope for this extension, and requested to be conservative, skip
            if skip_external_protocol_reqs and t.get("has_external_protocols_in_scope") and t.get("is_parent_extension"):
                continue
        # 2a) If requested, skip members declared in extension blocks whose parent type is not declared in this project (external type extensions)
        if skip_external_extensions and t.get("is_parent_extension") and not t.get("is_parent_declared_in_project"):
            continue
        # 2b) Skip only members declared inside *constrained* extensions (extension ... where ...)
        if t.get("is_parent_extension_constrained"):
            continue
        # 3b) Skip isolated instance methods on actor or global-actor parents unless explicitly nonisolated
        if parent and not t.get("is_static"):
            if (t.get("is_parent_actor") or t.get("is_parent_global_actor") or t.get("is_func_global_actor")) and "nonisolated" not in (t.get("modifiers") or []):
                continue

        # 4) Skip functions that reference bare nested type names (e.g., parameter type `Node` when parent has `class Node`)
        #    This is the lowest-risk policy: avoid qualifying automatically; simply skip to prevent 'Cannot find type ...' errors.
        if _uses_bare_nested_type(t):
            continue

        # 5) Skip functions that reference bare Capitalized identifiers not declared top-level in this file
        if _uses_bare_unknown_capitalized_type(t):
            continue

        new_text, did = _rename_and_add_wrapper(text, name=t["name"], parent_type=t.get("parent_type"), is_static=t.get("is_static"), params_src=t.get("params_src"), return_type=t.get("return_type"), route_key=t.get("route_key"), file_id=file_id, modifiers=t.get("modifiers"))
        if not did: continue
        text, wrapped_count = new_text, wrapped_count + 1
        impl, n, parent, is_static = f"obfImpl_{t['name']}", len(t.get("param_types") or []), t.get("parent_type"), t.get("is_static")
        param_types_str, ret_str = ", ".join(t.get("param_types") or []), _swift_type(t.get("return_type"))
        if parent and not is_static:
            needs_isolated = (t.get("is_parent_actor") or t.get("is_parent_global_actor") or t.get("is_func_global_actor")) and "nonisolated" not in (t.get("modifiers") or [])
            owner_ty = f"(isolated {parent})" if needs_isolated else f"({parent})"
            sig, wrapper_name = f"{owner_ty} -> ({param_types_str}) -> {ret_str}", f"wrapM{n}"
            fnref = f"{parent}.{impl} as {sig}"
        else:
            sig, wrapper_name = f"({param_types_str}) -> {ret_str}", f"wrap{n}"
            fnref = (f"{parent}.{impl}" if parent and is_static else impl) + f" as {sig}"
        routes.append(f'_ = OBFF{file_id}.register("{t.get("route_key")}", CFGWrappingUtils.{wrapper_name}({fnref}))')
    if wrapped_count == 0: return (False, 0)
    final_text = inject_or_replace_block(text, build_perfile_runtime(file_id, routes, max_params))
    if not dry_run:
        try:
            write_text(file_abs, final_text)
        except (OSError, UnicodeError) as e:
            _trace("inject_per_file: write_text failed for %s: %s", file_abs, e)
            _maybe_raise(e)
            return (False, 0)
    return (True, wrapped_count)
