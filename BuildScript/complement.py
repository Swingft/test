import yaml
import sys
import argparse
from pathlib import Path


def load_yaml(path: Path):
    if not path.exists():
        print(f"❌ 입력 파일을 찾을 수 없습니다: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True, width=1000)
    print(f"✅ 보강된 project.yml 저장 완료: {path.resolve()}")


def clean_resources(resources):
    """ .xcassets 내부 JSON 등 불필요한 세부 리소스 제거 """
    cleaned = []
    for r in resources:
        path = r.get("path") if isinstance(r, dict) else r
        if not isinstance(path, str):
            continue
        if "Assets.xcassets/" in path:
            # 내부 개별 이미지 파일은 제외하고, xcassets 루트만 유지
            continue
        if path.endswith(".json") and "LottieAnimation" not in path:
            # 단순 json 리소스는 제외 (Lottie 예외)
            continue
        cleaned.append({"path": path})
    return cleaned


def complement_yaml(data):
    # --- 1️⃣ name 수정
    if data.get("name") == "project" and data.get("targets"):
        data["name"] = list(data["targets"].keys())[0]
        print(f"🧩 name 수정: project → {data['name']}")

    # --- 2️⃣ deploymentTarget 통일
    if "options" in data:
        data["options"].setdefault("deploymentTarget", {"iOS": "15.5"})
        data["options"]["deploymentTarget"]["iOS"] = "15.5"
    if "settings" in data and "base" in data["settings"]:
        data["settings"]["base"]["IPHONEOS_DEPLOYMENT_TARGET"] = "15.5"

    # --- 3️⃣ targets 정리
    for target_name, target in (data.get("targets") or {}).items():
        # ✅ 중복 dependencies 제거
        unique_deps = []
        seen = set()
        for dep in target.get("dependencies", []) or []:
            dep_key = tuple(sorted(dep.items())) if isinstance(dep, dict) else ("__raw__", str(dep))
            if dep_key not in seen:
                seen.add(dep_key)
                unique_deps.append(dep)
        target["dependencies"] = unique_deps

        # ✅ resource 정리
        if "resources" in target and target["resources"]:
            target["resources"] = clean_resources(target["resources"])

        # ✅ sources 보강 (없을 경우)
        if not target.get("sources"):
            target["sources"] = [{"path": target_name}]

        # ✅ settings INFOPLIST_FILE 확인
        base_settings = (target.get("settings") or {}).get("base", {})
        if "INFOPLIST_FILE" not in base_settings:
            base_settings["INFOPLIST_FILE"] = f"{target_name}/Info.plist"
        target.setdefault("settings", {})["base"] = base_settings

    return data


def resolve_paths_from_project(project_arg: str, name_hint: str | None) -> Path:
    """
    - project_arg가 .xcodeproj면 그 상위 폴더 기준
    - 디렉토리면 그 폴더 기준
    output 폴더에서 *_project.yml (또는 name_hint_project.yml) 검색
    """
    p = Path(project_arg).resolve()
    base_dir = p.parent if p.suffix == ".xcodeproj" else p
    output_dir = base_dir / "output"

    if name_hint:
        candidate = output_dir / f"{name_hint}_project.yml"
        if candidate.exists():
            return candidate
        # 대소문자/케이스 차이 흡수용
        matches = list(output_dir.glob(f"*{name_hint}*_project.yml"))
        if matches:
            return sorted(matches, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        print(f"❌ 지정한 이름으로 project.yml을 찾을 수 없습니다: {candidate}")
        sys.exit(1)

    # 이름 힌트 없으면 최신 *_project.yml 선택
    candidates = list(output_dir.glob("*_project.yml"))
    if not candidates:
        print(f"❌ project.yml 파일을 찾을 수 없습니다: {output_dir}/*_project.yml")
        sys.exit(1)
    # 가장 최근 수정된 파일 선택
    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description="XcodeGen project.yml 보강 스크립트")
    parser.add_argument("input_yml", nargs="?", help="입력 project.yml 경로")
    parser.add_argument("output_yml", nargs="?", help="출력 yml 경로 (옵션)")
    parser.add_argument("-p", "--project", help=".xcodeproj 경로 또는 그 상위 폴더")
    parser.add_argument("--name", help="프로젝트 이름 힌트 (예: SwiftRadio)")
    args = parser.parse_args()

    # 우선순위:
    # 1) input_yml 직접 지정
    # 2) --project 로부터 자동 탐색 (옵션: --name)
    if args.input_yml:
        input_path = Path(args.input_yml).resolve()
    elif args.project:
        input_path = resolve_paths_from_project(args.project, args.name)
    else:
        print("❌ 사용법:")
        print("   python3 complement.py <input_yml 경로> [출력_yml 경로]")
        print("   또는")
        print("   python3 complement.py -p <.xcodeproj 또는 그 상위 폴더> [--name SwiftRadio]")
        sys.exit(1)

    # 출력 경로 결정: 지정 없으면 같은 폴더에 *_final.yml
    if args.output_yml:
        output_path = Path(args.output_yml).resolve()
    else:
        output_path = input_path.parent / f"{input_path.stem}_final.yml"

    print(f"🗂  입력: {input_path}")
    print(f"📝 출력: {output_path}")

    data = load_yaml(input_path)
    updated = complement_yaml(data or {})
    save_yaml(updated, output_path)


if __name__ == "__main__":
    main()
