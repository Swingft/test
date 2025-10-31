"""
json_cmd.py: Generate an example exclusion configuration JSON in the swingft_config.json format.
"""

import json
import sys
import logging

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

def handle_generate_json(json_path: str) -> None:
    """
    예시 제외목록 JSON 파일을 생성합니다.
    """
    example = {
        "_comment_path": "Specify the absolute path to your project. The output path is optional.",
        "project": {
            "input": "/Users/Project/Root/Path",
            "output": "/Users/Project/Root/Path_obf",
            "build_target": "MySwiftProject"
        },
        "options": {
            "Obfuscation_identifiers": True,
            "Obfuscation_controlFlow": True,
            "Delete_debug_symbols": True,
            "Encryption_strings": True
        },
        "_comment_exclude": "The following section is optional and can be customized as needed.",
        "exclude": {
            "obfuscation": [
                "sampleClass",
                "sampleFunction",
                "sampleVariable",
                "sampleProperty",
                "sampleProtocol",
                "sampleStructure",
                "**Wildcard"
            ],
            "encryption": [
                "someString",
                "**Wildcard"
            ]
        },
        "_comment_include": "You can explicitly include items to always obfuscate/encrypt, regardless of global settings.",
        "include": {
            "obfuscation": [
                "sampleClass",
                "sampleFunction",
                "sampleVariable",
                "sampleProperty",
                "sampleProtocol",
                "sampleStructure",
                "**Wildcard"
            ],
            "encryption": [
                "someString",
                "**Wildcard"
            ]
        }
        ,
        "_comment_conflict_policy": "ask | force | skip — include/exclude vs rules conflict resolution: ask=prompt user, force=override, skip=ignore",
        "preflight": {
            "conflict_policy": "ask" 
        }
    }
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(example, f, indent=2, ensure_ascii=False)
        print(f"Example exclusion JSON file has been created: {json_path}")
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as e:
        _trace("json_cmd: failed to write JSON %s: %s", json_path, e)
        _maybe_raise(e)
        print(f"Error writing JSON to {json_path}: {e}", file=sys.stderr)
        sys.exit(1)