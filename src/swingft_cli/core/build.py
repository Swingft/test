"""빌드 스크립트 실행 및 모니터링 모듈"""
import os
import sys
import subprocess
import time
import threading
import queue
from collections import deque
from .tui import get_tui, _maybe_raise, _trace

# TUI 인스턴스 가져오기
tui = get_tui()

# find_project 모듈 캐시
_find_project_available = False
_find_xcode_project_func = None


def _init_find_project():
    """find_project 모듈 동적 로드"""
    global _find_project_available, _find_xcode_project_func
    if _find_project_available:
        return _find_xcode_project_func
    
    try:
        pipeline_dir = os.path.join(os.getcwd(), "Obfuscation_Pipeline")
        find_project_path = os.path.join(pipeline_dir, "find_project.py")
        if os.path.exists(find_project_path):
            # sys.path에 추가하지 않고 직접 import
            import importlib.util
            spec = importlib.util.spec_from_file_location("find_project", find_project_path)
            if spec and spec.loader:
                find_project_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(find_project_module)
                _find_xcode_project_func = find_project_module.find_xcode_project
                _find_project_available = True
                return _find_xcode_project_func
    except Exception as e:
        _trace("find_project 모듈 로드 실패: %s", e)
    
    _find_project_available = True  # 한 번만 시도
    return None


def _monitor_build_progress(proc: subprocess.Popen, log_file, obf_project_dir: str) -> int:
    """빌드 진행률 모니터링 및 로그 파일 저장"""
    spinner = ["|", "/", "-", "\\"]
    sp_idx = 0
    current_status = "Preparing build"
    tail_lines = deque(maxlen=5)
    
    # 빌드 단계 감지용 키워드
    build_stages = {
        "main.py": "Generating project.yml",
        "xcodegen": "Regenerating project",
        "xcodebuild": "Building app",
        "build": "Building",
        "compile": "Compiling",
        "linking": "Linking",
        "succeeded": "Build completed",
        "failed": "Build failed"
    }
    
    # queue reader
    q: "queue.Queue[str|None]" = queue.Queue()
    def _reader():
        try:
            for raw in proc.stdout:  # type: ignore[arg-type]
                line = (raw or "").rstrip("\n")
                q.put(line)
        finally:
            try:
                q.put(None)
            except queue.Full as e:
                _trace("queue sentinel put failed: %s", e)
                _maybe_raise(e)
    
    thr = threading.Thread(target=_reader, daemon=True)
    thr.start()
    
    eof = False
    while True:
        # 프로세스가 종료되었는지 확인
        proc_return_code = proc.poll()
        
        try:
            item = q.get(timeout=0.1)
        except queue.Empty:
            item = ""
        
        if item is None:
            eof = True
        elif isinstance(item, str) and item:
            # 로그 파일에 저장
            try:
                log_file.write(item + "\n")
                log_file.flush()
            except (OSError, UnicodeEncodeError) as e:
                _trace("log file write failed: %s", e)
            
            # 상태 감지
            line_lower = item.lower()
            for keyword, status in build_stages.items():
                if keyword in line_lower:
                    current_status = status
                    break
            
            # tail lines에 추가
            if item.strip():
                tail_lines.append(item.strip())
        
        # 프로세스가 종료되었는지 확인
        if proc_return_code is not None:
            # 프로세스가 종료되었고, 큐에 남은 데이터 처리
            # 큐에 남은 데이터가 있으면 모두 처리
            remaining_data = []
            while True:
                try:
                    remaining_item = q.get_nowait()
                    if remaining_item is None:
                        break
                    if isinstance(remaining_item, str) and remaining_item:
                        remaining_data.append(remaining_item)
                        try:
                            log_file.write(remaining_item + "\n")
                            log_file.flush()
                        except (OSError, UnicodeEncodeError):
                            pass
                except queue.Empty:
                    break
            
            # 마지막 상태 업데이트
            if proc_return_code == 0:
                current_status = "Build completed"
            else:
                current_status = "Build failed"
            
            return proc_return_code
        
        # 스피너 업데이트
        sp_idx = (sp_idx + 1) % len(spinner)
        try:
            tui.set_status([
                f"Building: {spinner[sp_idx]}",
                f"Status: {current_status}",
                "",
                *list(tail_lines)
            ])
        except (OSError, UnicodeEncodeError) as e:
            _trace("set_status build update failed: %s", e)
        
        # EOF가 발생했고 큐가 비어있고 프로세스도 종료된 경우
        if eof and q.empty() and proc_return_code is not None:
            break
        
        time.sleep(0.1)
    
    # 프로세스 종료 대기
    return proc.wait()


