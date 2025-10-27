#!/bin/bash

# Swingft 프로젝트 가상환경 설정 스크립트

echo "🐍 Swingft 가상환경 설정을 시작합니다..."

# 가상환경이 이미 존재하는지 확인
if [ -d "venv" ]; then
    echo "⚠️  기존 가상환경이 존재합니다. 삭제하시겠습니까? (y/N)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        rm -rf venv
        echo "✅ 기존 가상환경을 삭제했습니다."
    else
        echo "❌ 가상환경 설정을 취소했습니다."
        exit 1
    fi
fi

# 가상환경 생성
echo "📦 가상환경을 생성합니다..."
python3 -m venv venv

# 가상환경 활성화
echo "🔄 가상환경을 활성화합니다..."
source venv/bin/activate

# pip 업그레이드
echo "⬆️  pip을 업그레이드합니다..."
pip install --upgrade pip

# requirements.txt 설치
if [ -f "requirements.txt" ]; then
    echo "📋 requirements.txt에서 패키지를 설치합니다..."
    pip install -r requirements.txt
else
    echo "⚠️  requirements.txt 파일이 없습니다."
fi

# 개발용 패키지 설치 (선택사항)
echo "🛠️  개발용 패키지를 설치하시겠습니까? (y/N)"
read -r dev_response
if [[ "$dev_response" =~ ^[Yy]$ ]]; then
    echo "📦 개발용 패키지를 설치합니다..."
    pip install black flake8 mypy pytest ipython jupyter
fi

echo "✅ 가상환경 설정이 완료되었습니다!"
echo ""
echo "🎯 사용 방법:"
echo "   source venv/bin/activate  # 가상환경 활성화"
echo "   deactivate               # 가상환경 비활성화"
echo ""
echo "🚀 Swingft CLI 실행:"
echo "   PYTHONPATH=/Users/lanian/Desktop/test python3 -m src.swingft_cli.cli --help"