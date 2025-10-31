from __future__ import annotations

import os
from typing import Tuple

from .loader import load_config_or_exit as _load_cfg


def read_io_paths(config_path: str) -> Tuple[str | None, str | None]:
    """Read project.input/output from config without triggering preflight.

    Returns (input_path, output_path). Either may be None if missing.
    """
    # Suppress preflight/LLM during this read
    prev = os.environ.get("SWINGFT_DEFER_PREFLIGHT")
    os.environ["SWINGFT_DEFER_PREFLIGHT"] = "1"
    try:
        cfg = _load_cfg(config_path)
    finally:
        if prev is None:
            try:
                del os.environ["SWINGFT_DEFER_PREFLIGHT"]
            except KeyError as e:
                import logging
                logging.trace("SWINGFT_DEFER_PREFLIGHT env var deletion failed (not set): %s", e)
        else:
            os.environ["SWINGFT_DEFER_PREFLIGHT"] = prev

    proj = cfg.get("project") if isinstance(cfg.get("project"), dict) else {}
    inp = proj.get("input") if isinstance(proj, dict) else None
    out = proj.get("output") if isinstance(proj, dict) else None
    return inp, out


