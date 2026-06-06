import subprocess
import os
import sys
import time
import signal
import threading
import logging
import re
import unicodedata
import json
from pathlib import Path
from datetime import datetime
from collections import deque

try:
    import psutil
except ImportError:
    psutil = None

try:
    import readline
except ImportError:
    readline = None

def configure_console():
    """Prefer UTF-8 output so the styled Chinese UI renders cleanly on Windows."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass

configure_console()

# ══════════════════════════════════════════════════════════════
#  ANSI COLORS & STYLES
# ══════════════════════════════════════════════════════════════

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
ITALIC  = "\033[3m"
ULINE   = "\033[4m"

# 前景
BLACK   = "\033[30m"
RED     = "\033[91m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
BLUE    = "\033[94m"
MAGENTA = "\033[95m"
CYAN    = "\033[96m"
WHITE   = "\033[97m"
GRAY    = "\033[90m"

# 背景
BG_BLACK  = "\033[40m"
BG_RED    = "\033[41m"
BG_GREEN  = "\033[42m"
BG_BLUE   = "\033[44m"
BG_CYAN   = "\033[46m"

def rgb(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"

def bg_rgb(r, g, b):
    return f"\033[48;2;{r};{g};{b}m"

def gradient_text(text, start_rgb, end_rgb):
    """平滑漸層文字"""
    sr, sg, sb = start_rgb
    er, eg, eb = end_rgb
    result = ""
    n = max(len(text) - 1, 1)
    for i, ch in enumerate(text):
        r = int(sr + (er - sr) * (i / n))
        g = int(sg + (eg - sg) * (i / n))
        b = int(sb + (eb - sb) * (i / n))
        result += f"{rgb(r,g,b)}{ch}"
    return result + RESET

# ══════════════════════════════════════════════════════════════
#  LOG LEVEL COLORS
# ══════════════════════════════════════════════════════════════

LEVEL_STYLES = {
    "INFO":    (rgb(100, 220, 255),  "ℹ"),
    "OK":      (rgb(100, 255, 160),  "✔"),
    "WARN":    (rgb(255, 220,  80),  "⚠"),
    "ERROR":   (rgb(255,  90,  90),  "✖"),
    "FATAL":   (rgb(255,  50,  50),  "☠"),
    "START":   (rgb(120, 255, 200),  "▶"),
    "STOP":    (rgb(255, 160, 100),  "■"),
    "RESTART": (rgb(100, 200, 255),  "↻"),
    "CRASH":   (rgb(255,  80, 120),  "☢"),
    "DEBUG":   (rgb(160, 160, 160),  "·"),
    "SYS":     (rgb(200, 150, 255),  "⚙"),
}

def level_tag(level):
    color, icon = LEVEL_STYLES.get(level.upper(), (GRAY, "•"))
    return f"{color}{BOLD}{icon} {level:<7}{RESET}"

# ══════════════════════════════════════════════════════════════
#  TERMINAL WIDTH & ALIGNMENT
# ══════════════════════════════════════════════════════════════

def term_width():
    try:
        return os.get_terminal_size().columns
    except:
        return 80

def divider(char="─", color=CYAN):
    w = min(term_width(), 60)
    return f"{color}{char * w}{RESET}"

def display_width(text):
    """計算字串在終端機中的實際顯示寬度（處理中文字、全形字元與 ANSI 色碼）"""
    raw_text = re.sub(r'\033\[[^m]*m', '', text)
    width = 0
    for char in raw_text:
        # F: Fullwidth, W: Wide
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width

def align_text(text, target_width):
    """用空白將字串補齊到指定顯示寬度"""
    tw = display_width(text)
    return text + " " * max(0, target_width - tw)

def center_text(text, width=None, fill=" "):
    w = width or min(term_width(), 60)
    tw = display_width(text)
    pad = max(0, (w - tw) // 2)
    return fill * pad + text

# ══════════════════════════════════════════════════════════════
#  BANNER & UI
# ══════════════════════════════════════════════════════════════

PROJECT_NAME = "Kusanagi Supervisor"
VERSION = "v2.0.0"
AUTHOR  = "Kusanagi_Akane"

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def print_banner():
    w = min(term_width(), 60)
    border = rgb(180, 100, 255)

    print()
    print(f"{border}{BOLD}╔{'═' * (w-2)}╗{RESET}")
    print(f"{border}{BOLD}║{RESET}{' ' * (w-2)}{border}{BOLD}║{RESET}")

    # 漸層標題
    title = gradient_text(f"  ✦  {PROJECT_NAME}  ✦  ", (220, 120, 255), (120, 200, 255))
    raw_title = f"  ✦  {PROJECT_NAME}  ✦  "
    tw = display_width(raw_title)
    pad_l = (w - 2 - tw) // 2
    pad_r = w - 2 - tw - pad_l
    print(f"{border}{BOLD}║{RESET}{' ' * pad_l}{BOLD}{title}{RESET}{' ' * pad_r}{border}{BOLD}║{RESET}")

    # 版本行
    ver_line = gradient_text(f"  {VERSION}  ·  Made by {AUTHOR}  ", (150, 200, 255), (200, 150, 255))
    raw_ver  = f"  {VERSION}  ·  Made by {AUTHOR}  "
    vw = display_width(raw_ver)
    pad_l2 = (w - 2 - vw) // 2
    pad_r2 = w - 2 - vw - pad_l2
    print(f"{border}{BOLD}║{RESET}{' ' * pad_l2}{ver_line}{' ' * pad_r2}{border}{BOLD}║{RESET}")

    print(f"{border}{BOLD}║{RESET}{' ' * (w-2)}{border}{BOLD}║{RESET}")
    print(f"{border}{BOLD}╚{'═' * (w-2)}╝{RESET}")
    print()

def copyright_footer():
    w = min(term_width(), 50)
    c = rgb(255, 150, 220)
    print()
    print(f"{c}{'─' * w}{RESET}")
    print(center_text(gradient_text(f"© 2026 {AUTHOR} · All rights reserved", (255,100,200),(200,150,255)), w))
    print(f"{c}{'─' * w}{RESET}")
    print()

def section_header(title, icon="◈"):
    w = min(term_width(), 60)
    col = rgb(140, 200, 255)
    print(f"\n{col}{BOLD}{icon} {title}{RESET}")
    print(f"{col}{'╌' * (display_width(title) + 4)}{RESET}")

# ══════════════════════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════════════════════

script_processes = {}     # name -> {"process": Popen, "log_fp": FileObject, "start_time": float}
script_states    = {}     # name -> {"status": str, "pid": int/None, "restart_count": int, "crash_count": int, "last_exit_code": int/None, "start_time": float/None}
restart_history = {}      # name -> deque of timestamps
log_listeners   = {}      # name -> bool
listener_threads= {}      # name -> Thread
manual_stop     = {}      # name -> bool
running         = True
is_monitoring   = False   # 控制是否在 Monitor (即時更新) 模式中
state_lock       = threading.RLock()
config_last_mtime = 0.0   # 追蹤設定檔修改時間
is_prompting    = False

RESTART_LIMIT  = 5
RESTART_WINDOW = 60       # 秒

def init_script_state(name):
    """初始化或重設腳本狀態機的狀態屬性。"""
    if name not in script_states:
        script_states[name] = {
            "status": "STOPPED",
            "pid": None,
            "restart_count": 0,
            "crash_count": 0,
            "last_exit_code": None,
            "start_time": None
        }

def get_process_stats(name):
    """讀取進程的 CPU% 與記憶體 (MB)"""
    with state_lock:
        entry = script_processes.get(name)
        if not entry:
            return 0.0, 0.0
        ps_proc = entry.get("psutil_proc")

    if psutil is None or ps_proc is None:
        return 0.0, 0.0

    try:
        mem = ps_proc.memory_info().rss / (1024 * 1024)
        cpu = ps_proc.cpu_percent(interval=None)
        return round(cpu, 1), round(mem, 1)
    except Exception:
        return 0.0, 0.0

# ══════════════════════════════════════════════════════════════
#  LOGGING SYSTEM
# ══════════════════════════════════════════════════════════════

MAX_LOG_SIZE   = 5 * 1024 * 1024   # 5 MB
LOG_KEEP       = 7                  # 保留最多 7 份輪替
LOG_BASE       = Path(__file__).parent / "logs"
LOG_BASE.mkdir(exist_ok=True)

# 建立 Python logger（Supervisor 自身的 log）
_supervisor_log_path = LOG_BASE / "supervisor" / (datetime.now().strftime("%Y-%m-%d") + ".log")
_supervisor_log_path.parent.mkdir(exist_ok=True)

_file_handler = logging.FileHandler(_supervisor_log_path, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
supervisor_logger = logging.getLogger("kusanagi-supervisor")
supervisor_logger.setLevel(logging.DEBUG)
supervisor_logger.addHandler(_file_handler)


def now_str():
    return datetime.now().strftime("%H:%M:%S")

def date_str():
    return datetime.now().strftime("%Y-%m-%d")

def safe_print(text):
    global is_prompting
    with state_lock:
        prompting = is_prompting
    if prompting and readline:
        sys.stdout.write(f"\r\033[K{text}\n")
        readline.redisplay()
        sys.stdout.flush()
    else:
        print(text)

def plog(level, msg, context_name=None):
    """Supervisor 輸出（終端 + 寫檔）"""
    tag  = level_tag(level)
    time_col = GRAY
    ts   = f"{time_col}[{now_str()}]{RESET}"
    name_part = f" {rgb(200,220,255)}{BOLD}[{context_name}]{RESET}" if context_name else ""
    
    global is_monitoring
    # 如果沒有在即時監控模式，才印出文字，避免破壞自動更新畫面
    if not is_monitoring:
        safe_print(f"{ts} {tag}{name_part}  {msg}")

    # 也寫入 supervisor log（純文字）
    raw = re.sub(r'\033\[[^m]*m', '', msg)
    lvl_map = {
        "INFO": logging.INFO, "OK": logging.INFO,
        "WARN": logging.WARNING, "ERROR": logging.ERROR,
        "FATAL": logging.CRITICAL, "START": logging.INFO,
        "STOP": logging.INFO, "RESTART": logging.INFO,
        "CRASH": logging.ERROR, "DEBUG": logging.DEBUG,
        "SYS": logging.INFO
    }
    supervisor_logger.log(lvl_map.get(level, logging.INFO),
                          f"[{context_name or 'SUPERVISOR'}] {raw}")


def get_log_path(name):
    folder = LOG_BASE / name
    folder.mkdir(exist_ok=True)
    return folder / (datetime.now().strftime("%Y-%m-%d") + ".log")


def rotate_logs(name):
    """超過 MAX_LOG_SIZE 時輪替"""
    p = get_log_path(name)
    if not p.exists() or p.stat().st_size < MAX_LOG_SIZE:
        return
    for i in range(LOG_KEEP - 1, 0, -1):
        old = p.with_suffix(f".log.{i}")
        new = p.with_suffix(f".log.{i+1}")
        if old.exists():
            old.rename(new)
    p.rename(p.with_suffix(".log.1"))
    p.touch()
    plog("SYS", f"{name} log 已輪替", name)


def tail_log(name, lines=50):
    p = get_log_path(name)
    if not p.exists():
        return ["(尚無 log 紀錄)\n"]
    
    try:
        # 使用二進位倒序 seek 讀取法，即使檔案超大也不會撐爆記憶體
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            
            buffer = bytearray()
            block_size = 4096
            lines_found = 0
            pos = file_size
            
            while pos > 0 and lines_found <= lines:
                read_size = min(block_size, pos)
                pos -= read_size
                f.seek(pos, os.SEEK_SET)
                chunk = f.read(read_size)
                buffer[:0] = chunk
                lines_found = buffer.count(b'\n')
                
            decoded = buffer.decode("utf-8", errors="ignore")
            all_lines = decoded.splitlines(keepends=True)
            return all_lines[-lines:]
    except Exception as e:
        return [f"(讀取 log 失敗: {e})\n"]


def format_log_line(line):
    """為終端輸出著色 log 行"""
    line = line.rstrip()
    low = line.lower()
    if any(k in low for k in ["error", "exception", "traceback", "failed"]):
        return f"{rgb(255,100,100)}{line}{RESET}"
    elif any(k in low for k in ["warn", "warning"]):
        return f"{rgb(255,210,80)}{line}{RESET}"
    elif any(k in low for k in ["info", "start", "ready", "connect"]):
        return f"{rgb(150,230,255)}{line}{RESET}"
    elif any(k in low for k in ["debug"]):
        return f"{GRAY}{DIM}{line}{RESET}"
    else:
        return f"{rgb(210,210,210)}{line}{RESET}"

# ══════════════════════════════════════════════════════════════
#  SCRIPT CONFIG
# ══════════════════════════════════════════════════════════════

CONFIG_PATH = Path(__file__).parent / "supervisor_config.json"
SCRIPT_CONFIGS = {}
DEFAULT_SCRIPT_CONFIG = {
    "path": "",
    "file": "main.py",
    "enabled": True,
    "auto_restart": True,
    "args": [],
    "env": {},
}

TRUE_VALUES = {"1", "true", "yes", "y", "on", "是", "啟用"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "否", "停用"}

def resolve_path(p):
    path = Path(p)
    if path.is_absolute():
        return path
    return Path(__file__).parent / path

def coerce_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUE_VALUES:
            return True
        if normalized in FALSE_VALUES:
            return False
    return default

def normalize_script_config(name, conf):
    if not isinstance(conf, dict):
        plog("WARN", f"{name} 設定不是 JSON 物件，已套用預設值", name)
        conf = {}

    normalized = DEFAULT_SCRIPT_CONFIG.copy()
    normalized["path"] = str(conf.get("path", normalized["path"])).strip()
    normalized["file"] = str(conf.get("file", normalized["file"])).strip() or DEFAULT_SCRIPT_CONFIG["file"]
    normalized["enabled"] = coerce_bool(conf.get("enabled", normalized["enabled"]), normalized["enabled"])
    normalized["auto_restart"] = coerce_bool(
        conf.get("auto_restart", normalized["auto_restart"]),
        normalized["auto_restart"],
    )

    args = conf.get("args", normalized["args"])
    if isinstance(args, str):
        normalized["args"] = args.split()
    elif isinstance(args, (list, tuple)):
        normalized["args"] = [str(arg) for arg in args]
    else:
        plog("WARN", f"{name} 的 args 格式無效，已改為空列表", name)
        normalized["args"] = []

    env = conf.get("env", normalized["env"])
    if isinstance(env, dict):
        normalized["env"] = {str(k): str(v) for k, v in env.items()}
    else:
        plog("WARN", f"{name} 的 env 格式無效，已改為空物件", name)
        normalized["env"] = {}

    return normalized

def normalize_configs(data):
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("設定檔根節點必須是 JSON 物件")

    normalized = {}
    for raw_name, raw_conf in data.items():
        name = str(raw_name).strip()
        if not name:
            plog("WARN", "略過名稱為空的腳本設定")
            continue
        normalized[name] = normalize_script_config(name, raw_conf)
    return normalized

def write_json_atomic(path, data):
    path.parent.mkdir(exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

def load_configs():
    global SCRIPT_CONFIGS
    if not CONFIG_PATH.exists():
        try:
            write_json_atomic(CONFIG_PATH, {})
        except Exception as e:
            plog("ERROR", f"無法初始化設定檔 {CONFIG_PATH}：{e}")
    
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = normalize_configs(data)
        with state_lock:
            SCRIPT_CONFIGS = data
            for name in SCRIPT_CONFIGS:
                init_script_state(name)
        return True
    except Exception as e:
        plog("ERROR", f"讀取設定檔失敗：{e}")
        with state_lock:
            if not globals().get("SCRIPT_CONFIGS"):
                SCRIPT_CONFIGS = {}
        return False

def save_configs():
    global SCRIPT_CONFIGS
    try:
        with state_lock:
            data = normalize_configs(SCRIPT_CONFIGS)
        write_json_atomic(CONFIG_PATH, data)
        with state_lock:
            SCRIPT_CONFIGS = data
        return True
    except Exception as e:
        plog("ERROR", f"儲存設定檔失敗：{e}")
        return False

def interactive_add():
    print(f"\n{rgb(140, 200, 255)}{BOLD}✦ 新增腳本設定 ✦{RESET}")
    try:
        name = input("輸入腳本設定名稱: ").strip()
        if not name:
            print("名稱不可為空！")
            return
        with state_lock:
            exists = name in SCRIPT_CONFIGS
        if exists:
            print("此名稱已存在！")
            return
        
        path = input("輸入腳本工作目錄 (可為相對或絕對路徑): ").strip()
        if not path:
            print("路徑不可為空！")
            return
        
        filename = input("輸入執行檔案名稱 (預設: main.py): ").strip() or "main.py"
        
        enabled_input = input("是否預設啟用？ (y/n, 預設: y): ").strip().lower()
        enabled = enabled_input != 'n'
        
        autorestart_input = input("當機是否自動重啟？ (y/n, 預設: y): ").strip().lower()
        auto_restart = autorestart_input != 'n'
        
        args_input = input("自訂執行參數 (選填，空格分隔): ").strip()
        args = args_input.split() if args_input else []
        
        env_input = input("自訂環境變數 (選填，格式: KEY1=VAL1,KEY2=VAL2): ").strip()
        env = {}
        if env_input:
            for pair in env_input.split(','):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    env[k.strip()] = v.strip()
        
        with state_lock:
            SCRIPT_CONFIGS[name] = {
                "path": path,
                "file": filename,
                "enabled": enabled,
                "auto_restart": auto_restart,
                "args": args,
                "env": env
            }
            init_script_state(name)
        save_configs()
        plog("OK", f"成功新增腳本設定：{name}")
    except (KeyboardInterrupt, EOFError):
        print("\n已取消新增。")

def interactive_edit(name):
    with state_lock:
        exists = name in SCRIPT_CONFIGS
    if not exists:
        plog("ERROR", f"找不到腳本設定：{name}")
        return
    
    print(f"\n{rgb(140, 200, 255)}{BOLD}✦ 編輯腳本設定：{name} ✦{RESET}")
    print("直接按下 Enter 代表保留原設定。")
    
    with state_lock:
        conf = SCRIPT_CONFIGS[name].copy()
        
    try:
        new_path = input(f"目錄路徑 ({conf['path']}): ").strip() or conf['path']
        new_file = input(f"執行檔案 ({conf['file']}): ").strip() or conf['file']
        
        enabled_str = "y" if conf['enabled'] else "n"
        new_enabled_input = input(f"是否啟用？ (y/n, 目前: {enabled_str}): ").strip().lower()
        new_enabled = conf['enabled'] if not new_enabled_input else (new_enabled_input != 'n')
        
        autorestart_str = "y" if conf['auto_restart'] else "n"
        new_autorestart_input = input(f"是否自動重啟？ (y/n, 目前: {autorestart_str}): ").strip().lower()
        new_autorestart = conf['auto_restart'] if not new_autorestart_input else (new_autorestart_input != 'n')
        
        args_str = " ".join(conf['args'])
        new_args_input = input(f"自訂參數 ({args_str}): ").strip()
        new_args = conf['args'] if not new_args_input else new_args_input.split()
        
        env_str = ",".join(f"{k}={v}" for k, v in conf['env'].items())
        new_env_input = input(f"自訂環境變數 ({env_str}): ").strip()
        new_env = conf['env']
        if new_env_input:
            new_env = {}
            for pair in new_env_input.split(','):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    new_env[k.strip()] = v.strip()
        
        with state_lock:
            SCRIPT_CONFIGS[name] = {
                "path": new_path,
                "file": new_file,
                "enabled": new_enabled,
                "auto_restart": new_autorestart,
                "args": new_args,
                "env": new_env
            }
            init_script_state(name)
        save_configs()
        plog("OK", f"成功更新腳本設定：{name}")
        plog("INFO", f"提示：新參數將在下一次啟動/重啟 {name} 時生效")
    except (KeyboardInterrupt, EOFError):
        print("\n已取消編輯。")

# ══════════════════════════════════════════════════════════════
#  LIVE LOG LISTENER
# ══════════════════════════════════════════════════════════════

def listen_log_thread(name):
    current_date = date_str()
    plog("INFO", f"開始監聽 {BOLD}{name}{RESET} 的 log（輸入 {CYAN}listen {name} off{RESET} 停止）", name)

    path = get_log_path(name)
    last_size = 0
    last_file_id = 0
    if path.exists():
        try:
            stat_result = path.stat()
            last_size = stat_result.st_size
            last_file_id = stat_result.st_ino if os.name != "nt" else stat_result.st_ctime
            # 先印出最後 10 行作為 context
            lines = tail_log(name, 10)
            if lines and not is_monitoring:
                for ln in lines:
                    if ln.strip() != "(尚無 log 紀錄)":
                        print(f"  {GRAY}│{RESET} {format_log_line(ln)}")
        except Exception as e:
            plog("ERROR", f"初始化監聽失敗：{e}", name)

    sleep_time = 0.5
    while True:
        with state_lock:
            is_active = listener_threads.get(name) == threading.current_thread()
            should_run = running and log_listeners.get(name, False) and is_active
        if not should_run:
            break

        path = get_log_path(name)
        today_date = date_str()

        had_data = False
        try:
            if path.exists():
                stat_result = path.stat()
                size = stat_result.st_size
                file_id = stat_result.st_ino if os.name != "nt" else stat_result.st_ctime

                # 當換日時，或者檔案被重新建立/輪替時，重置讀取指標
                if today_date != current_date or file_id != last_file_id or size < last_size:
                    last_size = 0
                    current_date = today_date
                    last_file_id = file_id

                if size > last_size:
                    with open(path, "rb") as f:
                        f.seek(last_size)
                        chunk = f.read()
                    if chunk:
                        had_data = True
                        new_content = chunk.decode("utf-8", errors="ignore")
                        # 只有不在監控模式時才印出
                        if not is_monitoring and new_content.strip():
                            for ln in new_content.splitlines():
                                safe_print(f"  {GRAY}│{RESET} {format_log_line(ln)}")
                        last_size += len(chunk)
                    last_file_id = file_id
            else:
                last_size = 0
                last_file_id = 0
        except Exception:
            pass
            
        if had_data:
            sleep_time = 0.01
        else:
            sleep_time = min(0.5, sleep_time + 0.1)
            
        time.sleep(sleep_time)

    plog("STOP", f"已停止監聽 {name}", name)
    with state_lock:
        listener_threads.pop(name, None)

# ══════════════════════════════════════════════════════════════
#  RESTART LIMIT
# ══════════════════════════════════════════════════════════════

def is_restart_limited(name):
    now  = time.time()
    with state_lock:
        hist = restart_history.setdefault(name, deque())
        # 清除過期記錄
        while hist and now - hist[0] > RESTART_WINDOW:
            hist.popleft()

        limited = len(hist) >= RESTART_LIMIT
        if not limited:
            hist.append(now)

    if limited:
        plog("WARN", f"{name} 在 {RESTART_WINDOW}s 內已重啟 {RESTART_LIMIT} 次，暫停自動重啟", name)
        return True

    return False

def kill_process_tree(proc):
    """嘗試安全結束進程與其衍生之所有子進程 (Windows/Unix)"""
    pid = proc.pid
    try:
        if os.name == "nt":
            # Windows: 傳送 CTRL_BREAK_EVENT 到進程組
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:
                pass
            # 輔以 taskkill /T (優雅關閉) 保證樹狀清理
            subprocess.run(["taskkill", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Unix: 向整個進程組傳送 SIGTERM
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                pass
    except Exception:
        pass

def force_kill_process_tree(proc):
    """強行終止進程與其衍生之所有子進程"""
    pid = proc.pid
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
#  SCRIPT CONTROL
# ══════════════════════════════════════════════════════════════

def start_script(name):
    with state_lock:
        manual_stop[name] = False
        conf = SCRIPT_CONFIGS.get(name)
        if not conf:
            plog("ERROR", f"找不到腳本設定：{name}")
            return None
        conf = conf.copy()

        if not conf.get("enabled", True):
            plog("WARN", f"{name} 已停用（enabled=False）", name)
            return None

        init_script_state(name)
        state_info = script_states[name]
        if state_info["status"] == "RUNNING":
            plog("WARN", f"{name} 已經在執行中，無法重複啟動", name)
            return None
        if state_info["status"] == "STOPPING":
            plog("WARN", f"{name} 正在停止中，請稍後再試", name)
            return None

        script_dir = resolve_path(conf["path"])
        if not script_dir.exists():
            plog("ERROR", f"目錄不存在：{script_dir}", name)
            return None
        if not script_dir.is_dir():
            plog("ERROR", f"路徑不是目錄：{script_dir}", name)
            return None

        script_file = Path(conf["file"])
        if not script_file.is_absolute():
            script_file = script_dir / script_file
        if not script_file.is_file():
            plog("ERROR", f"執行檔不存在：{script_file}", name)
            return None

    try:
        rotate_logs(name)
        log_fp = open(get_log_path(name), "a", encoding="utf-8", buffering=1)

        # 寫入啟動分隔線到 log 檔
        log_fp.write(f"\n{'='*60}\n")
        log_fp.write(f"  Script 啟動  ·  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_fp.write(f"{'='*60}\n\n")
        log_fp.flush()

        # 合併環境變數
        env = os.environ.copy()
        custom_env = conf.get("env", {})
        if custom_env:
            for k, v in custom_env.items():
                env[str(k)] = str(v)

        kwargs = dict(
            cwd=str(script_dir),
            stdout=log_fp,
            stderr=log_fp,
            env=env,
        )
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["preexec_fn"] = os.setsid

        # 執行指令
        cmd = [sys.executable, "-u", str(script_file)]
        cmd.extend(conf.get("args", []))

        proc = subprocess.Popen(cmd, **kwargs)
        with state_lock:
            # 預熱 psutil Process 物件
            ps_proc = None
            if psutil is not None:
                try:
                    ps_proc = psutil.Process(proc.pid)
                    ps_proc.cpu_percent(interval=None) # 預熱
                except Exception:
                    pass
            script_processes[name] = {
                "process":    proc,
                "log_fp":     log_fp,
                "start_time": time.time(),
                "psutil_proc": ps_proc,
            }
            state_info["status"] = "RUNNING"
            state_info["pid"] = proc.pid
            state_info["start_time"] = time.time()
            
        plog("START", f"啟動 {BOLD}{name}{RESET}  {GRAY}PID {proc.pid}{RESET}", name)
        return proc

    except Exception as e:
        plog("ERROR", f"啟動失敗：{e}", name)
        with state_lock:
            init_script_state(name)
            script_states[name]["status"] = "STOPPED"
        if 'log_fp' in locals() and not log_fp.closed:
            log_fp.close()
        return None


def stop_script(name):
    with state_lock:
        manual_stop[name] = True
        init_script_state(name)
        state_info = script_states[name]
        
        if state_info["status"] == "STOPPED":
            plog("WARN", f"{name} 並未在執行中", name)
            return False
        if state_info["status"] == "STOPPING":
            plog("WARN", f"{name} 正在停止中，請勿重複操作", name)
            return False

        entry = script_processes.get(name)
        if not entry:
            state_info["status"] = "STOPPED"
            plog("WARN", f"{name} 並未在執行中", name)
            return False

        proc = entry["process"]
        state_info["status"] = "STOPPING"
        # 保留 script_processes[name] 供停止期間的狀態追蹤與 wait 安全

    plog("STOP", f"正在停止 {BOLD}{name}{RESET}…", name)

    try:
        # 使用進程樹強殺機制避免 Windows ffmpeg 等子進程殘留
        kill_process_tree(proc)

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            plog("WARN", f"{name} 未在 5s 內結束，強制終止進程樹", name)
            force_kill_process_tree(proc)
            proc.wait()

        try:
            entry["log_fp"].close()
        except Exception:
            pass

        with state_lock:
            script_processes.pop(name, None)
            state_info["status"] = "STOPPED"
            state_info["pid"] = None
            state_info["start_time"] = None

        elapsed = time.time() - entry.get("start_time", time.time())
        uptime  = _fmt_uptime(elapsed)
        plog("OK", f"{BOLD}{name}{RESET} 已停止  {GRAY}(運行了 {uptime}){RESET}", name)
        return True

    except Exception as e:
        plog("ERROR", f"停止 {name} 失敗：{e}", name)
        with state_lock:
            if proc.poll() is None:
                state_info["status"] = "RUNNING"
            else:
                script_processes.pop(name, None)
                state_info["status"] = "STOPPED"
                state_info["pid"] = None
        return False


def restart_script(name):
    with state_lock:
        manual_stop[name] = False
    plog("RESTART", f"重啟 {BOLD}{name}{RESET}…", name)
    if is_restart_limited(name):
        return
    stop_script(name)
    time.sleep(1)
    with state_lock:
        init_script_state(name)
        script_states[name]["restart_count"] += 1
    start_script(name)


def _fmt_uptime(seconds):
    seconds = int(seconds)
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    if h:   return f"{h}h {m}m {s}s"
    if m:   return f"{m}m {s}s"
    return f"{s}s"

# ══════════════════════════════════════════════════════════════
#  STATUS DISPLAY
# ══════════════════════════════════════════════════════════════

def status():
    w = 72
    border = rgb(160, 120, 255)
    print()
    print(f"{border}{BOLD}{'═'*w}{RESET}")
    title = "  Script 運行狀態與系統資源監控  "
    print(center_text(f"{BOLD}{WHITE}{title}{RESET}", w))
    print(f"{border}{BOLD}{'─'*w}{RESET}")

    h_name = align_text("腳本名稱", 10)
    h_status = align_text("狀態", 11)
    h_pid = align_text("PID", 7)
    h_cpu = align_text("CPU", 7)
    h_mem = align_text("記憶體", 9)
    h_rc = align_text("重啟/崩潰", 10)
    h_up = align_text("運行時間", 16)
    headers = f"{BOLD}{WHITE}{h_name}{h_status}{h_pid}{h_cpu}{h_mem}{h_rc}{h_up}{RESET}"
    print(f" {headers}")
    print(f"{border}{BOLD}{'╌'*w}{RESET}")

    with state_lock:
        script_items = list(SCRIPT_CONFIGS.items())

    for name, conf in script_items:
        with state_lock:
            init_script_state(name)
            state_info = script_states[name]
            entry = script_processes.get(name)
        
        status_now = state_info["status"]
        enabled = conf.get("enabled", True)

        if not enabled:
            status_str = f"{GRAY}● 已停用{RESET}"
            pid_str    = "-"
            cpu_str    = "-"
            mem_str    = "-"
            up_str     = "-"
        elif status_now == "RUNNING":
            pid = state_info["pid"]
            elapsed = time.time() - state_info["start_time"] if state_info["start_time"] else 0
            up_str  = _fmt_uptime(elapsed)
            status_str = f"{rgb(100,255,160)}{BOLD}● 運行中{RESET}"
            pid_str    = str(pid)
            
            if psutil is not None:
                cpu, mem = get_process_stats(name)
                cpu_str = f"{cpu}%"
                mem_str = f"{mem}MB"
            else:
                cpu_str = "N/A"
                mem_str = "N/A"
        elif status_now == "STOPPING":
            status_str = f"{YELLOW}{BOLD}● 停止中{RESET}"
            pid_str    = str(state_info["pid"]) if state_info["pid"] else "-"
            cpu_str    = "-"
            mem_str    = "-"
            up_str     = "-"
        elif status_now == "CRASHED":
            status_str = f"{RED}{BOLD}● 崩潰{RESET}"
            pid_str    = "-"
            cpu_str    = "-"
            mem_str    = "-"
            up_str     = "-"
        else: # STOPPED
            status_str = f"{rgb(255,100,100)}{BOLD}● 已停止{RESET}"
            pid_str    = "-"
            cpu_str    = "-"
            mem_str    = "-"
            up_str     = "-"

        rc_str = f"{state_info['restart_count']}/{state_info['crash_count']}"
        name_col = gradient_text(name, (200, 180, 255), (160, 220, 255))
        
        name_part   = align_text(name_col, 10)
        status_part = align_text(status_str, 11)
        pid_part    = align_text(pid_str, 7)
        cpu_part    = align_text(cpu_str, 7)
        mem_part    = align_text(mem_str, 9)
        rc_part     = align_text(rc_str, 10)
        up_part     = align_text(up_str, 16)

        content = f" {name_part}{status_part}{pid_part}{cpu_part}{mem_part}{rc_part}{up_part}"
        print(content)

    print(f"{border}{BOLD}{'═'*w}{RESET}")
    print()


# ══════════════════════════════════════════════════════════════
#  HELP DISPLAY
# ══════════════════════════════════════════════════════════════

def print_help():
    section_header("可用指令", "◈")
    cmds = [
        ("start <name>",      "啟動指定腳本"),
        ("stop <name>",       "停止指定腳本（不自動重啟）"),
        ("restart <name>",    "重啟指定腳本"),
        ("startall",          "啟動全部已啟用腳本"),
        ("stopall",           "停止全部腳本"),
        ("status",            "顯示所有腳本狀態"),
        ("monitor",           "即時監控狀態 (自動更新，按 Enter 退出)"),
        ("scripts",           "列出所有腳本設定"),
        ("log <name> [N]",    "查看最後 N 行 log（預設50）"),
        ("listen <name> on",  "即時監聽 log 輸出"),
        ("listen <name> off", "停止監聽"),
        ("add",               "互動式新增腳本設定"),
        ("edit <name>",       "互動式編輯腳本設定"),
        ("remove <name>",     "刪除指定腳本設定"),
        ("enable <name>",     "啟用腳本設定"),
        ("disable <name>",    "停用腳本設定"),
        ("config",            "顯示所有腳本詳細設定"),
        ("clear",             "清空終端畫面"),
        ("exit",              "優雅關閉所有腳本並退出"),
    ]
    key_color  = rgb(120, 200, 255)
    desc_color = rgb(200, 200, 220)
    for cmd, desc in cmds:
        print(f"  {key_color}{BOLD}{cmd:<22}{RESET}  {desc_color}{desc}{RESET}")
    print()

# ══════════════════════════════════════════════════════════════
#  COMMAND HANDLER
# ══════════════════════════════════════════════════════════════

PROMPT = f"\n{rgb(200,150,255)}{BOLD}❯{RESET} "

def console_listener():
    global running, is_monitoring, is_prompting
    while True:
        try:
            with state_lock:
                is_prompting = True
            cmdline = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        finally:
            with state_lock:
                is_prompting = False
        if not cmdline:
            continue

        parts = cmdline.split()
        cmd   = parts[0].lower()

        # ── 說明 ──────────────────────────────────────
        if cmd == "help":
            print_help()

        # ── 列出 ──────────────────────────────────────
        elif cmd == "scripts":
            section_header("腳本設定列表", "◈")
            with state_lock:
                script_items = list(SCRIPT_CONFIGS.items())
            for name, conf in script_items:
                enabled = conf.get("enabled", True)
                tag = f"{rgb(100,255,150)}[啟用]{RESET}" if enabled else f"{GRAY}[停用]{RESET}"
                print(f"  {BOLD}{name:<10}{RESET} {tag}")
            print()

        # ── 狀態 ──────────────────────────────────────
        elif cmd == "status":
            status()

        # ── 即時監控 (自動更新) ────────────────────────
        elif cmd == "monitor":
            is_monitoring = True
            clear_screen()
            
            def monitor_loop():
                while is_monitoring and running:
                    print("\033[H\033[J", end="")
                    print_banner()
                    status()
                    
                    w = min(term_width(), 72)
                    msg = "● 即時監控模式運行中... (按下 Enter 退出)"
                    print(center_text(f"{rgb(100,255,160)}{BOLD}{msg}{RESET}", w))
                    print()
                    
                    time.sleep(1)
                    
            mt = threading.Thread(target=monitor_loop, daemon=True)
            mt.start()
            
            try:
                input() 
            except:
                pass
            finally:
                is_monitoring = False
                time.sleep(0.1)
                clear_screen()
                print_banner()
                status()

        # ── 清除 ──────────────────────────────────────
        elif cmd == "clear":
            clear_screen()
            print_banner()

        # ── 退出 ──────────────────────────────────────
        elif cmd == "exit":
            running = False
            print()
            plog("SYS", "收到 exit 指令，開始關閉…")
            break

        # ── 全部啟動 ──────────────────────────────────
        elif cmd == "startall":
            section_header("啟動全部腳本", "▶")
            with state_lock:
                names = list(SCRIPT_CONFIGS.keys())
            for name in names:
                start_script(name)

        # ── 全部停止 ──────────────────────────────────
        elif cmd == "stopall":
            section_header("停止全部腳本", "■")
            with state_lock:
                names = list(SCRIPT_CONFIGS.keys())
            for name in names:
                stop_script(name)

        # ── 查看 log ──────────────────────────────────
        elif cmd == "log":
            if len(parts) < 2:
                plog("WARN", "用法：log <name> [行數]")
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", f"找不到腳本設定：{script_name}")
                continue
            n = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 50

            section_header(f"{script_name} · 最後 {n} 行 log", "◈")
            lines = tail_log(script_name, n)
            for ln in lines:
                print(f"  {GRAY}│{RESET} {format_log_line(ln)}")
            print(f"  {GRAY}└{'─'*50}{RESET}\n")

        # ── 即時監聽 ──────────────────────────────────
        elif cmd == "listen":
            if len(parts) < 3:
                plog("WARN", "用法：listen <name> on/off")
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", f"找不到腳本設定：{script_name}")
                continue
            mode     = parts[2].lower()

            if mode == "on":
                with state_lock:
                    already_listening = log_listeners.get(script_name)
                if already_listening:
                    plog("WARN", f"{script_name} 已在監聽中", script_name)
                    continue
                with state_lock:
                    log_listeners[script_name] = True
                t = threading.Thread(target=listen_log_thread, args=(script_name,), daemon=True)
                with state_lock:
                    listener_threads[script_name] = t
                t.start()

            elif mode == "off":
                with state_lock:
                    log_listeners[script_name] = False

            else:
                plog("WARN", "listen 第二個參數須為 on 或 off")

        # ── 新增設定 ───────────────────────────────────
        elif cmd == "add":
            interactive_add()

        # ── 編輯設定 ───────────────────────────────────
        elif cmd == "edit":
            if len(parts) < 2:
                plog("WARN", "用法：edit <name>")
                continue
            script_name = parts[1]
            interactive_edit(script_name)

        # ── 刪除設定 ───────────────────────────────────
        elif cmd == "remove":
            if len(parts) < 2:
                plog("WARN", "用法：remove <name>")
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", f"找不到腳本設定：{script_name}")
                continue
            
            is_running = False
            with state_lock:
                entry = script_processes.get(script_name)
                if entry and entry["process"].poll() is None:
                    is_running = True
            
            if is_running:
                confirm = input(f"腳本 {script_name} 正在執行中，刪除前需要先停止它，是否繼續？(y/n): ").strip().lower()
                if confirm != 'y':
                    plog("INFO", "已取消刪除。")
                    continue
                stop_script(script_name)
            
            with state_lock:
                if script_name in SCRIPT_CONFIGS: del SCRIPT_CONFIGS[script_name]
                if script_name in script_processes: del script_processes[script_name]
                if script_name in restart_history: del restart_history[script_name]
                if script_name in log_listeners: del log_listeners[script_name]
                if script_name in listener_threads: del listener_threads[script_name]
                if script_name in manual_stop: del manual_stop[script_name]
                if script_name in script_states: del script_states[script_name]
            save_configs()
            plog("OK", f"成功刪除腳本設定：{script_name}")

        # ── 啟用/停用設定 ──────────────────────────────
        elif cmd in ("enable", "disable"):
            if len(parts) < 2:
                plog("WARN", f"用法：{cmd} <name>")
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", f"找不到腳本設定：{script_name}")
                continue
            with state_lock:
                SCRIPT_CONFIGS[script_name]["enabled"] = (cmd == "enable")
            save_configs()
            plog("OK", f"已設定 {script_name} 為 {'啟用' if cmd == 'enable' else '停用'}")

        # ── 顯示詳細設定 ──────────────────────────────
        elif cmd == "config":
            section_header("腳本詳細設定", "⚙")
            with state_lock:
                script_items = list(SCRIPT_CONFIGS.items())
            for name, conf in script_items:
                print(f"  {rgb(140, 200, 255)}{BOLD}{name}{RESET}:")
                print(f"    {GRAY}路徑:{RESET} {conf['path']}")
                print(f"    {GRAY}檔案:{RESET} {conf['file']}")
                print(f"    {GRAY}狀態:{RESET} {'啟用' if conf['enabled'] else '停用'}")
                print(f"    {GRAY}自動重啟:{RESET} {'是' if conf['auto_restart'] else '否'}")
                if conf['args']:
                    print(f"    {GRAY}參數:{RESET} {' '.join(conf['args'])}")
                if conf['env']:
                    env_str = ", ".join(f"{k}={v}" for k, v in conf['env'].items())
                    print(f"    {GRAY}環境變數:{RESET} {env_str}")
            print()

        # ── 單個操作 ───────────────────────────────────
        elif cmd in ("start", "stop", "restart"):
            if len(parts) < 2:
                plog("WARN", f"用法：{cmd} <name>")
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", f"找不到腳本設定：{script_name}")
                continue
            if cmd == "start":       start_script(script_name)
            elif cmd == "stop":      stop_script(script_name)
            else:                    restart_script(script_name)

        else:
            plog("WARN", f"未知指令：{BOLD}{cmd}{RESET}  輸入 {CYAN}help{RESET} 查看指令列表")


def graceful_shutdown():
    print()
    plog("SYS", "正在優雅關閉所有腳本…")
    with state_lock:
        names = list(SCRIPT_CONFIGS.keys())
    for name in names:
        stop_script(name)
    plog("OK", "所有腳本已安全關閉")
    copyright_footer()


def watchdog():
    """監控所有腳本崩潰並自動重啟，以及偵測設定熱更新。"""
    global running, config_last_mtime
    
    try:
        if CONFIG_PATH.exists():
            config_last_mtime = CONFIG_PATH.stat().st_mtime
    except Exception:
        pass

    while running:
        time.sleep(2)
        
        # 1. 熱重載設定檔
        try:
            if CONFIG_PATH.exists():
                mtime = CONFIG_PATH.stat().st_mtime
                if mtime != config_last_mtime:
                    config_last_mtime = mtime
                    plog("SYS", "偵測到設定檔變更，正在進行熱重載...")
                    
                    with state_lock:
                        old_scripts = set(SCRIPT_CONFIGS.keys())
                    
                    load_configs()
                    
                    with state_lock:
                        new_scripts = set(SCRIPT_CONFIGS.keys())
                        
                    removed_scripts = old_scripts - new_scripts
                    for name in removed_scripts:
                        plog("SYS", f"設定已移除腳本：{name}，正在停止進程...", name)
                        stop_script(name)
                        with state_lock:
                            if name in script_states:
                                del script_states[name]
                                
                    for name in new_scripts:
                        with state_lock:
                            conf = SCRIPT_CONFIGS.get(name)
                            enabled = conf.get("enabled", True) if conf else False
                            init_script_state(name)
                            status_now = script_states[name]["status"]
                            
                        if status_now == "RUNNING" and not enabled:
                            plog("SYS", f"腳本 {name} 已在設定檔中被停用，正在停止進程...", name)
                            stop_script(name)
                        elif status_now == "STOPPED" and enabled:
                            with state_lock:
                                is_manual = manual_stop.get(name, False)
                            if not is_manual:
                                plog("SYS", f"腳本 {name} 已在設定檔中被啟用，正在初始化啟動...", name)
                                start_script(name)
        except Exception as e:
            plog("ERROR", f"熱重載設定檔失敗：{e}")

        # 2. 崩潰偵測與重啟
        with state_lock:
            script_names = list(SCRIPT_CONFIGS.keys())
            
        for name in script_names:
            with state_lock:
                entry = script_processes.get(name)
                init_script_state(name)
                state_info = script_states[name]
                if state_info["status"] == "STOPPING":
                    continue
                
            if not entry:
                continue

            proc = entry["process"]
            if proc.poll() is None:
                continue

            exit_code = proc.returncode
            with state_lock:
                if script_processes.get(name) is not entry:
                    continue
                script_processes.pop(name, None)
                state_info["status"] = "CRASHED" if exit_code != 0 else "STOPPED"
                state_info["pid"] = None
                state_info["start_time"] = None
                state_info["last_exit_code"] = exit_code
                if exit_code != 0:
                    state_info["crash_count"] += 1

            try:
                entry["log_fp"].close()
            except Exception:
                pass

            with state_lock:
                was_manual_stop = manual_stop.get(name, False)
                if was_manual_stop:
                    script_states[name]["status"] = "STOPPED"

            if was_manual_stop:
                plog("STOP", f"{name} 已由使用者手動停止（跳過自動重啟）", name)
                continue

            plog("CRASH" if exit_code != 0 else "STOP", f"{BOLD}{name}{RESET} 已結束，退出碼 {exit_code}", name)

            with state_lock:
                conf = SCRIPT_CONFIGS.get(name)
                auto_restart = conf.get("auto_restart", True) if conf else True
                
            if auto_restart:
                if not is_restart_limited(name):
                    plog("RESTART", f"自動重啟 {BOLD}{name}{RESET}…", name)
                    time.sleep(1)
                    with state_lock:
                        script_states[name]["restart_count"] += 1
                    start_script(name)

# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def main():
    clear_screen()
    print_banner()

    # 載入設定檔
    load_configs()

    plog("SYS",  f"{PROJECT_NAME} 啟動  Python {sys.version.split()[0]}")
    plog("SYS",  f"Log 目錄：{LOG_BASE}")
    print()

    # 啟動所有啟用的腳本
    section_header("初始化腳本", "▶")
    for name in SCRIPT_CONFIGS:
        start_script(name)
    print()

    # 顯示初始狀態
    status()

    # 啟動 watchdog 執行緒
    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()

    # 啟動指令監聽執行緒
    cli = threading.Thread(target=console_listener, daemon=True)
    cli.start()
    cli.join()

    graceful_shutdown()


# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        plog("SYS", "收到 Ctrl+C / Pterodactyl STOP 訊號")
        graceful_shutdown()

