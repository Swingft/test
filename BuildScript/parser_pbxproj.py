import os
import sys
import json
from pathlib import Path
from pbxproj import XcodeProject


# ✅ PBXGenericObject를 dict로 안전 변환
def safe_dict(obj):
    """PBXGenericObject나 dict, 혹은 None을 안전하게 dict로 변환."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "get_keys"):  # PBXGenericObject의 경우
        return {k: obj[k] for k in obj.get_keys()}
    return {}  # 알 수 없는 타입은 빈 dict로 반환


# ✅ Package.resolved 파서
def parse_package_resolved(resolved_path: Path):
    """Package.resolved에서 패키지 버전/브랜치 정보를 추출"""
    if not resolved_path or not resolved_path.exists():
        print(f"⚠️ Package.resolved 파일을 찾을 수 없습니다: {resolved_path}")
        return {}

    print(f"📦 Package.resolved 분석 중: {resolved_path}")
    versions = {}

    try:
        data = json.loads(resolved_path.read_text(encoding="utf-8"))
        pins = data.get("pins", []) or data.get("object", {}).get("pins", [])
        for pin in pins:
            identity = pin.get("identity") or Path(pin.get("package", "")).stem.lower()
            state = pin.get("state", {})
            info = {}
            if "version" in state:
                info["version"] = state["version"]
            elif "branch" in state:
                info["branch"] = state["branch"]
            elif "revision" in state:
                info["revision"] = state["revision"]
            versions[identity.lower()] = info
    except Exception as e:
        print(f"⚠️ Package.resolved 파싱 실패: {e}")

    return versions


# ✅ Package.resolved 탐색 함수
def find_package_resolved(base_path: Path):
    """Package.resolved를 여러 경로에서 탐색"""
    search_paths = [
        base_path.parent / "project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
        base_path / "project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
        base_path / "xcshareddata/swiftpm/Package.resolved",
        base_path.parent / "Package.resolved",
        base_path / "Package.resolved",
    ]

    for p in search_paths:
        if p.exists():
            print(f"✅ Package.resolved 발견: {p}")
            return p

    print("⚠️ Package.resolved 파일을 찾을 수 없습니다. (검색 경로 모두 확인됨)")
    return None


def export_pbxproj_to_json(pbxproj_path: Path, output_dir: Path):
    if not pbxproj_path.exists():
        print(f"❌ 파일을 찾을 수 없습니다: {pbxproj_path}")
        sys.exit(1)

    print(f"🔍 '{pbxproj_path}' 파일을 파싱 중입니다...")

    project = XcodeProject.load(str(pbxproj_path))

    # === 프로젝트 이름 ===
    root_projects = project.objects.get_objects_in_section("PBXProject")
    root_project = (
        list(root_projects.values())[0]
        if isinstance(root_projects, dict)
        else root_projects[0]
    )
    project_name = getattr(root_project, "name", None) or Path(pbxproj_path).stem

    result = {
        "project_name": project_name,
        "targets": [],
        "packages": [],
        "linked_frameworks": [],   # ✅ 시스템/로컬 프레임워크 리스트 추가
        "build_settings": {},
    }

    # === Targets ===
    all_targets = []
    for section_name in [
        "PBXNativeTarget",
        "PBXAggregateTarget",
        "PBXLegacyTarget",
        "PBXTestTarget",  # ✅ 테스트 타겟 포함
    ]:
        section_targets = project.objects.get_objects_in_section(section_name)
        if not section_targets:
            continue

        if isinstance(section_targets, dict):
            all_targets.extend(section_targets.values())
        else:
            all_targets.extend(section_targets)

    print(f"🎯 총 {len(all_targets)}개 타겟 탐지됨")

    for target in all_targets:
        target_name = getattr(target, "name", "UnknownTarget")
        target_type = getattr(target, "productType", "UnknownType")

        target_info = {
            "name": target_name,
            "product_type": target_type,
            "configurations": [],
        }

        # === Swift Package Dependencies 추출 ===
        package_deps = []
        if hasattr(target, "packageProductDependencies"):
            for dep_id in getattr(target, "packageProductDependencies", []):
                dep_obj = project.get_object(dep_id)
                if dep_obj:
                    product_name = getattr(dep_obj, "productName", None)
                    package_ref = getattr(dep_obj, "package", None)
                    package_obj = project.get_object(package_ref) if package_ref else None
                    repo_url = getattr(package_obj, "repositoryURL", None)
                    if repo_url and product_name:
                        package_deps.append({
                            "package": Path(repo_url).stem.lower().replace(".git", ""),
                            "productName": product_name
                        })

        target_info["packageProductDependencies"] = package_deps

        # === Build Configurations ===
        config_list = project.get_object(getattr(target, "buildConfigurationList", None))
        if config_list:
            for config_uuid in getattr(config_list, "buildConfigurations", []):
                config = project.get_object(config_uuid)
                if not config:
                    continue
                build_settings_raw = getattr(config, "buildSettings", {})
                build_settings = safe_dict(build_settings_raw)
                safe_settings = {
                    str(k): str(v)
                    for k, v in build_settings.items()
                    if isinstance(v, (str, int, float))
                }
                config_name = getattr(config, "name", "Unknown")
                target_info["configurations"].append(
                    {"name": config_name, "settings": safe_settings}
                )
                result["build_settings"][config_name] = safe_settings

        result["targets"].append(target_info)

    # === Linked Frameworks (System / Custom) === ✅ 완전 개선 버전
    linked_frameworks = set()

    # 1️⃣ 모든 Frameworks Build Phase 탐색
    build_phases = project.objects.get_objects_in_section("PBXFrameworksBuildPhase") or []
    if isinstance(build_phases, dict):
        build_phases = build_phases.values()

    for phase in build_phases:
        files = getattr(phase, "files", []) or []
        for file_id in files:
            build_file = project.get_object(file_id)
            if not build_file:
                continue

            file_ref = getattr(build_file, "fileRef", None)
            if not file_ref:
                continue

            file_obj = project.get_object(file_ref)
            if not file_obj:
                continue

            path = getattr(file_obj, "path", None)
            name = getattr(file_obj, "name", None)

            if path and path.endswith(".framework"):
                linked_frameworks.add(Path(path).name)
            elif name and name.endswith(".framework"):
                linked_frameworks.add(Path(name).name)

    # 2️⃣ Fallback: PBXBuildFile 섹션에서 직접 찾기 (혹시 누락된 경우)
    framework_refs = project.objects.get_objects_in_section("PBXBuildFile") or []
    if isinstance(framework_refs, dict):
        build_files = framework_refs.values()
    else:
        build_files = framework_refs

    for ref in build_files:
        file_ref = getattr(ref, "fileRef", None)
        if not file_ref:
            continue
        file_obj = project.get_object(file_ref)
        if not file_obj:
            continue
        path = getattr(file_obj, "path", "")
        if path.endswith(".framework"):
            linked_frameworks.add(Path(path).name)

    # ✅ 결과 저장
    result["linked_frameworks"] = sorted(linked_frameworks)
    print(f"📚 Linked frameworks: {', '.join(linked_frameworks) if linked_frameworks else '없음'}")

    # === Swift Packages ===
    package_refs = project.objects.get_objects_in_section("XCRemoteSwiftPackageReference")
    packages = package_refs.values() if isinstance(package_refs, dict) else package_refs

    # === Package.resolved 탐색 및 분석 ===
    base_path = Path(pbxproj_path).parent  # .../YourProj.xcodeproj
    resolved_path = find_package_resolved(base_path)
    package_versions = parse_package_resolved(resolved_path) if resolved_path else {}

    for package_ref in packages:
        url = getattr(package_ref, "repositoryURL", None)
        name = Path(url).stem.lower().replace(".git", "") if url else None

        pkg_entry = {
            "name": name,
            "repositoryURL": url,
        }

        # 버전 정보 병합
        if name and name.lower() in package_versions:
            pkg_entry.update(package_versions[name.lower()])

        result["packages"].append(pkg_entry)

    # === JSON 저장 ===
    output_dir.mkdir(parents=True, exist_ok=True)
    project_basename = Path(pbxproj_path).parent.stem
    output_path = output_dir / f"{project_basename}_xcodeproj.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ JSON 파일 생성 완료: {output_path.resolve()}")


def main():
    if len(sys.argv) < 2:
        print(f"❗️사용법: python3 {Path(sys.argv[0]).name} /경로/YourProject.xcodeproj [출력폴더]")
        sys.exit(1)

    arg_path = Path(sys.argv[1]).resolve()

    if len(sys.argv) > 2:
        output_dir = Path(sys.argv[2]).resolve()
    else:
        if arg_path.suffix == ".xcodeproj":
            base_dir = arg_path.parent
        elif arg_path.name == "project.pbxproj":
            base_dir = arg_path.parent.parent
        else:
            base_dir = arg_path if arg_path.is_dir() else arg_path.parent
        output_dir = base_dir / "output"

    pbxproj_path = (
        arg_path / "project.pbxproj"
        if arg_path.suffix == ".xcodeproj"
        else arg_path
    )

    export_pbxproj_to_json(pbxproj_path, output_dir)


if __name__ == "__main__":
    main()
