from __future__ import annotations

import json
import os
from typing import Any
import logging

# strict-mode helper
try:
    from ..tui import _maybe_raise, _trace  # type: ignore
except ImportError as _imp_err:
    def _trace(msg: str, *args, **kwargs) -> None:
        try:
            import logging as _lg
            _lg.log(10, msg, *args, **kwargs)
        except (ValueError, TypeError, OSError, UnicodeError, AttributeError) as e:
            return

    _trace("fallback _maybe_raise due to ImportError: %s", _imp_err)

    def _maybe_raise(e: BaseException) -> None:
        import os
        if os.environ.get("SWINGFT_TUI_STRICT", "").strip() == "1":
            raise e


def build_structured_input(swift_code: str, symbol_info) -> str:
    try:
        if isinstance(symbol_info, (dict, list)):
            pretty = json.dumps(symbol_info, ensure_ascii=False, indent=2)
        elif isinstance(symbol_info, str) and symbol_info.strip():
            try:
                pretty = json.dumps(json.loads(symbol_info), ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                _trace("build_structured_input: symbol_info JSON parse failed: %s", e)
                _maybe_raise(e)
                pretty = symbol_info
        else:
            pretty = "[]"
    except (TypeError, ValueError) as e:
        _trace("build_structured_input: pretty build failed: %s", e)
        _maybe_raise(e)
        pretty = "[]"
    swift = swift_code if isinstance(swift_code, str) else ""
    return (
        "**Swift Source Code:**\n"
        "```swift\n" + swift + "\n```\n\n"
        "**AST Symbol Information (JSON):**\n"
        "```\n" + pretty + "\n```"
    )





# --- Snippet and AST analyzer helpers (moved from loader) ---
def find_first_swift_file_with_identifier(project_dir: str, ident: str):
    try:
        import os
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'build', 'DerivedData'}]
            for fn in files:
                if not fn.lower().endswith('.swift'):
                    continue
                fp = os.path.join(root, fn)
                try:
                    with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                        text = f.read()
                    if ident in text:
                        return fp, text
                except (OSError, UnicodeError) as e:
                    _trace("find_first_swift_file_with_identifier: read failed for %s: %s", fp, e)
                    _maybe_raise(e)
                    continue
    except OSError as e:
        _trace("find_first_swift_file_with_identifier: walk failed: %s", e)
        _maybe_raise(e)
        return None
    return None


def make_snippet(text: str, ident: str, ctx_lines: int = 30) -> str:
    try:
        lines = text.splitlines()
        hit = None
        for i, ln in enumerate(lines):
            if ident in ln:
                hit = i
                break
        if hit is None:
            return text[:8000]
        lo = max(0, hit - ctx_lines)
        hi = min(len(lines), hit + ctx_lines + 1)
        snippet = "\n".join(lines[lo:hi])
        if len(snippet) > 8000:
            snippet = snippet[:8000] + "\n... [truncated]"
        return snippet
    except (AttributeError, UnicodeError) as e:
        _trace("make_snippet failed: %s", e)
        _maybe_raise(e)
        return text[:8000]


def _verbose() -> bool:
    v = os.environ.get("SWINGFT_PREFLIGHT_VERBOSE", "")
    return str(v).strip().lower() in {"1","true","yes","y","on"}


def _locate_swift_ast_analyzer():
    """Find SwiftASTAnalyzer binary by probing common locations and limited walk. Cached."""
    global _ANALYZER_PATH_CACHE
    if _ANALYZER_PATH_CACHE is not None:
        return _ANALYZER_PATH_CACHE
    try:
        from pathlib import Path as _P
        override = os.environ.get('SWINGFT_AST_ANALYZER_PATH', '').strip()
        if override and _P(override).exists():
            _ANALYZER_PATH_CACHE = _P(override)
            return _ANALYZER_PATH_CACHE
        cwd = _P(os.getcwd())
        candidates = [
            cwd / 'ast_analyzers' / 'sensitive' / 'SwiftASTAnalyzer',
            cwd / 'ast_analyzers' / 'SwiftASTAnalyzer',
            cwd / '.swingft' / 'tools' / 'SwiftASTAnalyzer',
            cwd / 'tools' / 'SwiftASTAnalyzer',
            cwd / 'bin' / 'SwiftASTAnalyzer',
        ]
        for c in candidates:
            if c.exists():
                _ANALYZER_PATH_CACHE = c
                return _ANALYZER_PATH_CACHE
        # limited walk with pruned dirs
        prune = {'.git', '.venv', 'node_modules', 'DerivedData', 'build', '.build', 'Obfuscation_Pipeline'}
        max_depth = 4
        base_parts = len(cwd.parts)
        for root, dirs, files in os.walk(str(cwd)):
            # prune
            pd = []
            for d in list(dirs):
                if d in prune:
                    pd.append(d)
            for d in pd:
                dirs.remove(d)
            # depth limit
            if len(_P(root).parts) - base_parts > max_depth:
                dirs[:] = []
                continue
            if 'SwiftASTAnalyzer' in files:
                p = _P(root) / 'SwiftASTAnalyzer'
                if p.exists():
                    _ANALYZER_PATH_CACHE = p
                    return _ANALYZER_PATH_CACHE
    except OSError as e:
        _trace("_locate_swift_ast_analyzer failed: %s", e)
        _maybe_raise(e)
    _ANALYZER_PATH_CACHE = None
    return None


