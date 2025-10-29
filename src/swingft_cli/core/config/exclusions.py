from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Any, Dict
import logging

# strict-mode helper
try:
    from ..tui import _maybe_raise  # type: ignore
except ImportError as _imp_err:
    logging.trace("fallback _maybe_raise due to ImportError: %s", _imp_err)
    def _maybe_raise(e: BaseException) -> None:
        import os
        if os.environ.get("SWINGFT_TUI_STRICT", "").strip() == "1":
            raise e

def write_feedback_to_output(config: Dict[str, Any], filename: str, content: str) -> str | None:
    try:
        out_dir = str(config.get("project", {}).get("output") or "").strip()
        if not out_dir:
            return None
        base = os.path.join(out_dir, "Obfuscation_Report", "preflight")
        os.makedirs(base, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(base, f"{filename}_{ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except (OSError, UnicodeError, PermissionError, ValueError) as e:
        logging.trace("write_feedback_to_output failed: %s", e)
        _maybe_raise(e)
        return None

def ast_unwrap(node):
    try:
        if isinstance(node, dict) and isinstance(node.get("node"), dict):
            return node["node"]
    except (TypeError, AttributeError, KeyError) as e:
        logging.trace("ast_unwrap failed: %s", e)
        _maybe_raise(e)
    return node
