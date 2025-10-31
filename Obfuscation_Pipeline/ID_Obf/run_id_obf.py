#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, json, shutil, subprocess
import logging
from pathlib import Path

# local trace / strict helpers
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

ROOT = Path(__file__).resolve().parents[1]  # Obfuscation_Pipeline
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Mapping.run_mapping import mapping
from ID_Obf.id_dump import make_dump_file_id


def to_bool(v, default=True):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}
    if isinstance(v, (int, float)):
        return bool(v)
    return default


def load_config(path: Path | None) -> dict:
    if not path:
        return {}
    try:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError) as e:
                _trace("load_config: failed to read/parse %s: %s", path, e)
                _maybe_raise(e)
                return {}
    except (OSError, UnicodeError) as e:
        _trace("load_config: path check failed %s: %s", path, e)
        _maybe_raise(e)
    return {}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Identifiers obfuscation runner with config gating")
    ap.add_argument("--root", required=True, help="Obfuscation_Pipeline root path")
    ap.add_argument("--project", required=True, help="Target project (obfuscated) path")
    ap.add_argument("--config", help="Swingft_config.json path (optional)")
    args = ap.parse_args()

    obf_root = Path(args.root).resolve()
    project = Path(args.project).resolve()

    cfg_env = os.environ.get("SWINGFT_WORKING_CONFIG")
    cfg_path = Path(cfg_env).resolve() if cfg_env else (Path(args.config).resolve() if args.config else (obf_root / "Swingft_config.json"))
    cfg = load_config(cfg_path)

    if not to_bool(cfg.get("Obfuscation_identifiers", True), True):
        print("[ID_Obf] Obfuscation_identifiers=false → skip identifiers mapping/obfuscation")
        return

    # 1) Mapping
    mapping()

    # 2) Build and run IDOBF
    target_project_dir = obf_root / "ID_Obf"
    target_name = "IDOBF"
    swift_list = obf_root / "swift_file_list.txt"
    mapping_result = obf_root / "mapping_result_s.json"

    os.chdir(target_project_dir)
    try:
        build_marker_file = Path(".build") / "build_path.txt"
        previous = ""
        try:
            if build_marker_file.exists():
                previous = build_marker_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as e:
            _trace("build marker read failed %s: %s", build_marker_file, e)
            _maybe_raise(e)
            previous = ""
        current = str((target_project_dir / ".build").resolve())
        if previous != current or not previous:
            try:
                subprocess.run(["swift", "package", "clean"], check=True)
                shutil.rmtree(".build", ignore_errors=True)
                subprocess.run(["swift", "build"], check=True)
            except (OSError, subprocess.CalledProcessError) as e:
                _trace("swift build failed: %s", e)
                _maybe_raise(e)
                sys.exit(1)
        try:
            subprocess.run(["swift", "run", target_name, str(mapping_result), str(swift_list)], check=True)
        except (OSError, subprocess.CalledProcessError) as e:
            _trace("swift run failed: %s", e)
            _maybe_raise(e)
            sys.exit(1)
    finally:
        os.chdir(str(ROOT))

    # 3) Dump
    make_dump_file_id(str(project), str(project))


if __name__ == "__main__":
    main()
