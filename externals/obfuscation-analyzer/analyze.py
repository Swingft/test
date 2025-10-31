#!/usr/bin/env python3
"""
Swift Obfuscation Analyzer
CLI 도구 - 난독화 제외 대상 분석

사용법:
    python analyze.py <project_path> [options]
"""

import argparse
import subprocess
import sys
import logging
import os
from pathlib import Path
import json
import shutil

# 모듈 임포트
from lib.extractors.header_extractor import HeaderScanner


class ObfuscationAnalyzer:
    """난독화 분석 오케스트레이터"""

    def __init__(self, project_path: Path, output_dir: Path = None):
        self.project_path = Path(project_path)
        self.output_dir = output_dir or Path("./analysis_output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 로깅 설정
        self.logger = self._setup_logging()

        # 프로젝트 이름 자동 추출
        self.project_name = self._find_project_name()

    def _setup_logging(self) -> logging.Logger:
        """로깅 설정"""
        logger = logging.getLogger(__name__)
        return logger

    def _trace(self, msg: str, *args, **kwargs) -> None:
        """추적 로그"""
        try:
            # 로깅 레벨 10 사용 (trace level)
            self.logger.log(10, msg, *args, **kwargs)
        except (OSError, ValueError, TypeError) as e:
            # 로깅 실패 시에도 프로그램은 계속 진행
            print(f"[TRACE] {msg % args if args else msg}")

    def _maybe_raise(self, e: BaseException) -> None:
        """엄격 모드에서 예외 재발생"""
        try:
            if str(os.environ.get("SWINGFT_TUI_STRICT", "")).strip() == "1":
                raise e
        except (OSError, ValueError, TypeError) as env_error:
            # 환경변수 읽기 실패 시에는 무시하고 계속 진행
            print(f"[TRACE] 환경변수 읽기 실패: {env_error}")

    def run_header_analysis(self, real_project_name: str = None):
        """헤더 기반 제외 대상 분석"""
        #print("=" * 70)
        #print("🚀 Header-based Exclusion Analysis")
        #print("=" * 70)

        # 프로젝트 이름 사용 (사용자 지정 우선, 없으면 자동 추출)
        project_name = real_project_name or self.project_name
        #print(f"📦 Project Name: {project_name}\n")

        # Step 1: 헤더에서 식별자 추출
        external_ids = self._extract_external_identifiers(project_name)
        #print(f"✅ Step 1 Complete: {len(external_ids)} external identifiers found\n")

        # Step 2: 제외 리스트 생성
        self._generate_exclusion_list(external_ids)
        #print(f"✅ Step 2 Complete: Exclusion list generated\n")

        #print(f"🎉 Analysis Complete!")
        #print(f"📁 Results saved to: {self.output_dir.absolute()}")
        #print("=" * 70)

        return external_ids


    def _extract_external_identifiers(self, project_name: str = None) -> set:
        """Step 1: 헤더 식별자 추출"""
        #print("🔍 [Step 1/3] Extracting external identifiers...")

        all_identifiers = set()

        # 1-1. 헤더 스캔
        #print("  → Scanning Objective-C headers...")
        try:
            header_scanner = HeaderScanner(
                self.project_path,
                target_name=project_name,
            )
            header_ids = header_scanner.scan_all()
            all_identifiers.update(header_ids)
            #print(f"     Found {len(header_ids)} identifiers from headers")
        except (OSError, FileNotFoundError) as e:
            self._trace("HeaderScanner initialization failed: %s", e)
            self._maybe_raise(e)
            print(f"⚠️  경고: 헤더 스캔 실패 - {e}")
        except (RuntimeError, MemoryError, SystemError) as e:
            self._trace("Unexpected error in header scanning: %s", e)
            self._maybe_raise(e)
            print(f"❌ 오류: 헤더 스캔 중 예상치 못한 오류 - {e}")
            raise

        # 저장
        try:
            external_file = self.output_dir / "external_identifiers.txt"
            with open(external_file, 'w', encoding='utf-8') as f:
                for identifier in sorted(all_identifiers):
                    f.write(identifier + '\n')
        except (OSError, PermissionError) as e:
            self._trace("Failed to save external identifiers: %s", e)
            self._maybe_raise(e)
            print(f"⚠️  경고: 식별자 저장 실패 - {e}")
        except (RuntimeError, MemoryError, SystemError) as e:
            self._trace("Unexpected error saving identifiers: %s", e)
            self._maybe_raise(e)
            print(f"❌ 오류: 식별자 저장 중 예상치 못한 오류 - {e}")
            raise

        return all_identifiers

    def _generate_exclusion_list(self, external_ids: set):
        """Step 2: 제외 리스트 생성"""
        #print("📝 [Step 2/2] Generating exclusion list...")

        # TXT 리포트 (이름만)
        try:
            txt_path = self.output_dir / "exclusion_list.txt"
            with open(txt_path, 'w', encoding='utf-8') as f:
                for identifier in sorted(external_ids):
                    f.write(identifier + '\n')
            #print(f"  → Exclusion list saved to: {txt_path.name}")
            #print(f"  → Total {len(external_ids)} identifiers excluded")
        except (OSError, PermissionError) as e:
            self._trace("Failed to save exclusion list: %s", e)
            self._maybe_raise(e)
            print(f"⚠️  경고: 제외 리스트 저장 실패 - {e}")
        except (RuntimeError, MemoryError, SystemError) as e:
            self._trace("Unexpected error saving exclusion list: %s", e)
            self._maybe_raise(e)
            print(f"❌ 오류: 제외 리스트 저장 중 예상치 못한 오류 - {e}")
            raise

    def _find_project_name(self) -> str:
        """프로젝트 경로에서 프로젝트 이름 추출"""
        # 1. 주어진 경로가 .xcodeproj 파일이면 바로 사용
        if self.project_path.suffix == '.xcodeproj':
            return self.project_path.stem

        # 2. 주어진 경로가 .xcworkspace 파일이면 사용
        if self.project_path.suffix == '.xcworkspace':
            return self.project_path.stem

        # 3. 디렉토리라면 재귀적으로 .xcodeproj 또는 .xcworkspace 찾기
        if self.project_path.is_dir():
            # .xcodeproj 재귀 검색
            xcodeproj_files = list(self.project_path.rglob("*.xcodeproj"))
            if xcodeproj_files:
                xcodeproj_files.sort(key=lambda p: len(p.relative_to(self.project_path).parts))
                return xcodeproj_files[0].stem

            # .xcworkspace 재귀 검색
            xcworkspace_files = list(self.project_path.rglob("*.xcworkspace"))
            if xcworkspace_files:
                xcworkspace_files.sort(key=lambda p: len(p.relative_to(self.project_path).parts))
                return xcworkspace_files[0].stem

            # Package.swift 검색
            package_swift = self.project_path / "Package.swift"
            if package_swift.exists():
                try:
                    with open(package_swift, 'r', encoding='utf-8') as f:
                        content = f.read()
                        import re
                        match = re.search(r'name:\s*"([^"]+)"', content)
                        if match:
                            return match.group(1)
                except (OSError, UnicodeDecodeError) as e:
                    self._trace("Failed to read Package.swift: %s", e)
                    self._maybe_raise(e)
                    print(f"⚠️  경고: Package.swift 읽기 실패 - {e}")
                except (RuntimeError, MemoryError, SystemError) as e:
                    self._trace("Unexpected error reading Package.swift: %s", e)
                    self._maybe_raise(e)
                    print(f"❌ 오류: Package.swift 읽기 중 예상치 못한 오류 - {e}")
                return self.project_path.name

        # 찾지 못하면 디렉토리 이름 사용
        return self.project_path.name



def main():
    parser = argparse.ArgumentParser(
        description="Swift 프로젝트 헤더 기반 제외 대상 분석기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 기본 분석
  python analyze.py /path/to/MyProject.xcodeproj

  # 출력 디렉토리 지정
  python analyze.py /path/to/project -o ./results

  # 프로젝트 이름 명시 (DerivedData 검색용)
  python analyze.py /path/to/project -p "MyRealProjectName"
        """
    )

    parser.add_argument(
        "project_path",
        type=Path,
        help="Swift 프로젝트 경로 (.xcodeproj, .xcworkspace, 또는 프로젝트 루트)"
    )

    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("./analysis_output"),
        help="분석 결과 출력 디렉토리 (기본: ./analysis_output)"
    )

    parser.add_argument(
        "-p", "--project-name",
        type=str,
        help="DerivedData 검색용 프로젝트 이름 (미지정시 자동 추출)"
    )

    args = parser.parse_args()

    # 프로젝트 존재 확인
    if not args.project_path.exists():
        print(f"❌ 오류: 프로젝트를 찾을 수 없습니다: {args.project_path}")
        sys.exit(1)

    # 분석 실행
    try:
        analyzer = ObfuscationAnalyzer(
            project_path=args.project_path,
            output_dir=args.output
        )

        analyzer.run_header_analysis(real_project_name=args.project_name)
    except (OSError, PermissionError) as e:
        print(f"❌ 파일 시스템 오류: {e}")
        sys.exit(1)
    except (RuntimeError, MemoryError, SystemError) as e:
        print(f"❌ 예상치 못한 오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()