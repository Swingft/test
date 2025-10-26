import os
import re
import sys
import base64
import secrets
import shutil
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional, Dict, List, Set
from json import JSONDecodeError

try:
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
except ImportError:
    import subprocess
    venv_dir = Path.cwd() / "venv"
    python_exec = venv_dir / "bin" / "python"
    try:
        if not venv_dir.exists():
            subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.check_call([str(python_exec), "-m", "pip", "install", "--upgrade", "pip", "-q"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.check_call([str(python_exec), "-m", "pip", "install", "cryptography", "-q"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.execv(str(python_exec), [str(python_exec)] + sys.argv)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to auto-install 'cryptography': {e}", file=sys.stderr)
        sys.exit(2)

KEY_BYTE_LEN = 32

SWIFT_SIMPLE_ESCAPES = {
    r'\n': '\n', r'\r': '\r', r'\t': '\t',
    r'\"': '\"',  r"\'": "'", r'\\': '\\', r'\0': '\0',
}

def load_build_target_from_config(cfg_path: Optional[str]) -> Optional[str]:
    if not cfg_path:
        return None
    p = Path(cfg_path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        bt = (((data or {}).get("project") or {}).get("build_target") or "").strip()
        return bt or None
    except (OSError, JSONDecodeError) as e:
        print(f"[WARN] Failed to read config {p}: {e}", file=sys.stderr)
        return None

def load_targets_map(targets_json_path: Optional[str]) -> Dict[str, List[str]]:
    if not targets_json_path:
        return {}
    p = Path(targets_json_path)
    if not p.exists():
        return {}
    try:
        m = json.loads(p.read_text(encoding='utf-8'))
        out: Dict[str, List[str]] = {}
        for k, v in (m or {}).items():
            if isinstance(v, list):
                out[str(k)] = [str(x) for x in v]
        return out
    except (OSError, JSONDecodeError) as e:
        print(f"[WARN] Failed to load targets map {p}: {e}", file=sys.stderr)
        return {}

def choose_target_name(cands: List[str], want: str) -> Optional[str]:
    lw = want.lower()
    for c in cands:
        if c == want or c.lower() == lw:
            return c
    subs = [c for c in cands if lw in c.lower()]
    return subs[0] if len(subs) == 1 else None

def pick_files_for_target(cfg_path: Optional[str], targets_json_path: Optional[str]) -> List[str]:
    bt = load_build_target_from_config(cfg_path)
    if not bt:
        return []
    tmap = load_targets_map(targets_json_path)
    if not tmap:
        return []
    name = choose_target_name(list(tmap.keys()), bt)
    if not name:
        print(f"[WARN] build_target '{bt}' not found in map. Fallback to project-wide.", file=sys.stderr)
        return []
    paths = [os.path.realpath(p) for p in (tmap.get(name) or []) if os.path.isfile(p)]
    if not paths:
        print(f"[WARN] target '{name}' has no files. Fallback to project-wide.", file=sys.stderr)
    return sorted(set(paths))

def ensure_import(swift_file: str) -> bool:
    p = Path(swift_file)
    try:
        s = p.read_text(encoding='utf-8')
    except OSError:
        return False
    if 'import StringSecurity' in s:
        return False
    lines = s.splitlines(True)
    idx = next((i for i, l in enumerate(lines) if l.lstrip().startswith('import ')), 0)
    lines.insert(idx, 'import StringSecurity\n')
    try:
        p.write_text(''.join(lines), encoding='utf-8')
        return True
    except OSError:
        return False

def swift_unescape(s: str) -> str:
    def _u(m): return chr(int(m.group(1), 16))
    s = re.sub(r'\\u\{([0-9A-Fa-f]+)\}', _u, s)
    for k, v in SWIFT_SIMPLE_ESCAPES.items():
        s = s.replace(k, v)
    return s

def load_included_from_json(path: str):
    in_strings, in_lines = defaultdict(set), defaultdict(set)
    try:
        with open(path, encoding='utf-8') as f:
            items = json.load(f)
    except (OSError, JSONDecodeError) as e:
        print(f"[ERROR] Cannot load included JSON: {path} ({e})", file=sys.stderr)
        return in_strings, in_lines

    for obj in items:
        if (obj.get("kind") or "").upper() != "STR":
            continue
        file_raw = obj.get("file", "")
        abs_file = os.path.realpath(re.sub(r"^(?:STR|NUM)\s*:\s*", "", file_raw))
        line = obj.get("line")
        val = obj.get("value")
        if not abs_file or val is None:
            continue
        if isinstance(line, int) and line > 0:
            in_lines[abs_file].add(line)
        in_strings[abs_file].add(str(val))
    return in_strings, in_lines

def line_no_of(text: str, pos: int) -> int:
    return text.count('\\n', 0, pos) + 1

def encrypt_and_insert(source_root: str, included_json_path: str,
                       cfg_path: Optional[str] = None,
                       targets_json_path: Optional[str] = None):
    in_strings, in_lines = load_included_from_json(included_json_path)
    STRING_RE = re.compile(r'("""(?:\\.|"(?!""")|[^"])*?"""|"(?:\\.|[^"\\])*")', re.DOTALL)

    key = ChaCha20Poly1305.generate_key()
    cipher = ChaCha20Poly1305(key)
    modified: Set[str] = set()

    for root, _, files in os.walk(source_root):
        for fn in files:
            if not fn.endswith(".swift"):
                continue
            fp = os.path.join(root, fn)
            try:
                content = Path(fp).read_text(encoding='utf-8')
            except OSError:
                continue

            abs_fp = os.path.realpath(fp)
            in_vals = in_strings.get(abs_fp, set())
            allowed_lines = in_lines.get(abs_fp, set())
            allowed_window = allowed_lines | {ln + 1 for ln in allowed_lines}

            def replace(m):
                raw = m.group(0)
                if raw not in in_vals:
                    return raw
                cur_ln = line_no_of(content, m.start())
                if allowed_window and cur_ln not in allowed_window:
                    return raw
                inner = raw[3:-3] if raw.startswith('"""') else raw[1:-1]
                plain = swift_unescape(inner)
                nonce = secrets.token_bytes(12)
                ct = cipher.encrypt(nonce, plain.encode(), None)
                b64 = base64.b64encode(nonce + ct).decode()
                return f'SwingftEncryption.resolve("{b64}")'

            new_c = re.sub(STRING_RE, replace, content)
            if new_c != content:
                try:
                    Path(fp).write_text(new_c, encoding='utf-8')
                    modified.add(fp)
                except OSError as e:
                    print(f"[WARN] write failed {fp}: {e}", file=sys.stderr)

    if not modified:
        print("[INFO] No encrypted strings found. Exiting.")
        return

    for _p in modified:
        ensure_import(_p)

    print(f"[Swingft] Encrypted and patched {len(modified)} file(s).")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python SwingftEncryption.py <source_root> <strings.json> [config] [targets_paths]")
        sys.exit(1)
    src = sys.argv[1]
    js = sys.argv[2]
    cfg = sys.argv[3] if len(sys.argv) >= 4 else None
    tgt = sys.argv[4] if len(sys.argv) >= 5 else None
    encrypt_and_insert(src, js, cfg, tgt)
