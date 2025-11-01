#!/bin/bash
set -e

# -------------------------------
# 0️⃣ Team ID 입력받기 (선택)
# -------------------------------
TEAM_ID="$2"

if [ -z "$1" ]; then
  echo "❌ 사용법: ./build.sh <프로젝트 경로> [TEAM_ID]"
  echo "예시: ./build.sh '/Users/baik/Desktop/bs test/0UIKit+SPM_2/StealPlateSwift.xcodeproj' 9A1234BXYZ"
  exit 1
fi

if [ -z "$TEAM_ID" ]; then
  echo "⚠️ Team ID 미입력 → 서명 비활성화 빌드(시뮬레이터용)"
  SIGN_OPTION="NO"
else
  echo "✅ Team ID 입력됨: $TEAM_ID"
  SIGN_OPTION="YES"
fi

# -------------------------------
# 1️⃣ 필수 툴 확인
# -------------------------------
if ! xcode-select -p &>/dev/null; then
  echo "🔧 Xcode Command Line Tools 설치 필요"
  xcode-select --install
  exit 1
fi

for tool in brew python3 xcodegen; do
  if ! command -v $tool &>/dev/null; then
    echo "📦 $tool 설치 중..."
    brew install $tool
  else
    echo "✅ $tool 확인됨."
  fi
done

# -------------------------------
# 2️⃣ main.py 실행
# -------------------------------
PROJECT_PATH="$1"
echo ""
echo "🚀 main.py 실행 중..."
python3 main.py -p "$PROJECT_PATH"

# -------------------------------
# 3️⃣ project.yml 탐색
# -------------------------------
echo ""
echo "📂 project.yml 탐색 중..."

if [[ "$PROJECT_PATH" == *".xcodeproj" ]]; then
  PROJECT_DIR=$(dirname "$PROJECT_PATH")
else
  PROJECT_DIR="$PROJECT_PATH"
fi

YML_PATH=""
if [ -f "$PROJECT_DIR/project.yml" ]; then
  YML_PATH="$PROJECT_DIR/project.yml"
elif [ -f "$PROJECT_DIR/output/project.yml" ]; then
  YML_PATH="$PROJECT_DIR/output/project.yml"
elif [ -f "$PROJECT_DIR"/*_project.yml ]; then
  YML_PATH=$(ls "$PROJECT_DIR"/*_project.yml | head -n 1)
elif [ -f "$PROJECT_DIR/output/"*_project.yml ]; then
  YML_PATH=$(ls "$PROJECT_DIR/output/"*_project.yml | head -n 1)
fi

if [ -z "$YML_PATH" ]; then
  echo "❌ project.yml 파일을 찾을 수 없습니다."
  exit 1
fi

echo "✅ project.yml 발견: $YML_PATH"

# -------------------------------
# 4️⃣ Team ID 삽입 or 서명 비활성화
# -------------------------------
if [ "$SIGN_OPTION" = "YES" ]; then
  echo "🛠️ Team ID 삽입 중..."
  awk -v teamid="$TEAM_ID" '
  BEGIN {found=0}
  {
    print $0
    if ($0 ~ /^  base:/ && found==0) {
      print "    DEVELOPMENT_TEAM: " teamid
      print "    CODE_SIGN_IDENTITY: \"Apple Development\""
      print "    CODE_SIGNING_ALLOWED: YES"
      found=1
    }
  }' "$YML_PATH" > "${YML_PATH}.tmp" && mv "${YML_PATH}.tmp" "$YML_PATH"
  echo "✅ Team ID 추가 완료."
else
  echo "🚫 Team ID 없음 → 서명 비활성화 모드"
  awk '
  BEGIN {found=0}
  {
    print $0
    if ($0 ~ /^  base:/ && found==0) {
      print "    CODE_SIGNING_ALLOWED: NO"
      print "    CODE_SIGNING_REQUIRED: NO"
      found=1
    }
  }' "$YML_PATH" > "${YML_PATH}.tmp" && mv "${YML_PATH}.tmp" "$YML_PATH"
  echo "✅ 서명 비활성화 설정 완료."
fi

# -------------------------------
# 5️⃣ XcodeGen 실행
# -------------------------------
YML_DIR=$(dirname "$YML_PATH")
cd "$YML_DIR"
echo ""
echo "🚀 XcodeGen 실행..."
xcodegen generate
cd - >/dev/null

# -------------------------------
# 6️⃣ Xcode 빌드 (시뮬레이터용)
# -------------------------------
echo ""
echo "🏗️ Xcode 빌드 시작 (시뮬레이터용)..."

XCODEPROJ_PATH=$(find "$PROJECT_DIR" -type d -name "*.xcodeproj" | head -n 1)
if [ -z "$XCODEPROJ_PATH" ]; then
  echo "❌ .xcodeproj 파일을 찾을 수 없습니다."
  exit 1
fi

SCHEME_NAME=$(basename "$XCODEPROJ_PATH" .xcodeproj)
echo "📦 Project: $XCODEPROJ_PATH"
echo "🎯 Scheme:  $SCHEME_NAME"
echo ""

cd "$PROJECT_DIR"

# 빌드 결과물을 프로젝트 디렉터리의 build 폴더에 저장
BUILD_OUTPUT_DIR="$PROJECT_DIR/build"
mkdir -p "$BUILD_OUTPUT_DIR"

# DerivedData도 프로젝트 내부로 지정 (빌드 속도 향상 및 검색 용이)
CUSTOM_DERIVED_DATA="$BUILD_OUTPUT_DIR/DerivedData"
mkdir -p "$CUSTOM_DERIVED_DATA"

# 빌드 결과 경로 설정
SYMROOT="$BUILD_OUTPUT_DIR"
BUILD_DIR="$BUILD_OUTPUT_DIR/Debug-iphonesimulator"

echo "📦 빌드 결과 저장 위치: $BUILD_DIR"

# 시뮬레이터 대상 빌드 (Team ID 없어도 OK)
xcodebuild \
  -project "$XCODEPROJ_PATH" \
  -scheme "$SCHEME_NAME" \
  -sdk iphonesimulator \
  -configuration Debug \
  -derivedDataPath "$CUSTOM_DERIVED_DATA" \
  SYMROOT="$SYMROOT" \
  CONFIGURATION_BUILD_DIR="$BUILD_DIR" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY="" \
  build

cd - >/dev/null

# -------------------------------
# 7️⃣ 결과물 표시
# -------------------------------
echo ""
echo "🔍 빌드 결과물 확인 중..."

# 지정한 빌드 디렉터리에서 바로 찾기
APP_PATH=$(find "$BUILD_DIR" -maxdepth 2 -type d -name "*.app" 2>/dev/null | head -n 1)

if [ -z "$APP_PATH" ]; then
  # DerivedData 경로에서도 확인
  APP_PATH=$(find "$CUSTOM_DERIVED_DATA" -type d -name "*.app" -path "*/Debug-iphonesimulator/*" 2>/dev/null | head -n 1)
fi

if [ -n "$APP_PATH" ]; then
  echo "✅ .app 파일 발견: $APP_PATH"
  echo "📂 Finder에서 보기..."
  open -R "$APP_PATH"
else
  echo "⚠️ .app 파일을 찾을 수 없습니다."
  echo "💡 빌드 출력 위치 확인: $BUILD_DIR"
fi

echo ""
echo "🎉 시뮬레이터 빌드 완료!"
