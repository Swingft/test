#!/bin/bash

# Swingft 프로젝트 환경 설정 스크립트
# 가상환경 생성, 의존성 설치, 가상환경 활성화

set -e  # 에러 발생 시 스크립트 종료

echo "🚀 Swingft 환경 설정을 시작합니다..."

# 현재 디렉토리 확인
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 가상환경 디렉토리명
VENV_DIR="venv"

# 기존 가상환경이 있으면 제거
if [ -d "$VENV_DIR" ]; then
    echo "📁 기존 가상환경을 제거합니다..."
    rm -rf "$VENV_DIR"
fi

# Python3 확인
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3가 설치되어 있지 않습니다. Python3를 먼저 설치해주세요."
    exit 1
fi

echo "🐍 Python3 버전: $(python3 --version)"

# 가상환경 생성
echo "📦 가상환경을 생성합니다..."
python3 -m venv "$VENV_DIR"

# 가상환경 활성화
echo "🔧 가상환경을 활성화합니다..."
source "$VENV_DIR/bin/activate"

# pip 업그레이드
echo "⬆️ pip을 업그레이드합니다..."
pip install --upgrade pip

# 메인 requirements.txt 설치
if [ -f "requirements.txt" ]; then
    echo "📋 메인 requirements.txt를 설치합니다..."
    pip install -r requirements.txt
else
    echo "⚠️ requirements.txt를 찾을 수 없습니다."
fi

# externals/obfuscation-analyzer requirements.txt 설치
if [ -f "externals/obfuscation-analyzer/requirements.txt" ]; then
    echo "📋 obfuscation-analyzer requirements.txt를 설치합니다..."
    pip install -r externals/obfuscation-analyzer/requirements.txt
else
    echo "⚠️ externals/obfuscation-analyzer/requirements.txt를 찾을 수 없습니다."
fi

# 추가 필수 패키지 설치
echo "📦 추가 필수 패키지를 설치합니다..."
pip install networkx>=2.8 pyyaml>=6.0

echo ""
echo "✅ 환경 설정이 완료되었습니다!"
echo ""
echo "🔧 가상환경을 활성화하려면 다음 명령어를 실행하세요:"
echo "   source $VENV_DIR/bin/activate"
echo ""
echo "🚀 Swingft CLI를 사용하려면:"
echo "   python3 src/swingft_cli/cli.py --help"
echo ""
echo "💡 가상환경을 비활성화하려면:"
echo "   deactivate"
