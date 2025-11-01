#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import yaml
from pathlib import Path

# ---------- 기본 유틸 ----------

def load_json(path: str):
    p = Path(path)
    if not p.exists():
        print(f"❌ JSON 파일을 찾을 수 없습니다: {p}")
        sys.exit(1)
    return json.loads(p.read_text(encoding="utf-8"))

def write_yaml(data, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True, width=1000)
    print(f"✅ project.yml 생성 완료: {out_path.resolve()}")

# ---------- 헬퍼 ----------

def is_test_target(name: str) -> bool:
    return "test" in name.lower()

def infer_ios_version(xproj_json):
    for cfg in xproj_json.get("build_settings", {}).values():
        v = cfg.get("IPHONEOS_DEPLOYMENT_TARGET")
        if v:
            return str(v)
    return "15.0"

def infer_bundle_prefix(xproj_json, project_name: str):
    for cfg in xproj_json.get("build_settings", {}).values():
        bid = cfg.get("PRODUCT_BUNDLE_IDENTIFIER")
        if bid and "." in bid:
            return ".".join(bid.split(".")[:-1])
    return f"com.{project_name.lower()}"

def ensure_unique_deps(deps):
    seen, result = set(), []
    for d in deps:
        key = (
            ("package", d.get("package"), d.get("product")) if "package" in d else
            ("framework", d.get("framework"))
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(d)
    return result

def pick_first(d, keys):
    for k in keys:
        if k in d and d[k]:
            return d[k]
    return None

# ---- Info.plist 관련: 읽기만 하고, 파일 조작은 절대 금지 ----

def find_target_infoplist_from_xcodeproj(xproj_json, target_name: str):
    """타깃의 build configurations에서 INFOPLIST_FILE을 찾아 반환. 없으면 None."""
    for t in xproj_json.get("targets", []):
        if t.get("name") != target_name:
            continue
        for cfg in t.get("configurations", []):
            bs = cfg.get("settings", {}) or {}
            v = bs.get("INFOPLIST_FILE")
            if v:
                return str(v)
    return None

def entitlements_if_exists(project_root: Path, target_name: str):
    cand = project_root / target_name / f"{target_name}.entitlements"
    return str(cand.relative_to(project_root)) if cand.exists() else None

# ---------- 리소스/소스 필터 ----------

def sanitize_resources(structure_json):
    """
    구조 스캐너가 수집한 리소스 중 다음만 유지:
      - *.xcassets (카탈로그)
      - *.lproj (로컬라이즈)
      - */Font 또는 */Fonts (대소문자 무시)
      - *.xcprivacy
      - */Lottie*/ (폴더 및 내부 .json)
      - GoogleService-Info.plist
    그 외 *.plist는 전부 제외.
    """
    keep = []
    for raw in structure_json.get("resources", []):
        path = str(raw)
        low = path.lower()
        if low.endswith(".xcassets"):
            keep.append(path)
        elif ".lproj" in path:
            keep.append(path)
        elif low.endswith(".xcprivacy"):
            keep.append(path)
        elif "lottie" in low:  # Lottie 폴더 및 내부 json
            keep.append(path)
        elif path.endswith("GoogleService-Info.plist"):
            keep.append(path)
        # Font/Fonts 폴더
        elif Path(path).name.lower() in ("font", "fonts"):
            keep.append(path)
        # 나머지 *.plist 는 버림(Info.plist 포함)
    return keep

def default_source_excludes():
    # 샘플 yml들의 공통 감각을 따르는 범용 exclude
    return [
        "**/*.plist",
        "**/*.xcassets",
        "**/*.lproj",
    ]

# ---------- packages ----------

def build_packages(xproj_json, structure_json):
    packages = {}

    # pbxproj에서 읽어온 원격 패키지 (url/branch/version)
    for pkg in xproj_json.get("packages", []):
        name = pkg.get("name")
        if not name:
            continue
        entry = {}
        if pkg.get("repositoryURL"):
            entry["url"] = pkg["repositoryURL"]
        if pkg.get("version"):
            entry["version"] = pkg["version"]
        if pkg.get("branch"):
            entry["branch"] = pkg["branch"]
        packages[name] = entry

    # 로컬 패키지 (프로젝트 루트 직속 ./Foo with Package.swift)
    for local in structure_json.get("local_packages", []):
        name = Path(local).name
        packages[name] = {"path": local}

    # 관례적으로 자주 쓰는 로컬 패키지 보강(없으면 무시됨)
    packages.setdefault("StringSecurity", {"path": "./StringSecurity"})
    return packages

# ---------- targets ----------

def build_targets(project_name, xproj_json, structure_json):
    targets = {}
    frameworks = structure_json.get("frameworks", [])
    resources_all = sanitize_resources(structure_json)
    sources_all = structure_json.get("sources", [])

    # 프로젝트 루트 (실제 파일 존재 확인용)
    # parser_structure 저장 포맷상 project_name은 이름이므로 상위 폴더를 직접 계산
    project_root = Path(structure_json.get("project_name") or project_name).resolve()
    if project_root.is_file() or project_root.suffix == ".xcodeproj":
        project_root = Path(structure_json.get("project_name", project_name)).parent

    for t in xproj_json.get("targets", []):
        name = t.get("name", "UnknownTarget")

        t_type = "bundle.ui-testing" if is_test_target(name) else "application"

        # 소스 패스: 보통 타깃명 폴더가 있으면 그걸, 없으면 루트
        default_source_path = name if any(str(s).startswith(name) for s in sources_all) else "."
        src_entry = {"path": default_source_path, "excludes": default_source_excludes()}

        # 리소스: 타깃명 포함된 경로 우선, 없으면 공통
        res_filtered = [r for r in resources_all if f"/{name}/" in ("/" + r + "/")]
        if not res_filtered:
            res_filtered = resources_all[:]
        res_entry = [{"path": r} for r in res_filtered]

        # 패키지/프레임워크 의존성
        deps = []
        # 로컬/원격 Swift Packages (타깃이 실제로 참조한 product들)
        for dep in t.get("packageProductDependencies", []):
            pkg = dep.get("package")
            prod = dep.get("productName")
            if pkg and prod:
                deps.append({"package": pkg, "product": prod})
        # 일반적으로 쓰는 로컬 패키지 보강(중복 방지)
        deps.append({"package": "StringSecurity", "product": "StringSecurity"})
        # xcframework 자동 embed
        for fw in frameworks:
            deps.append({"framework": fw, "embed": True, "codeSign": True})
        deps = ensure_unique_deps(deps)

        # 설정
        base = {
            "TARGETED_DEVICE_FAMILY": '"1,2"',
            "ASSETCATALOG_COMPILER_APPICON_NAME": "AppIcon",
            "FRAMEWORK_SEARCH_PATHS": ['"$(SRCROOT)/Frameworks"'],
        }

        # Info.plist: 있으면 그대로, 없으면 생성 모드
        infoplist = find_target_infoplist_from_xcodeproj(xproj_json, name)
        if infoplist:
            base["INFOPLIST_FILE"] = infoplist
        else:
            # 절대 파일을 만들지 않고 XcodeGen 생성 기능만 사용
            base["GENERATE_INFOPLIST_FILE"] = True
            base["INFOPLIST_KEY_CFBundleName"] = name
            base["INFOPLIST_KEY_CFBundleDisplayName"] = name
            base["INFOPLIST_KEY_CFBundleShortVersionString"] = "1.0"
            base["INFOPLIST_KEY_CFBundleVersion"] = "1"
            base["INFOPLIST_KEY_UILaunchScreen_Generation"] = True
            base["INFOPLIST_KEY_UIApplicationSceneManifest_Generation"] = True
            base["INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone"] = "UIInterfaceOrientationPortrait"
            base["INFOPLIST_KEY_UISupportedInterfaceOrientations_iPad"] = "UIInterfaceOrientationPortrait"
            base["INFOPLIST_KEY_UIUserInterfaceStyle"] = "Light"

        # Entitlements: 있을 때만
        ent = entitlements_if_exists(project_root, name)
        if ent and not is_test_target(name):
            base["CODE_SIGN_ENTITLEMENTS"] = ent

        targets[name] = {
            "type": t_type,
            "platform": "iOS",
            "sources": [src_entry],
            "resources": res_entry,
            "dependencies": deps,
            "settings": {"base": base},
        }

    return targets

# ---------- schemes ----------

def build_schemes(xscheme_json, xproj_json, project_name, targets):
    schemes = (xscheme_json.get("schemes") or
               xscheme_json.get("scheme_info", {}).get("schemes") or
               {})
    if not schemes:
        default = next((k for k in targets.keys() if not is_test_target(k)), None) or project_name
        schemes = {
            project_name: {
                "build": {"targets": {default: "all"}},
                "run": {"config": "Debug"},
                "archive": {"config": "Release"},
                "profile": {"config": "Release"},
                "analyze": {"config": "Debug"},
            }
        }
        print(f"🧩 스킴 자동 생성: {project_name}")

    # CarPlay-only 방지: 메인앱을 빌드 타깃에 추가
    for s_name, s in list(schemes.items()):
        build_tgts = s.get("build", {}).get("targets", {})
        only_carplay = build_tgts and all("carplay" in (k or "").lower() for k in build_tgts.keys())
        main_app = next((k for k in targets if not is_test_target(k) and "carplay" not in k.lower()), None)
        if only_carplay and main_app:
            build_tgts[main_app] = "all"

    return schemes

# ---------- main ----------

def main():
    if len(sys.argv) < 6:
        print("❌ Usage: python3 build_project_yml.py <project_name> <structure.json> <xcodeproj.json> <xcscheme.json> <output_dir>")
        sys.exit(1)

    project_name, structure_path, xcodeproj_path, xcscheme_path, output_dir = sys.argv[1:6]

    structure = load_json(structure_path)
    xproj = load_json(xcodeproj_path)
    xscheme = load_json(xcscheme_path)

    ios_target = infer_ios_version(xproj)
    bundle_prefix = infer_bundle_prefix(xproj, project_name)

    data = {
        "name": project_name,
        "options": {
            "bundleIdPrefix": bundle_prefix,
            "deploymentTarget": {"iOS": ios_target},
            "createIntermediateGroups": True,
        },
        "configs": {"Debug": "debug", "Release": "release"},
        "settings": {
            "base": {
                "SWIFT_VERSION": "5.0",
                "IPHONEOS_DEPLOYMENT_TARGET": ios_target,
                "ENABLE_BITCODE": False,
                "CODE_SIGN_STYLE": "Automatic",
                "LD_RUNPATH_SEARCH_PATHS": '"$(inherited) @executable_path/Frameworks"',
            }
        },
        "packages": build_packages(xproj, structure),
        "targets": {},
        "schemes": {},
    }

    data["targets"] = build_targets(project_name, xproj, structure)
    data["schemes"] = build_schemes(xscheme, xproj, project_name, data["targets"])

    out_dir = Path(output_dir)
    out_path = out_dir / f"{project_name}_project.yml"
    write_yaml(data, out_path)

if __name__ == "__main__":
    main()
