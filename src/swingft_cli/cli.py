#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
# Ensure 'src' is on sys.path so `-m swingft_cli.cli` works without installation
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir))
src_dir = os.path.join(project_root, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import argparse
import json
import logging
from pathlib import Path
import textwrap

# Add TRACE level and trace() method to logging
if not hasattr(logging, 'trace'):
    TRACE = 5
    logging.addLevelName(TRACE, "TRACE")
    
    def _trace(self, message, *args, **kwargs):
        if self.isEnabledFor(TRACE):
            self._log(TRACE, message, args, **kwargs)
    
    logging.Logger.trace = _trace
    logging.trace = lambda msg, *args, **kwargs: logging.log(TRACE, msg, *args, **kwargs)

from swingft_cli.commands.json_cmd import handle_generate_json
from swingft_cli.commands.obfuscate_cmd import handle_obfuscate

# Optional: pretty help with rich-argparse. Falls back gracefully.
try:
    from rich_argparse import RichHelpFormatter  # type: ignore

    class _NoNoneRichHelp(RichHelpFormatter):
        """Hide '(default: None)' but show real defaults, preserve newlines."""
        def _get_help_string(self, action):
            help_str = action.help or ""
            if "%(default)" in help_str:
                return help_str
            default = getattr(action, "default", None)
            if default is None or default is argparse.SUPPRESS:
                return help_str
            return f"{help_str} (default: {default})"

    def _HelpFmt(prog: str):
        return _NoNoneRichHelp(prog=prog, max_help_position=28, width=100)

except (ImportError, AttributeError) as e:
    logging.trace("rich_argparse import failed, using fallback: %s", e)
    class _NoNoneRawHelp(argparse.RawTextHelpFormatter):
        """Hide '(default: None)' but show real defaults, preserve newlines."""
        def _get_help_string(self, action):
            help_str = action.help or ""
            if "%(default)" in help_str:
                return help_str
            default = getattr(action, "default", None)
            if default is None or default is argparse.SUPPRESS:
                return help_str
            return f"{help_str} (default: {default})"

    def _HelpFmt(prog: str):
        return _NoNoneRawHelp(prog, max_help_position=28, width=100)

# ------------------------------
# Preflight: ast_node.json vs swingft_config.json overlap check
# ------------------------------

def _collect_config_sets(cfg: dict):
    """Pick include/exclude sets from swingft_config.json structure.
    Expected keys: include.obfuscation, exclude.obfuscation, include.encryption, exclude.encryption (each list[str]).
    Returns a dict of 4 sets.
    """
    inc = cfg.get("include", {}) if isinstance(cfg.get("include"), dict) else {}
    exc = cfg.get("exclude", {}) if isinstance(cfg.get("exclude"), dict) else {}

    def _as_set(d: dict, key: str):
        arr = d.get(key, []) if isinstance(d, dict) else []
        return set(x.strip() for x in arr if isinstance(x, str) and x.strip())

    return {
        "inc_obf": _as_set(inc, "obfuscation"),
        "exc_obf": _as_set(exc, "obfuscation"),
        "inc_enc": _as_set(inc, "encryption"),
        "exc_enc": _as_set(exc, "encryption"),
    }


def _preflight_check_exceptions(config_path: Path, ast_path: Path, *, fail_on_conflict: bool = False):
    """Load config & ast_node JSON, report overlaps. Optionally abort on conflicts."""
    if not ast_path.exists():
        print(f"[preflight] warning: AST node file not found: {ast_path}")
        return
    if not config_path.exists():
        print(f"[preflight] warning: config not found: {config_path}")
        return

    try:
        ast_list = json.loads(ast_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        logging.warning("preflight: malformed AST node file %s: %s", ast_path, e)
        print(f"[preflight] warning: malformed AST node file ({ast_path}): {e}")
        return

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as e:
        logging.warning("preflight: malformed config %s: %s", config_path, e)
        print(f"[preflight] warning: malformed config ({config_path}): {e}")
        return

    # Extract excluded identifiers from AST nodes (isException: 1)
    exc_all_names = set()
    if isinstance(ast_list, list):
        for item in ast_list:
            if isinstance(item, dict):
                name = str(item.get("A_name", "")).strip()
                is_exception = item.get("isException", 0)
                if name and is_exception == 1:
                    exc_all_names.add(name)

    cfg_sets = _collect_config_sets(cfg)

    conflicts = {
        "obf_include_vs_exception": cfg_sets["inc_obf"] & exc_all_names,
        "obf_exclude_vs_exception": cfg_sets["exc_obf"] & exc_all_names,
        "enc_include_vs_exception": cfg_sets["inc_enc"] & exc_all_names,
        "enc_exclude_vs_exception": cfg_sets["exc_enc"] & exc_all_names,
    }

    any_conflict = any(conflicts[k] for k in conflicts)
    if any_conflict:
        for key, vals in conflicts.items():
            if vals:
                sample = ", ".join(sorted(list(vals))[:10])
                print(f"  - {key}: {len(vals)}건 (예: {sample})")
        if fail_on_conflict:
            raise SystemExit("[preflight] conflicts detected; aborting due to fail_on_conflict=True")
    else:
        print("[preflight] 제외 대상과 config 충돌 없음 ✅")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swingft",
        description="Swingft CLI",
        formatter_class=_HelpFmt,
        add_help=True,
    )

    parser.add_argument("--version", action="version", version="Swingft CLI 1.0")

    # top-level --json (generate example config and exit)
    parser.add_argument(
        "--json",
        nargs="?",
        const="swingft_config.json",
        metavar="JSON_PATH",
        help="Generate an example exclusion config JSON and exit (default: swingft_config.json)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # run command (config-driven I/O)
    obf = sub.add_parser(
        "run",
        help="Obfuscate Swift files",
        formatter_class=_HelpFmt,
        description=(
            "Run obfuscation based on the config file. Input/output are read from\n"
            "project.input/project.output in the config. Provide config path via\n"
            "-i/--input or -c/--config (defaults to swingft_config.json)."
        ),
    )
    obf.add_argument(
        "--input", "-i", dest="config", nargs="?", const="swingft_config.json",
        help="Path to config JSON (default when flag present: swingft_config.json)",
    )
    obf.add_argument(
        "--config", "-c", dest="config", nargs="?", const="swingft_config.json",
        help="Alias to specify config JSON (default when flag present: swingft_config.json)",
    )
    obf.add_argument(
        "--check-rules", action="store_true",
        help="Scan project and print which identifiers from config are present",
    )
    obf.add_argument(
        "--encryption-only", action="store_true",
        help="Show only encryption-related logs",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # top-level: generate example config and exit
    if getattr(args, "json", None) is not None:
        handle_generate_json(args.json)
        return 0

    if args.command == "run":
        # Sync CLI paths into config via env; config.py will write back to JSON
        # ensure a default config path when none is provided
        if not getattr(args, "config", None):
            setattr(args, "config", "swingft_config.json")
        # Ensure JSON gets updated for future runs
        os.environ.setdefault("SWINGFT_WRITE_BACK", "1")

        # 규칙 검사 출력 비활성화: 프리플라이트만 유지
        if hasattr(args, "check_rules") and args.check_rules:
            args.check_rules = False

        handle_obfuscate(args)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())