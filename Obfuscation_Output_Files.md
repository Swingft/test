# 난독화 출력 폴더(obf_project_dir)에 생성되는 파일 목록

## 1. 결과 파일 디렉토리 (`swingft_output/`)
모든 결과 파일들이 `{obf_project_dir}/swingft_output/` 디렉토리 아래에 생성됩니다.

### 1-1. ID 난독화 덤프 파일
- **Swingft_ID_Obfuscation_Dump.json**
  - 위치: `{obf_project_dir}/swingft_output/Swingft_ID_Obfuscation_Dump.json`
  - 설명: 식별자 난독화 결과를 저장하는 JSON 파일
  - 생성 위치: `ID_Obf/id_dump.py`

### 1-2. 빌드 로그 (선택적)
- **디렉토리**: `{obf_project_dir}/swingft_output/build_logs/`
  - 파일명: `build_{project_name}_{timestamp}.log`
  - 설명: 빌드 스크립트 실행 로그
  - 생성 위치: `src/swingft_cli/core/build.py`

### 1-3. Preflight 결과 파일 (conflict_policy: ask/force/skip 시 생성)
- **디렉토리**: `{obf_project_dir}/swingft_output/preflight/`
  - **exclude_review_{timestamp}.json**: 사용자 승인된 식별자 제외 목록
  - **exclude_pending_{timestamp}.json**: 사용자 확인 대상(PENDING) 식별자 목록
  - **payloads/**: 각 식별자별 payload 파일들
    - `{identifier}.payload.json`: 개별 식별자 payload 파일
    - **pending/**: PENDING 상태의 payload 파일들
  - 생성 위치: `src/swingft_cli/core/config/exclude_review.py`

## 2. StringSecurity 폴더 (별도 유지)
- **디렉토리**: `{obf_project_dir}/StringSecurity/`
  - 설명: 문자열 암호화 및 CFG 기능을 위한 Swift Package 모듈
  - 생성 위치: `CFG/last.py`, `String_Encryption/SwingftEncryption.py`
  - 참고: 결과 파일 디렉토리와 분리되어 루트에 존재

## 3. 난독화된 Swift 소스 파일들
- 실제 프로젝트의 Swift 소스 파일들이 난독화되어 수정됨

### 1-4. CFF Diff 파일 (제어 흐름 평탄화 결과)
- **디렉토리**: `{obf_project_dir}/swingft_output/Swingft_CFF_Dump/`
  - 파일명: `{경로}.diff` 형태로 생성
  - 설명: 제어 흐름 평탄화 적용 전후 비교 diff 파일들
  - 생성 위치: `Obfuscation_Pipeline/CFF/run_swiftCFF.py`, `Obfuscation_Pipeline/CFF/Sources/Swingft_CFF/main.swift`

## 정리되지 않고 유지되는 파일들
- `{obf_project_dir}/swingft_output/` 디렉토리 및 내부 파일들 - 최종 결과물로 유지
- `StringSecurity/` 폴더 - 빌드에 필요하므로 유지
- 난독화된 Swift 소스 파일들 - 최종 결과물

