import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, Tuple, List


def read_json(p: Path) -> dict:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[Swingft] ERROR: JSON file not found: {p}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"[Swingft] ERROR: JSON parse failed ({p}): {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"[Swingft] ERROR: I/O error while reading {p}: {e}", file=sys.stderr)
        sys.exit(2)


def to_bool(v) -> bool:
    if isinstance(v, bool): return v
    if isinstance(v, str): return v.strip().lower() in {"1","true","yes","y","on"}
    if isinstance(v, (int, float)): return bool(v)
    return False


def find_key_ci(obj, key_name: str) -> Optional[bool]:
    target = key_name.lower()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() == target:
                return to_bool(v)
        for v in obj.values():
            r = find_key_ci(v, key_name)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = find_key_ci(it, key_name)
            if r is not None:
                return r
    return None


def run_streamed(cmd: List[str], cwd: Optional[Path], tag: str) -> int:
    env = os.environ.copy()
    env.setdefault("SWINGFT_ENC_STDERR_TO_STDOUT", "1")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
    except OSError as e:
        print(f"[Swingft] ERROR: Failed to launch {cmd[0]}: {e}", file=sys.stderr)
        return 1

    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
    return proc.wait()


def run_parallel(cmdA: List[str], tagA: str,
                 cmdB: List[str], tagB: str,
                 cwd: Optional[Path]) -> Tuple[int, int]:
    rcA = rcB = 999

    def ta():
        nonlocal rcA
        rcA = run_streamed(cmdA, cwd, tagA)

    def tb():
        nonlocal rcB
        rcB = run_streamed(cmdB, cwd, tagB)

    t1 = threading.Thread(target=ta, daemon=True)
    t2 = threading.Thread(target=tb, daemon=True)
    t1.start(); t2.start()
    t1.join();  t2.join()
    return rcA, rcB


def newest_matching(root: Path, pattern: re.Pattern) -> Optional[Path]:
    newest_p, newest_t = None, -1
    for p in root.rglob("*.json"):
        if not pattern.search(p.name):
            continue
        try:
            t = p.stat().st_mtime
        except OSError:
            continue
        if t > newest_t:
            newest_p, newest_t = p, t
    return newest_p


def main():
    build_marker_file = Path(".build") / "build_path.txt"
    previous_build_path = ""
    if build_marker_file.exists():
        try:
            previous_build_path = build_marker_file.read_text(encoding="utf-8").strip()
        except OSError as e:
            logging.trace("read_text() failed for build_marker_file: %s", e)
            previous_build_path = ""

    current_build_path = Path(".build").resolve()
    if previous_build_path != str(current_build_path) or not previous_build_path:
        subprocess.run(["swift", "package", "clean"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(current_build_path, ignore_errors=True)
        subprocess.run(["swift", "build"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            build_marker_file.parent.mkdir(parents=True, exist_ok=True)
            build_marker_file.write_text(str(current_build_path), encoding="utf-8")
        except OSError as e:
            print(f"[Swingft] WARN: Failed to record build path: {e}", file=sys.stderr)

    ap = argparse.ArgumentParser(description="Run Swingft pipeline, gated by Encryption_strings")
    ap.add_argument("root_path", help="Project root path")
    ap.add_argument("config_path", help="Swingft_config.json path")
    args = ap.parse_args()

    root = Path(args.root_path).resolve()
    cfg  = Path(args.config_path).resolve()
    cfg_dir = Path.cwd()

    if not cfg.exists():
        print(f"[Swingft] ERROR: Config file not found: {cfg}", file=sys.stderr)
        sys.exit(2)

    cfg_json = read_json(cfg)
    flag = find_key_ci(cfg_json, "Encryption_strings")
    if not flag:
        print("[Swingft] Encryption_strings is false (or missing) → nothing to do.")
        return

    bin_path = current_build_path / "debug" / "Swingft_Encryption"
    cmd_a = [str(bin_path), str(root), str(cfg)] if bin_path.exists() else \
            ["swift", "run", "Swingft_Encryption", str(root), str(cfg)]

    script_dir = Path(__file__).parent.resolve()
    build_target_py = script_dir / "build_target.py"
    cmd_b = ["python3", str(build_target_py if build_target_py.exists() else "build_target.py"), str(root)]

    rcA, rcB = run_parallel(cmd_a, "A", cmd_b, "B", cwd=cfg_dir)
    if rcA != 0 or rcB != 0:
        print(f"[Swingft] ERROR: parallel step failed ({rcA=}, {rcB=})", file=sys.stderr)
        sys.exit(3)

    strings_json = cfg_dir / "strings.json"
    targets_json = cfg_dir / "targets_swift_paths.json"

    for target, pattern in [
        (strings_json, re.compile(r"^strings.*\.json$", re.I)),
        (targets_json, re.compile(r"^targets_swift_paths\.json$", re.I))
    ]:
        if not target.exists():
            cand = newest_matching(root, pattern)
            if cand:
                try:
                    shutil.copy2(cand, target)
                    print(f"[Swingft] Copied {target.name} from: {cand}")
                except OSError as e:
                    print(f"[Swingft] ERROR: Copy failed ({cand}): {e}", file=sys.stderr)
                    sys.exit(4)
            else:
                print(f"[Swingft] ERROR: {target.name} not found.", file=sys.stderr)
                sys.exit(4)

    swingft_enc_py = script_dir / "SwingftEncryption.py"
    cmd_c = [
        "python3",
        str(swingft_enc_py if swingft_enc_py.exists() else "SwingftEncryption.py"),
        str(root),
        str(strings_json),
        str(cfg),
        str(targets_json),
    ]
    rcC = run_streamed(cmd_c, cwd=cfg_dir, tag="C")
    if rcC != 0:
        print(f"[Swingft] ERROR: step failed with code {rcC}", file=sys.stderr)
        sys.exit(5)

    print("[Swingft] Encryption process completed successfully.")


if __name__ == "__main__":
    main()
