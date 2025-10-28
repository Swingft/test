#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
utils.py
- 공통 유틸리티 함수들을 담당하는 모듈
- 로깅, 파일 I/O, 프로젝트 복사 등의 기본 기능들을 포함
"""
from __future__ import annotations
import json
import os
import shutil
import sys
from typing import List

# ---------- 전역 설정 ----------
APP_TAG = "[dyn_obf]"
DEFAULT_SKIP_DIRS = {".git", ".build", "DerivedData", "Pods", "Carthage", ".swiftpm", "__MACOSX", "node_modules", "vendor"}

# ---------- 로깅 유틸리티 ----------
def log(msg: str) -> None: 
    print(f"{APP_TAG} {msg}")

def fail(msg: str, code: int = 1) -> None: 
    print(f"{APP_TAG} ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

# ---------- 파일 I/O 유틸리티 ----------
def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f: 
        return f.read()

def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: 
        f.write(text)

def dump_json(path: str, data) -> None: 
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))

def dump_text(path: str, lines: List[str]) -> None: 
    write_text(path, "\n".join(lines) + ("\n" if lines else ""))

# ---------- 프로젝트 관리 유틸리티 ----------
def copy_project_tree(src: str, dst: str, overwrite: bool = False) -> None:
    """
    프로젝트 트리를 복사하는 함수
    
    Args:
        src: 소스 프로젝트 루트 경로
        dst: 대상 프로젝트 루트 경로
        overwrite: 기존 대상이 있을 때 덮어쓸지 여부
    """
    abs_src, abs_dst = os.path.abspath(src), os.path.abspath(dst)
    if not os.path.isdir(abs_src): 
        fail(f"source is not a directory: {abs_src}")
    if abs_src == abs_dst: 
        fail("src and dst must be different paths")
    if os.path.exists(abs_dst):
        if overwrite:
            log(f"removing existing dst: {abs_dst}")
            shutil.rmtree(abs_dst)
        else:
            fail(f"dst already exists: {abs_dst} (pass --overwrite to replace)")
    
    def ignore_filter(d, names):
        ignored = [name for name in names if name in DEFAULT_SKIP_DIRS]
        # ✅ .swiftpm 은 복사되도록 예외 처리
        if ".swiftpm" in ignored:
            ignored.remove(".swiftpm")
        return ignored
    
    shutil.copytree(abs_src, abs_dst, ignore=ignore_filter)
    log(f"cloning project → {abs_dst}")