def run_swift_ast_analyzer(swift_file_path: str):
    """Execute local Swift AST analyzer binary and parse JSON from stdout."""
    try:
        import subprocess, os
        from pathlib import Path
        analyzer_path = _locate_swift_ast_analyzer()
        if not analyzer_path or not Path(analyzer_path).exists():
            if _verbose():
                print(f"Warning: AST analyzer not found at {analyzer_path}")
            return None
        command_str = f'"{str(analyzer_path)}" "{swift_file_path}"'
        proc = subprocess.run(
            command_str,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60,
        )
        if proc.returncode != 0:
            err = (proc.stderr or '').strip()
            if _verbose():
                print(f"Warning: AST analyzer failed for {swift_file_path}. Error: {err}")
            return None
        out = (proc.stdout or '').strip()
        if not out:
            return None
        lb = out.find('[')
        lb2 = out.find('{')
        if lb == -1 and lb2 == -1:
            return None
        json_start = lb if (lb != -1 and (lb < lb2 or lb2 == -1)) else lb2
        json_part = out[json_start:]
        import json as _json
        try:
            data = _json.loads(json_part)
            return data
        except (json.JSONDecodeError, ValueError) as e:
            _trace("AST analyzer JSON decode failed: %s", e)
            return None
    except subprocess.TimeoutExpired:
        if _verbose():
            print(f"Warning: AST analysis timed out for {swift_file_path}")
        return None
    except (OSError, subprocess.SubprocessError) as e:
        if _verbose():
            print(f"Warning: AST analysis failed for {swift_file_path}: {e}")
        _trace("AST analysis failed: %s", e)
        _maybe_raise(e)
        return None


# --- Local LLM inference (analyze_payload 스타일) ---
def _extract_first_json(text: str):
    try:
        import json as _json
        depth, start = 0, -1
        for i, ch in enumerate(text or ""):
            if ch == '{':
                if start < 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        return _json.loads((text[start:i+1]))
                    except (json.JSONDecodeError, ValueError):
                        break
        # fenced block fallback
        try:
            import re
            m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text or "", re.MULTILINE)
            if m:
                return _json.loads(m.group(1))
        except (re.error, json.JSONDecodeError, ValueError) as e:
            _trace("extract_first_json fenced parse failed: %s", e)
            _maybe_raise(e)
    except (TypeError, ValueError) as e:
        _trace("extract_first_json failed: %s", e)
        _maybe_raise(e)
    return None


