from __future__ import annotations

import os
import sys


def supports_color() -> bool:
    try:
        v = os.environ.get("SWINGFT_TUI_COLOR", "1")
        if str(v).strip().lower() in {"0", "false", "no", "off"}:
            return False
        return sys.stdout.isatty()
    except (OSError, AttributeError) as e:
        import logging
        logging.trace("supports_color check failed: %s", e)
        return False


def blue(s: str) -> str:
    return f"\x1b[34m{s}\x1b[0m"


def yellow(s: str) -> str:
    return f"\x1b[33m{s}\x1b[0m"


def gray(s: str) -> str:
    return f"\x1b[90m{s}\x1b[0m"


def bold(s: str) -> str:
    return f"\x1b[1m{s}\x1b[0m"


def print_warning_block(header: str, items: list[str]) -> None:
    """Print warning header, then exactly one blank line, then the bullet list.
    No leading/trailing extra blank lines.
    """
    try:
        if supports_color():
            sys.stdout.write(blue("[Warning]") + yellow(f" {header}") + "\n\n")  # header + one blank line
            for it in items:
                sys.stdout.write("  " + gray("-") + " " + bold(yellow(str(it))) + "\n")
        else:
            sys.stdout.write(f"[Warning] {header}\n\n")
            for it in items:
                sys.stdout.write(f"  - {it}\n")
        sys.stdout.flush()
    except (OSError, UnicodeEncodeError, BrokenPipeError) as e:
        import logging
        logging.trace("print_warning_block stdout write failed: %s", e)
        # Fallback to simple prints if direct writes fail
        if supports_color():
            print(blue("[Warning]") + yellow(f" {header}"))
            print("")
            for it in items:
                print("  " + gray("-") + " " + bold(str(it)))
        else:
            print(f"[Warning] {header}")
            print("")
            for it in items:
                print(f"  - {it}")


