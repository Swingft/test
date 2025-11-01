import os
import sys
import json
from pathlib import Path


def scan_project_structure(project_path: Path):
    """
    Xcode 프로젝트 폴더를 스캔해 주요 소스/리소스/프레임워크/로컬 패키지 정보를 추출
    """
    if not project_path.exists():
        print(f"❌ 경로를 찾을 수 없습니다: {project_path}")
        sys.exit(1)

    project_name = project_path.stem.replace(".xcodeproj", "")

    # ✅ 결과 구조
    result = {
        "project_name": project_name,
        "sources": [],
        "resources": [],
        "frameworks": [],
        "local_packages": [],
    }

    root_dir = project_path.parent

    # === 1️⃣ Frameworks (.xcframework)
    print("🔍 프레임워크(.xcframework) 탐색 중...")
    for fw in root_dir.rglob("*.xcframework"):
        # 무시할 경로 필터 (DerivedData, .build 등)
        if any(skip in str(fw) for skip in [".git", "output", "DerivedData", ".build", "__MACOSX"]):
            continue
        rel = fw.relative_to(root_dir)
        result["frameworks"].append(str(rel))
    print(f"✅ {len(result['frameworks'])}개의 프레임워크 탐지 완료")

    # === 2️⃣ Local Swift Packages (Package.swift 존재)
    for pkg in root_dir.iterdir():
        if pkg.is_dir() and (pkg / "Package.swift").exists():
            rel = pkg.relative_to(root_dir)
            result["local_packages"].append(f"./{rel}")

    # === 3️⃣ Sources / Resources 스캔 ===
    print("📁 소스 및 리소스 스캔 중...")
    for dirpath, dirnames, filenames in os.walk(root_dir):
        p = Path(dirpath)
        rel = p.relative_to(root_dir)

        # 무시할 폴더들
        if any(skip in str(rel) for skip in [".git", "output", ".build", "DerivedData", "__MACOSX"]):
            continue

        # Swift / ObjC 파일이 있는 폴더 → sources
        if any(f.endswith((".swift", ".m", ".h")) for f in filenames):
            if str(rel) not in result["sources"]:
                result["sources"].append(str(rel))

        # Resource 파일들
        resource_exts = (".xcassets", ".plist", ".xcprivacy", ".json", ".lproj", ".strings")
        for f in filenames:
            if f.endswith(resource_exts):
                file_path = p / f
                rel_file = file_path.relative_to(root_dir)
                if str(rel_file) not in result["resources"]:
                    result["resources"].append(str(rel_file))

        # Resource 폴더들 (예: Base.lproj, Font 등)
        for d in dirnames:
            if d.endswith(".xcassets") or d.endswith(".lproj") or d.lower() in ["font", "assets"]:
                dir_path = p / d
                rel_dir = dir_path.relative_to(root_dir)
                if str(rel_dir) not in result["resources"]:
                    result["resources"].append(str(rel_dir))

    print(f"✅ 소스 {len(result['sources'])}개, 리소스 {len(result['resources'])}개 탐지 완료")

    return result


def main():
    if len(sys.argv) < 2:
        print("❌ 사용법: python3 parser_structure.py /경로/YourProject.xcodeproj [출력폴더]")
        sys.exit(1)

    project_path = Path(sys.argv[1]).resolve()
    if project_path.suffix != ".xcodeproj":
        print("⚠️ .xcodeproj 경로를 입력해야 합니다.")
        sys.exit(1)

    # 프로젝트 스캔
    structure_info = scan_project_structure(project_path)

    # === 결과 저장 ===
    if len(sys.argv) >= 3:
        output_dir = Path(sys.argv[2]).resolve()
    else:
        output_dir = project_path.parent / "output"

    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{project_path.stem}_structure.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(structure_info, f, ensure_ascii=False, indent=2)

    print(f"✅ 구조 분석 완료: {output_path.resolve()}")


if __name__ == "__main__":
    main()
