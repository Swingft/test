from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable

import os
from .exclusions import ast_unwrap as _ast_unwrap

# strict-mode helper and trace logger
try:
    from ..tui import _maybe_raise, _trace  # type: ignore
except ImportError as _imp_err:
    def _trace(msg: str, *args, **kwargs) -> None:
        try:
            import logging as _lg
            _lg.log(10, msg, *args, **kwargs)
        except (OSError, ValueError, TypeError, AttributeError) as e:
            # 로깅 실패 시에도 프로그램은 계속 진행
            return
    _trace("fallback _maybe_raise due to ImportError: %s", _imp_err)
    def _maybe_raise(e: BaseException) -> None:
        import os as _os
        if _os.environ.get("SWINGFT_TUI_STRICT", "").strip() == "1":
            raise e


def _preflight_verbose() -> bool:
    v = os.environ.get("SWINGFT_PREFLIGHT_VERBOSE", "")
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def compare_exclusion_list_vs_ast(analyzer_root: str, ast_file_path: str | None) -> dict:
    """Compare exclusion_list.txt against AST isException flags and print summary.

    Prints per-category counts and up to 20 sample names for zero/missing.
    Returns a dict: {one:int, zero:int, missing:int, ones:[], zeros:[], missings:[], ast_path:str|None}.
    """
    result = {"one": 0, "zero": 0, "missing": 0, "ones": [], "zeros": [], "missings": [], "ast_path": None}
    if not analyzer_root or not os.path.isdir(analyzer_root):
        return result
    excl_path = os.path.join(analyzer_root, "analysis_output", "exclusion_list.txt")
    if not os.path.isfile(excl_path):
        return result
    names = []
    try:
        with open(excl_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                s = ("" if raw is None else str(raw)).strip()
                if s and s[:1] != "#":
                    names.append(s)
    except (OSError, UnicodeError) as e:
        _trace("compare: exclusion_list read failed: %s", e)
        _maybe_raise(e)
        return result
    if not names:
        return result

    # autodetect AST if not given
    ast_path_eff = ast_file_path
    if not ast_path_eff or not os.path.isfile(ast_path_eff):
        candidates = [
            os.path.join(os.getcwd(), "Obfuscation_Pipeline", "AST", "output", "ast_node.json"),
            os.path.join(os.getcwd(), "AST", "output", "ast_node.json"),
        ]
        ast_path_eff = next((p for p in candidates if os.path.isfile(p)), None)
    result["ast_path"] = ast_path_eff

    #print(f"[preflight] AST path: {ast_path_eff or 'NOT FOUND'}")

    if not ast_path_eff:
        return result

    try:
        with open(ast_path_eff, 'r', encoding='utf-8') as _af:
            ast_list = json.load(_af)
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        _trace("compare: AST load failed: %s", e)
        _maybe_raise(e)
        return result
    status_map: dict[str, list[int]] = {}
    dotted_map: dict[str, list[int]] = {}

    CONTAINER_KEYS = ("G_members", "children", "members", "extension", "node")

    def _walk_any_iter(root):
        from collections import deque
        # stack holds tuples of (object_to_visit, parents_path_list)
        dq = deque([(root, [])])
        seen = set()
        while dq:
            obj, parents = dq.pop()  # DFS; use popleft() for BFS
            oid = id(obj)
            if oid in seen:
                continue
            seen.add(oid)

            if isinstance(obj, dict):
                cur = _ast_unwrap(obj)
                if isinstance(cur, dict):
                    nm = str(cur.get('A_name', '')).strip()
                    if nm:
                        status_map.setdefault(nm, []).append(int(cur.get('isException', 0)))
                        if parents:
                            dotted = '.'.join(parents + [nm])
                            dotted_map.setdefault(dotted, []).append(int(cur.get('isException', 0)))
                    next_parents = parents + ([nm] if nm else [])

                    # 1) enqueue known containers on the unwrapped dict
                    for key in CONTAINER_KEYS:
                        ch = cur.get(key)
                        if isinstance(ch, list):
                            for c in ch:
                                dq.append((c, next_parents))
                        elif isinstance(ch, dict):
                            dq.append((ch, next_parents))

                    # 2) enqueue sibling containers on the wrapper `obj` (excluding `node`)
                    if obj is not cur:
                        for key in CONTAINER_KEYS:
                            if key == 'node':
                                continue
                            ch = obj.get(key)
                            if isinstance(ch, list):
                                for c in ch:
                                    dq.append((c, next_parents))
                            elif isinstance(ch, dict):
                                dq.append((ch, next_parents))

                    # 3) conservative descent into other values
                    for v in cur.values():
                        dq.append((v, next_parents))
                    if obj is not cur:
                        for k, v in obj.items():
                            if k not in CONTAINER_KEYS:
                                dq.append((v, next_parents))
                else:
                    # non-dict after unwrap: still descend values of the wrapper
                    for v in obj.values():
                        dq.append((v, parents))

            elif isinstance(obj, list):
                for elem in obj:
                    dq.append((elem, parents))

    _walk_any_iter(ast_list)

    zeros, missing = [], []
    one = zero = not_found = 0
    #print("[preflight][compare] exclusion_list.txt vs AST isException")
    # lowercase fallback maps
    status_map_lc = {k.lower(): v for k, v in status_map.items()}
    dotted_map_lc = {k.lower(): v for k, v in dotted_map.items()}

    def _norm_name(s: str) -> str:
        s2 = (s or "").strip().strip('\"\'')
        return s2

    for nm_raw in names:
        nm = _norm_name(nm_raw)
        vals = (
            status_map.get(nm)
            or dotted_map.get(nm)
            or status_map_lc.get(nm.lower())
            or dotted_map_lc.get(nm.lower())
        )
        if not vals:
            not_found += 1
            if len(missing) < 20:
                missing.append(nm)
            if len(result["missings"]) < 1000:
                result["missings"].append(nm)
            continue

        if any(int(v or 0) == 1 for v in vals):
            one += 1
            if len(result["ones"]) < 1000:
                result["ones"].append(nm)
        else:
            zero += 1
            if len(zeros) < 20:
                zeros.append(nm)
            if len(result["zeros"]) < 1000:
                result["zeros"].append(nm)
    for nm in missing:
        if len(result["missings"]) < 1000:
            result["missings"].append(nm)
    # Optional: explicit target count via env
    _target = os.environ.get("SWINGFT_COUNT_NAME", "").strip()
    if _target:
        try:
            _cnt = len(status_map.get(_target, []) or status_map_lc.get(_target.lower(), []))
            print(f"[preflight][count] target='{_target}' occurrences={_cnt}")
        except (KeyError, ValueError, TypeError) as e:
            _trace("compare: count block failed: %s", e)
            _maybe_raise(e)
    return result


def update_ast_node_exceptions(
    ast_file_path: str,
    identifiers_to_update: Iterable[str],
    is_exception: int = 0,
    allowed_kinds: set[str] | None = None,
    lock_children: bool = True,
    quiet: bool = True,
    only_when_explicit_zero: bool = False,
) -> None:
    """Update isException flag for specified identifiers in ast_node.json.

    Supports nested members and optional kind filtering.
    identifiers_to_update can contain simple names or dotted paths.
    """
    try:
        with open(ast_file_path, 'r', encoding='utf-8') as f:
            ast_list = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        _trace("update_ast: load failed: %s", e)
        _maybe_raise(e)
        return

    if not isinstance(ast_list, list):
        if not quiet:
            print(f"[preflight] ERROR: ast_node.json is not a list")
        # Normalize to empty list to keep downstream logic safe without early return
        ast_list = []

    def _parse_spec(spec: str):
        if not isinstance(spec, str):
            return (None, [], "")
        s = spec.strip()
        kind_hint = None
        path_part = s
        if ":" in s:
            k, rest = s.split(":", 1)
            k = k.strip().lower()
            if k:
                kind_hint = k
            path_part = rest.strip()
        parts = [p for p in path_part.split(".") if p.strip()]
        if not parts:
            return (kind_hint, [], "")
        if len(parts) == 1:
            return (kind_hint, [], parts[0])
        return (kind_hint, parts[:-1], parts[-1])

    parsed_targets = [_parse_spec(x) for x in identifiers_to_update if isinstance(x, str) and x.strip()]
    if allowed_kinds is not None:
        allowed_kinds = {str(k).strip().lower() for k in allowed_kinds if str(k).strip()}
    else:
        allowed_kinds = None

    updated_nodes = 0
    already_same_nodes = 0
    matched_ident_names: set[str] = set()
    changed_ident_names: set[str] = set()
    already_one_ident_names: set[str] = set()
    already_zero_ident_names: set[str] = set()
    updated_paths: set[str] = set()

    CONTAINER_KEYS = ("G_members", "children", "members", "extension", "node")

    def _walk(node: Dict[str, Any], parent_stack: list[str]):
        nonlocal updated_nodes, already_same_nodes
        if not isinstance(node, dict):
            return

        cur = _ast_unwrap(node)
        if not isinstance(cur, dict):
            return

        name = str(cur.get("A_name", "")).strip()
        kind = str(cur.get("B_kind", "")).strip().lower()

        matched_here = False
        parent_names = [str(p).strip() for p in parent_stack]

        for kind_hint, parent_path, leaf in parsed_targets:
            if parent_path:
                if len(parent_path) > len(parent_names):
                    continue
                if parent_names[-len(parent_path):] != parent_path:
                    continue
            if leaf and leaf != name:
                continue
            if allowed_kinds and kind not in allowed_kinds:
                continue
            if kind_hint and kind_hint != kind:
                continue

            if name:
                matched_ident_names.add(name)

            has_key = ("isException" in cur)
            try:
                prev_val = int(cur.get("isException", 0)) if has_key else 0
            except (ValueError, TypeError) as _e:
                _trace("update_ast: prev_val parse failed: %s", _e)
                _maybe_raise(_e)
                prev_val = 0

            if only_when_explicit_zero and is_exception == 1 and not (has_key and prev_val == 0):
                already_same_nodes += 1
                try:
                    if name:
                        if prev_val == 1:
                            already_one_ident_names.add(name)
                        else:
                            already_zero_ident_names.add(name)
                except (ValueError, TypeError) as _e:
                    _trace("update_ast: set update failed: %s", _e)
                    _maybe_raise(_e)
            elif prev_val != is_exception:
                cur["isException"] = is_exception
                updated_nodes += 1
                try:
                    if name:
                        changed_ident_names.add(name)
                    dotted = "/".join(parent_names + [name]) if (parent_names or name) else name
                    if dotted:
                        updated_paths.add(f"{dotted} ({kind})")
                except (ValueError, TypeError) as _e:
                    _trace("update_ast: set update failed: %s", _e)
                    _maybe_raise(_e)
            else:
                already_same_nodes += 1
                try:
                    if is_exception == 1 and name:
                        already_one_ident_names.add(name)
                    elif is_exception == 0 and name:
                        already_zero_ident_names.add(name)
                except (ValueError, TypeError) as _e:
                    _trace("update_ast: set update failed: %s", _e)
                    _maybe_raise(_e)

            matched_here = True
            if lock_children:
                cur["_no_inherit"] = True

        if not (lock_children and matched_here):
            next_stack = parent_stack + ([name] if name else [])
            for key in CONTAINER_KEYS:
                ch = cur.get(key)
                if isinstance(ch, list):
                    for c in ch:
                        _walk(c, next_stack)
                elif isinstance(ch, dict):
                    _walk(ch, next_stack)
            if node is not cur:
                for key in CONTAINER_KEYS:
                    if key == 'node':
                        continue
                    ch = node.get(key)
                    if isinstance(ch, list):
                        for c in ch:
                            _walk(c, next_stack)
                    elif isinstance(ch, dict):
                        _walk(ch, next_stack)

    for top in ast_list:
        _walk(top, [])

    # Compute missing from requested leafs
    try:
        requested_leafs = {leaf for (_k, _parents, leaf) in parsed_targets if leaf}
    except (ValueError, TypeError) as _e:
        _trace("update_ast: requested_leafs build failed: %s", _e)
        _maybe_raise(_e)
        requested_leafs = set()
    missing_ident_names = requested_leafs - matched_ident_names

    if updated_nodes > 0:
        try:
            with open(ast_file_path, 'w', encoding='utf-8') as f:
                json.dump(ast_list, f, ensure_ascii=False, indent=2)
        except (OSError, UnicodeError) as e:
            _trace("update_ast: save failed: %s", e)
            _maybe_raise(e)