def run_build_script_after_obfuscation(obf_project_dir: str) -> None:
    """난독화 완료 후 빌드 스크립트 자동 실행"""
    try:
        # find_project 모듈 로드
        find_xcode_project_func = _init_find_project()
        
        if find_xcode_project_func is None:
            #print("[WARN] find_project 모듈을 찾을 수 없습니다. 빌드 스크립트를 건너뜁니다.")
            return
        
        # find_project를 사용하여 xcodeproj 파일 찾기
        xcode_project_path = find_xcode_project_func(obf_project_dir)
        
        if not xcode_project_path:
            #print("[WARN] Xcode 프로젝트 파일을 찾을 수 없습니다. 빌드 스크립트를 건너뜁니다.")
            return
        
        #print(f"\n[INFO] Xcode 프로젝트 발견: {xcode_project_path}")
        
        # BuildScript 디렉토리 경로 찾기
        workspace_root = os.getcwd()
        build_script_dir = os.path.join(workspace_root, "BuildScript")
        build_script_main = os.path.join(build_script_dir, "main.py")
        
        if not os.path.exists(build_script_main):
            #print(f"[WARN] 빌드 스크립트를 찾을 수 없습니다: {build_script_main}")
            #print("[WARN] 빌드 스크립트를 건너뜁니다.")
            return
        
        # BuildScript/build.sh 실행 (내부에서 main.py도 자동 실행됨)
        build_script_sh = os.path.join(build_script_dir, "build.sh")
        
        if not os.path.exists(build_script_sh):
            #print(f"[WARN] build.sh를 찾을 수 없습니다: {build_script_sh}")
            #print("[WARN] 빌드 스크립트를 건너뜁니다.")
            return
        
        # build.sh는 실행 권한이 필요
        os.chmod(build_script_sh, 0o755)
        
        # 빌드 로그 파일 경로 생성 (난독화 대상 디렉토리의 swingft_output에 저장)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        project_name = os.path.basename(xcode_project_path).replace(".xcodeproj", "").replace(".xcworkspace", "")
        # obf_project_dir의 swingft_output 디렉토리에 build_logs 하위 디렉토리 생성
        output_dir = os.path.join(obf_project_dir, "swingft_output")
        os.makedirs(output_dir, exist_ok=True)
        log_dir = os.path.join(output_dir, "build_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, f"build_{project_name}_{timestamp}.log")
        
       # print("[INFO] 빌드 스크립트를 실행합니다...")
        #print(f"[INFO] 빌드 로그 저장 위치: {log_file_path}\n")
        
        
        # 빌드 로그 파일 열기
        log_file = None
        return_code = 1  # 기본값 (실패)
        try:
            log_file = open(log_file_path, "w", encoding="utf-8")
            log_file.write(f"Build started at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"Project: {xcode_project_path}\n")
            log_file.write("=" * 80 + "\n\n")
            log_file.flush()
        except (OSError, UnicodeError) as e:
            _trace("log file open failed: %s", e)
            log_file = None
        
        # build.sh 실행 (TEAM_ID 없이 서명 비활성화 모드로 실행)
        # build.sh 내부에서 main.py도 자동으로 실행됨
        try:
            proc = subprocess.Popen(
                ["bash", build_script_sh, xcode_project_path],
                cwd=build_script_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            if proc.stdout is None:
                raise RuntimeError("프로세스 stdout을 가져올 수 없습니다")
            
            # 빌드 진행률 모니터링
            if log_file:
                return_code = _monitor_build_progress(proc, log_file, obf_project_dir)
            else:
                return_code = proc.wait()
            
        finally:
            if log_file:
                try:
                    log_file.write("\n" + "=" * 80 + "\n")
                    log_file.write(f"Build finished at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    log_file.write(f"Exit code: {return_code}\n")
                    log_file.close()
                except (OSError, UnicodeError) as e:
                    _trace("log file close failed: %s", e)
        
        if return_code != 0:
            print(f"\n[WARN] Build script failed (exit code: {return_code})")
            print(f"[INFO] Build log: {log_file_path}")
            print("[WARN] Please build manually.")
        else:
            project_name = os.path.basename(xcode_project_path).replace(".xcodeproj", "").replace(".xcworkspace", "")
            app_path = os.path.join(os.path.dirname(xcode_project_path), "build", "Debug-iphonesimulator", f"{project_name}.app")
            print(f"\n[INFO] Build completed successfully")
            print(f"[INFO] .app file location: {app_path}")
            print(f"[INFO] Build log location: {log_file_path}")
        
    except Exception as e:
        _trace("빌드 스크립트 실행 실패: %s", e)
        print(f"[WARN] Build script execution error: {e}")
        print("[WARN] Please build manually.")

