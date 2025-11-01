import subprocess
import argparse
import sys
from pathlib import Path


def run_script(script_name, args, use_swift=False):
    """각 파이썬 또는 스위프트 스크립트를 순차적으로 실행"""
    script_path = Path(__file__).parent / script_name
    if not script_path.exists():
        print(f"❌ {script_name} 파일을 찾을 수 없습니다.")
        sys.exit(1)

    cmd = (["swift"] if use_swift else ["python3"]) + [str(script_path)] + args

    print(f"\n🚀 실행 중: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"❌ {script_name} 실행 실패 (종료 코드 {result.returncode})")
        sys.exit(result.returncode)
    else:
        print(f"✅ {script_name} 실행 완료")


def main():
    parser = argparse.ArgumentParser(description="Xcode project 자동 빌드 파이프라인")
    parser.add_argument(
        "-p", "--project", required=True, help=".xcodeproj 경로를 지정하세요."
    )
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    if not project_path.exists():
        print(f"❌ 경로를 찾을 수 없습니다: {project_path}")
        sys.exit(1)

    project_name = project_path.stem.replace(".xcodeproj", "")
    output_dir = project_path.parent / "output"
    output_dir.mkdir(exist_ok=True)

    print(f"\n📁 프로젝트 이름: {project_name}")
    print(f"📂 결과 저장 경로: {output_dir.resolve()}")

    # --- Step 1. project.pbxproj 파싱
    run_script("parser_pbxproj.py", [str(project_path), str(output_dir)])

    # --- Step 2. 폴더 구조 파싱
    run_script("parser_structure.py", [str(project_path), str(output_dir)])

    # --- Step 3. 스킴 파싱
    run_script("parser_xcscheme.py", [str(project_path), str(output_dir)])

    # --- Step 5. build_project_yml.py 실행
    run_script(
        "build_project_yml.py",
        [
            project_name,
            str(output_dir / f"{project_name}_structure.json"),
            str(output_dir / f"{project_name}_xcodeproj.json"),
            str(output_dir / f"{project_name}_xcscheme.json"),
            str(output_dir),  # ✅ 출력 디렉터리 전달
        ],
    )

    # --- Step 6. complement.py 실행
    final_output_path = project_path.parent / "project.yml"

    run_script(
        "complement.py",
        [str(output_dir / f"{project_name}_project.yml"), str(final_output_path)],
    )

    print(f"\n🎉 전체 자동 빌드 파이프라인 완료!")
    print(f"📄 최종 결과: {final_output_path}")


if __name__ == "__main__":
    main()