def _build_prompt_for_identifier(swift_code: str, target_identifier: str, ast_symbols) -> str:
    try:
        import json as _json
        ast = None
        if isinstance(ast_symbols, list) and ast_symbols:
            ast = ast_symbols[0]
        elif isinstance(ast_symbols, dict):
            ast = ast_symbols
        else:
            ast = {}
        ast_json = "{}"
        try:
            ast_json = _json.dumps(ast, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as e:
            _trace("build_prompt_for_identifier: ast dumps failed: %s", e)
            _maybe_raise(e)
            ast_json = "{}"
    except (TypeError, ValueError) as e:
        _trace("build_prompt_for_identifier: setup failed: %s", e)
        _maybe_raise(e)
        ast_json = "{}"
    instr = (
        "Analyze whether the target identifier in the Swift code is security-sensitive. "
        "Provide your judgment and reasoning."
    )
    guard = (
        "Respond with a single JSON object only. No code fences. "
        "Keys: is_sensitive, reasoning."
    )
    return (
        f"{instr}\n\n"
        f"**Swift Source Code:**\n```swift\n{swift_code or ''}\n```\n\n"
        f"**AST Symbol Information (Target: `{target_identifier}`):**\n```json\n{ast_json}\n```\n\n"
        f"**Target Identifier:** `{target_identifier}`\n\n{guard}"
    )


_LLM_SINGLETON = None
_ANALYZER_PATH_CACHE = None


def _load_llm_singleton():
    global _LLM_SINGLETON
    if _LLM_SINGLETON is not None:
        return _LLM_SINGLETON
    try:
        # llama.cpp 로그 소음을 줄이기 위해 기본 로그 레벨을 오류로 설정
        import os as _os
        if not _os.environ.get("LLAMA_LOG_LEVEL"):
            # ERROR 레벨로 설정 (낮을수록 출력 감소)
            _os.environ["LLAMA_LOG_LEVEL"] = "40"
        # Metal 초기화 등에서 찍히는 stderr 로그를 최대한 억제하기 위해 import 이후에도 제어
        from llama_cpp import Llama  # type: ignore
        _trace("llama_cpp import 성공")
    except ImportError as e:
        _trace("llama_cpp import 실패: %s", e)
        _maybe_raise(e)
        return None
    base_model = _os.getenv("BASE_MODEL_PATH", "./models/base_model.gguf")
    lora_path = _os.getenv("LORA_PATH", _os.path.join("./models", "lora_sensitive_single.gguf"))
    n_ctx = int(_os.getenv("N_CTX", "8192"))
    n_threads = int(_os.getenv("N_THREADS", str(os.cpu_count() or 8)))
    n_gpu_layers = int(_os.getenv("N_GPU_LAYERS", "12"))
    kwargs = dict(
        model_path=base_model,
        n_ctx=n_ctx,
        n_threads=n_threads,
        logits_all=False,
        verbose=False,
    )
    if lora_path and str(lora_path).strip():
        kwargs["lora_path"] = lora_path
    if n_gpu_layers:
        kwargs["n_gpu_layers"] = n_gpu_layers
    try:
        _trace("LLM 모델 로드 시도: %s", base_model)
        # 모델 로드 시 발생하는 Metal 초기화 stderr 로그를 억제
        import contextlib as _ct
        import sys as _sys
        try:
            with open(_os.devnull, 'w') as _devnull, _ct.redirect_stderr(_devnull):
                _LLM_SINGLETON = Llama(**kwargs)
        except (OSError, RuntimeError, ValueError) as e:
            _trace("LLM model load with stderr redirect failed, retrying without redirect: %s", e)
            # 일부 환경에서는 redirect가 적용되지 않을 수 있으므로 재시도
            _LLM_SINGLETON = Llama(**kwargs)
        _trace("LLM 모델 로드 성공")
    except (RuntimeError, OSError, ValueError) as e:
        _trace("LLM 모델 로드 실패: %s", e)
        _maybe_raise(e)
        _LLM_SINGLETON = None
    return _LLM_SINGLETON


def run_local_llm_exclude(identifier: str, swift_code: str, ast_symbols) -> list | None:
    """Return list[{name, exclude(bool), reason}] based on local llama inference.
    If llama not available or parsing fails, return None.
    """
    llm = _load_llm_singleton()
    if llm is None:
        return None
    prompt = _build_prompt_for_identifier(swift_code or "", identifier, ast_symbols)
    try:
        max_tokens = int(os.getenv("MAX_TOKENS", "256"))
        temperature = float(os.getenv("TEMPERATURE", "0.0"))
        top_p = float(os.getenv("TOP_P", "1.0"))
        resp = llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=None,
        )
        full_text = (resp.get("choices", [{}])[0] or {}).get("text", "")
        parsed = _extract_first_json(full_text or "")
        if isinstance(parsed, dict):
            is_sensitive = bool(parsed.get("is_sensitive", True))
            reason = str(parsed.get("reasoning", "") or "")
            return [{"name": identifier, "exclude": is_sensitive, "reason": reason}]
    except (KeyError, TypeError, ValueError, RuntimeError) as e:
        _trace("run_local_llm_exclude failed: %s", e)
        _maybe_raise(e)
        return None
    return None


# --- Fallback: pull symbol info from pipeline AST output ---
def find_ast_entry_from_pipeline(project_root: str, ident: str):
    try:
        import os as _os, json as _json
        from pathlib import Path as _P
        env_ast = _os.environ.get("SWINGFT_AST_NODE_PATH", "").strip()
        candidates = []
        if env_ast:
            candidates.append(env_ast)
        # common default locations
        candidates.extend([
            str(_P(os.getcwd()) / "Obfuscation_Pipeline" / "AST" / "output" / "ast_node.json"),
            str(_P(os.getcwd()) / "AST" / "output" / "ast_node.json"),
        ])
        ast_path = next((p for p in candidates if _P(p).exists()), None)
        if not ast_path:
            return None
        with open(ast_path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        # minimal presence check; we don't depend on schema here
        # return a synthesized entry focusing on the target identifier name
        return {"symbolName": ident, "symbolKind": "unknown", "source": "pipeline_ast"}
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        _trace("find_ast_entry_from_pipeline failed: %s", e)
        _maybe_raise(e)
        return None


def resolve_ast_symbols(project_root: str, swift_path: str | None, ident: str):
    """Best-effort AST symbol info for LLM prompt.
    Order: analyzer (if available) -> pipeline ast_node.json minimal entry -> None
    Returns either a dict or list compatible with downstream usage.
    """
    try:
        if swift_path:
            res = run_swift_ast_analyzer(swift_path)
            if res:
                return res
    except (OSError, RuntimeError) as e:
        _trace("resolve_ast_symbols analyzer error: %s", e)
        _maybe_raise(e)
    fb = find_ast_entry_from_pipeline(project_root, ident)
    if fb:
        return [fb]
    return None
