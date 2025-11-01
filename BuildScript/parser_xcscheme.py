import xml.etree.ElementTree as ET
import json
import sys
from pathlib import Path

# ---------- xcscheme 파서 ----------
def parse_xcscheme(xcscheme_path: Path):
    tree = ET.parse(xcscheme_path)
    root = tree.getroot()
    scheme_name = xcscheme_path.stem

    build_entries = root.findall(".//BuildActionEntry/BuildableReference")
    targets = {ref.attrib.get("BlueprintName"): "all" for ref in build_entries if ref is not None}

    def config_for(action_name, default="Debug"):
        elem = root.find(action_name)
        return elem.attrib.get("buildConfiguration", default) if elem is not None else default

    return {
        "schemes": {
            scheme_name: {
                "build": {"targets": targets},
                "run": {"config": config_for("LaunchAction", "Debug")},
                "archive": {"config": config_for("ArchiveAction", "Release")},
                "profile": {"config": config_for("ProfileAction", "Release")},
                "analyze": {"config": config_for("AnalyzeAction", "Debug")},
            }
        }
    }

# ---------- pbxproj 파서 (요약 정보용) ----------
def parse_pbxproj(pbxproj_path: Path):
    text = pbxproj_path.read_text(errors="ignore")
    targets = [line.strip() for line in text.splitlines() if "PBXNativeTarget" in line]
    return {
        "project": pbxproj_path.parent.stem,
        "pbxproj_path": str(pbxproj_path),
        "target_count": len(targets)
    }

def parse_args(argv):
    """
    사용법:
      python parser_xcscheme.py /path/YourProject.xcodeproj [출력폴더] [--pretty]
      python parser_xcscheme.py /path/YourProject.xcodeproj --out /custom/output --pretty
    """
    if len(argv) < 2:
        print("❌ Usage: python parser_xcscheme.py /path/to/YourProject.xcodeproj [출력폴더] [--pretty] [--out DIR]")
        sys.exit(1)

    project_arg = Path(argv[1]).resolve()
    if not project_arg.exists():
        print(f"❌ 경로를 찾을 수 없습니다: {project_arg}")
        sys.exit(1)

    pretty = False
    out_dir = None

    i = 2
    while i < len(argv):
        arg = argv[i]
        if arg == "--pretty":
            pretty = True
        elif arg.startswith("--out="):
            out_dir = Path(arg.split("=", 1)[1]).resolve()
        elif arg == "--out" and i + 1 < len(argv):
            out_dir = Path(argv[i + 1]).resolve()
            i += 1
        elif not arg.startswith("-") and out_dir is None:
            # 두 번째 위치 인자로 출력 폴더 허용
            out_dir = Path(arg).resolve()
        i += 1

    # 기본 출력 폴더: .xcodeproj 상위 폴더의 output
    if out_dir is None:
        base_dir = project_arg.parent  # .../YourProj.xcodeproj 의 상위
        out_dir = base_dir / "output"

    return project_arg, out_dir, pretty

# ---------- 메인 ----------
def main():
    project_path, output_dir, pretty = parse_args(sys.argv)

    pbxproj_path = project_path / "project.pbxproj"
    if not pbxproj_path.exists():
        print("❌ project.pbxproj 파일이 없습니다.")
        sys.exit(1)

    # pbxproj 정보
    pbxproj_info = parse_pbxproj(pbxproj_path)

    # 스킴 검색 (공유 또는 로컬)
    scheme_info = {}
    # 우선순위: 공유 스킴 -> 프로젝트 내부 스킴
    search_roots = [
        project_path / "xcshareddata/xcschemes",
        project_path / "xcuserdata",  # 로컬 사용자 스킴 폴더
        project_path,                 # fallback: 전체 탐색
    ]
    found = None
    for root in search_roots:
        if root.exists():
            for f in root.rglob("*.xcscheme"):
                found = f
                break
        if found:
            break
    if not found:
        # 마지막 보루: 전체 프로젝트 아래에서 첫 번째 .xcscheme
        for f in project_path.rglob("*.xcscheme"):
            found = f
            break

    if found:
        scheme_info = parse_xcscheme(found)
    else:
        scheme_info = {"schemes": {}}

    result = {
        "project_info": pbxproj_info,
        "scheme_info": scheme_info,
    }

    json_text = json.dumps(result, indent=2 if pretty else None, ensure_ascii=False)

    # 출력 경로 설정 및 저장
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{project_path.stem}_xcscheme.json"
    output_path.write_text(json_text, encoding="utf-8")
    print(f"✅ JSON 저장 완료: {output_path.resolve()}")

if __name__ == "__main__":
    main()
