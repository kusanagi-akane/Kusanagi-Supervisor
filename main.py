import contextlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime
from pathlib import Path

try:
    import psutil  # pyright: ignore[reportMissingModuleSource]
except ImportError:
    psutil = None

try:
    import readline
except ImportError:
    readline = None


def configure_console():
    """Configure UTF-8 console encoding for standard streams and Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(OSError, ValueError, AttributeError):
                reconfigure(encoding="utf-8", errors="replace")

    if os.name == "nt":
        with contextlib.suppress(ImportError, AttributeError, OSError):
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)


configure_console()


# ---------------------------------------------------------------------------
# Internationalization (i18n)
# ---------------------------------------------------------------------------
LOCALE_DIR   = Path(__file__).parent / "locales"
DEFAULT_LANG = "en"             # Fallback when a locale or key is missing
LOG_LANG     = "en"             # Supervisor log files always use this language
LANG_ENV_VAR = "KUSANAGI_LANG"  # Environment variable to force a UI language

# Windows reports locale names such as "Chinese (Traditional)_Taiwan"
_WINDOWS_LANG_ALIASES = {
    "chinese (traditional)": "zh_TW",
    "chinese_taiwan": "zh_TW",
    "chinese_hong kong": "zh_TW",
    "chinese": "zh",
    "english": "en",
    "japanese": "ja",
    "korean": "ko",
}

_catalogs = {}
current_lang = DEFAULT_LANG


def available_languages():
    """Return the sorted list of locale codes found in LOCALE_DIR."""
    if not LOCALE_DIR.is_dir():
        return []
    return sorted(p.stem for p in LOCALE_DIR.glob("*.json"))


def load_catalog(lang):
    """Load and cache the message catalog for a locale code."""
    if lang not in _catalogs:
        try:
            with open(LOCALE_DIR / f"{lang}.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            _catalogs[lang] = data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            _catalogs[lang] = {}
    return _catalogs[lang]


def normalize_lang_code(code):
    """Map a user or system locale string to an available locale code, or None."""
    if not code:
        return None
    raw = str(code).strip().split(".")[0].split("@")[0].replace("-", "_").lower()
    if not raw or raw in ("c", "posix"):
        return None

    for alias, target in _WINDOWS_LANG_ALIASES.items():
        if raw.startswith(alias):
            raw = target.lower()
            break

    available = available_languages()
    for lang in available:
        if lang.lower() == raw:
            return lang
    prefix = raw.split("_")[0]
    for lang in available:
        if lang.lower().split("_")[0] == prefix:
            return lang
    return None


def detect_language(argv=None):
    """Pick the UI language: --lang argument > KUSANAGI_LANG > DEFAULT_LANG (English)."""
    candidates = []
    args = list(argv or [])
    for i, arg in enumerate(args):
        if arg == "--lang" and i + 1 < len(args):
            candidates.append(args[i + 1])
        elif arg.startswith("--lang="):
            candidates.append(arg.split("=", 1)[1])
    candidates.append(os.environ.get(LANG_ENV_VAR))

    for candidate in candidates:
        lang = normalize_lang_code(candidate)
        if lang:
            return lang
    return DEFAULT_LANG


def set_language(code):
    """Switch the active UI language. Returns True on success."""
    global current_lang
    lang = normalize_lang_code(code)
    if not lang:
        return False
    load_catalog(lang)
    current_lang = lang
    return True


def language_name(lang=None):
    """Return the human-readable name of a locale."""
    lang = lang or current_lang
    meta = load_catalog(lang).get("_meta", {})
    return meta.get("name", lang) if isinstance(meta, dict) else lang


def translate(key, lang=None, **kwargs):
    """Return the message for key in lang (default: current language), formatted with kwargs."""
    text = load_catalog(lang or current_lang).get(key)
    if not isinstance(text, str):
        text = load_catalog(DEFAULT_LANG).get(key)
    if not isinstance(text, str):
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


class LocalizedText(str):
    """A translated string that remembers its key so it can be re-rendered in another language."""

    def __new__(cls, key, kwargs):
        obj = super().__new__(cls, translate(key, **kwargs))
        obj.key = key
        obj.kwargs = kwargs
        return obj

    def render(self, lang):
        return translate(self.key, lang=lang, **self.kwargs)


def t(key, **kwargs):
    """Translate a message key into the current UI language."""
    return LocalizedText(key, kwargs)


def bool_words(value):
    """Return the lowercase yes/no words defined across all locales."""
    field = "true_words" if value else "false_words"
    words = set()
    for lang in available_languages():
        meta = load_catalog(lang).get("_meta", {})
        if isinstance(meta, dict):
            words.update(str(w).strip().lower() for w in meta.get(field, []))
    return words


set_language(detect_language())

# ANSI escape codes for terminal styling
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
ITALIC  = "\033[3m"
ULINE   = "\033[4m"

BLACK   = "\033[30m"
RED     = "\033[91m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
BLUE    = "\033[94m"
MAGENTA = "\033[95m"
CYAN    = "\033[96m"
WHITE   = "\033[97m"
GRAY    = "\033[90m"

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
    """Render text with a linear RGB color gradient."""
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


def term_width():
    try:
        return os.get_terminal_size().columns
    except (OSError, ValueError):
        return 80


def divider(char="─", color=CYAN):
    w = min(term_width(), 60)
    return f"{color}{char * w}{RESET}"


def display_width(text):
    """Calculate terminal column width accounting for East Asian wide characters and ANSI codes."""
    raw_text = re.sub(r'\033\[[^m]*m', '', text)
    width = 0
    for char in raw_text:
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width


def align_text(text, target_width):
    """Pad text with trailing spaces to match the target terminal display width."""
    tw = display_width(text)
    return text + " " * max(0, target_width - tw)


def center_text(text, width=None, fill=" "):
    w = width or min(term_width(), 60)
    tw = display_width(text)
    pad = max(0, (w - tw) // 2)
    return fill * pad + text


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

    title = gradient_text(f"  ✦  {PROJECT_NAME}  ✦  ", (220, 120, 255), (120, 200, 255))
    raw_title = f"  ✦  {PROJECT_NAME}  ✦  "
    tw = display_width(raw_title)
    pad_l = (w - 2 - tw) // 2
    pad_r = w - 2 - tw - pad_l
    print(f"{border}{BOLD}║{RESET}{' ' * pad_l}{BOLD}{title}{RESET}{' ' * pad_r}{border}{BOLD}║{RESET}")

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
    col = rgb(140, 200, 255)
    print(f"\n{col}{BOLD}{icon} {title}{RESET}")
    print(f"{col}{'╌' * (display_width(title) + 4)}{RESET}")


# Global runtime state protected by state_lock
script_processes  = {}
script_states     = {}
restart_history   = {}
log_listeners     = {}
listener_threads  = {}
manual_stop       = {}
running           = True
is_monitoring     = False
state_lock        = threading.RLock()
config_last_mtime = 0.0
is_prompting      = False

RESTART_LIMIT  = 5
RESTART_WINDOW = 60


def init_script_state(name):
    """Initialize default state tracking entry for a script if not present."""
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
    """Return (cpu_percent, memory_mb) for a running script process."""
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
    except (psutil.Error, OSError, AttributeError, ValueError):
        return 0.0, 0.0


MAX_LOG_SIZE = 5 * 1024 * 1024
LOG_KEEP     = 7
LOG_BASE     = Path(__file__).parent / "logs"
LOG_BASE.mkdir(exist_ok=True)

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
    """Print a line to stdout without corrupting an active readline prompt."""
    with state_lock:
        prompting = is_prompting
    redisplay = getattr(readline, "redisplay", None) if readline else None
    if prompting and callable(redisplay):
        sys.stdout.write(f"\r\033[K{text}\n")
        redisplay()
        sys.stdout.flush()
    else:
        print(text)


def plog(level, msg, context_name=None):
    """Log a message to both the terminal (unless in monitor mode) and the supervisor log file."""
    tag  = level_tag(level)
    time_col = GRAY
    ts   = f"{time_col}[{now_str()}]{RESET}"
    name_part = f" {rgb(200,220,255)}{BOLD}[{context_name}]{RESET}" if context_name else ""

    if not is_monitoring:
        safe_print(f"{ts} {tag}{name_part}  {msg}")

    file_msg = msg.render(LOG_LANG) if isinstance(msg, LocalizedText) else msg
    raw = re.sub(r'\033\[[^m]*m', '', file_msg)
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
    """Rotate the current script log file if it exceeds MAX_LOG_SIZE."""
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
    plog("SYS", t("log.rotated", name=name), name)


def tail_log(name, lines=50):
    """Read the last N lines of a script's log file using reverse block seeks."""
    p = get_log_path(name)
    if not p.exists():
        return [translate("log.empty") + "\n"]

    try:
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
    except (OSError, ValueError) as e:
        return [translate("log.read_failed", error=e) + "\n"]


def format_log_line(line):
    """Colorize a log line based on severity keywords."""
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

TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}


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
        if normalized in TRUE_VALUES or normalized in bool_words(True):
            return True
        if normalized in FALSE_VALUES or normalized in bool_words(False):
            return False
    return default


def normalize_script_config(name, conf):
    """Validate and normalize a single script configuration dictionary."""
    if not isinstance(conf, dict):
        plog("WARN", t("config.not_object", name=name), name)
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
        plog("WARN", t("config.invalid_args", name=name), name)
        normalized["args"] = []

    env = conf.get("env", normalized["env"])
    if isinstance(env, dict):
        normalized["env"] = {str(k): str(v) for k, v in env.items()}
    else:
        plog("WARN", t("config.invalid_env", name=name), name)
        normalized["env"] = {}

    return normalized


def normalize_configs(data):
    """Normalize the full configuration mapping loaded from JSON."""
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(t("config.root_not_object"))  # noqa: TRY004

    normalized = {}
    for raw_name, raw_conf in data.items():
        name = str(raw_name).strip()
        if not name:
            plog("WARN", t("config.empty_name_skipped"))
            continue
        normalized[name] = normalize_script_config(name, raw_conf)
    return normalized


def write_json_atomic(path, data):
    """Write JSON data to a temporary file and atomically replace the target file."""
    path.parent.mkdir(exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()


def load_configs():
    global SCRIPT_CONFIGS
    if not CONFIG_PATH.exists():
        try:
            write_json_atomic(CONFIG_PATH, {})
        except OSError as e:
            plog("ERROR", t("config.init_failed", path=CONFIG_PATH, error=e))

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = normalize_configs(data)
        with state_lock:
            SCRIPT_CONFIGS = data
            for name in SCRIPT_CONFIGS:
                init_script_state(name)
        return True
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
        plog("ERROR", t("config.load_failed", error=e))
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
    except (OSError, ValueError, TypeError) as e:
        plog("ERROR", t("config.save_failed", error=e))
        return False


def interactive_add():
    print(f"\n{rgb(140, 200, 255)}{BOLD}✦ {t('add.title')} ✦{RESET}")
    try:
        name = input(t("add.prompt_name")).strip()
        if not name:
            print(t("add.name_empty"))
            return
        with state_lock:
            exists = name in SCRIPT_CONFIGS
        if exists:
            print(t("add.name_exists"))
            return

        path = input(t("add.prompt_path")).strip()
        if not path:
            print(t("add.path_empty"))
            return

        filename = input(t("add.prompt_file")).strip() or "main.py"

        enabled_input = input(t("add.prompt_enabled")).strip().lower()
        enabled = enabled_input != 'n'

        autorestart_input = input(t("add.prompt_auto_restart")).strip().lower()
        auto_restart = autorestart_input != 'n'

        args_input = input(t("add.prompt_args")).strip()
        args = args_input.split() if args_input else []

        env_input = input(t("add.prompt_env")).strip()
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
        plog("OK", t("add.success", name=name))
    except (KeyboardInterrupt, EOFError):
        print("\n" + t("add.cancelled"))


def interactive_edit(name):
    with state_lock:
        exists = name in SCRIPT_CONFIGS
    if not exists:
        plog("ERROR", t("common.profile_not_found", name=name))
        return

    print(f"\n{rgb(140, 200, 255)}{BOLD}✦ {t('edit.title', name=name)} ✦{RESET}")
    print(t("edit.keep_hint"))

    with state_lock:
        conf = SCRIPT_CONFIGS[name].copy()

    try:
        new_path = input(t("edit.prompt_path", value=conf['path'])).strip() or conf['path']
        new_file = input(t("edit.prompt_file", value=conf['file'])).strip() or conf['file']

        enabled_str = "y" if conf['enabled'] else "n"
        new_enabled_input = input(t("edit.prompt_enabled", value=enabled_str)).strip().lower()
        new_enabled = conf['enabled'] if not new_enabled_input else (new_enabled_input != 'n')

        autorestart_str = "y" if conf['auto_restart'] else "n"
        new_autorestart_input = input(t("edit.prompt_auto_restart", value=autorestart_str)).strip().lower()
        new_autorestart = conf['auto_restart'] if not new_autorestart_input else (new_autorestart_input != 'n')

        args_str = " ".join(conf['args'])
        new_args_input = input(t("edit.prompt_args", value=args_str)).strip()
        new_args = conf['args'] if not new_args_input else new_args_input.split()

        env_str = ",".join(f"{k}={v}" for k, v in conf['env'].items())
        new_env_input = input(t("edit.prompt_env", value=env_str)).strip()
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
        plog("OK", t("edit.success", name=name))
        plog("INFO", t("edit.apply_hint", name=name))
    except (KeyboardInterrupt, EOFError):
        print("\n" + t("edit.cancelled"))


def listen_log_thread(name):
    """Stream new log lines for a script to the console in real time."""
    current_date = date_str()
    plog("INFO", t("listen.started", name=f"{BOLD}{name}{RESET}", command=f"{CYAN}listen {name} off{RESET}"), name)

    path = get_log_path(name)
    last_size = 0
    last_file_id = 0
    if path.exists():
        try:
            stat_result = path.stat()
            last_size = stat_result.st_size
            last_file_id = stat_result.st_ino if os.name != "nt" else stat_result.st_ctime
            lines = tail_log(name, 10)
            if lines and not is_monitoring:
                for ln in lines:
                    if ln.strip() != translate("log.empty"):
                        print(f"  {GRAY}│{RESET} {format_log_line(ln)}")
        except OSError as e:
            plog("ERROR", t("listen.init_failed", error=e), name)

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
        with contextlib.suppress(OSError):
            if path.exists():
                stat_result = path.stat()
                size = stat_result.st_size
                file_id = stat_result.st_ino if os.name != "nt" else stat_result.st_ctime

                # Reset read offset on date rollover, log rotation, or file truncation
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
                        if not is_monitoring and new_content.strip():
                            for ln in new_content.splitlines():
                                safe_print(f"  {GRAY}│{RESET} {format_log_line(ln)}")
                        last_size += len(chunk)
                    last_file_id = file_id
            else:
                last_size = 0
                last_file_id = 0

        if had_data:
            sleep_time = 0.01
        else:
            sleep_time = min(0.5, sleep_time + 0.1)

        time.sleep(sleep_time)

    plog("STOP", t("listen.stopped", name=name), name)
    with state_lock:
        listener_threads.pop(name, None)


def is_restart_limited(name):
    """Check whether a script has exceeded RESTART_LIMIT within RESTART_WINDOW."""
    now  = time.time()
    with state_lock:
        hist = restart_history.setdefault(name, deque())
        while hist and now - hist[0] > RESTART_WINDOW:
            hist.popleft()

        limited = len(hist) >= RESTART_LIMIT
        if not limited:
            hist.append(now)

    if limited:
        plog("WARN", t("restart.limited", name=name, window=RESTART_WINDOW, limit=RESTART_LIMIT), name)
        return True

    return False


def kill_process_tree(proc):
    """Gracefully terminate a process and all of its child processes."""
    pid = proc.pid
    with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
        if os.name == "nt":
            with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            subprocess.run(
                ["taskkill", "/T", "/PID", str(pid)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            with contextlib.suppress(OSError, ProcessLookupError):
                os.killpg(os.getpgid(pid), signal.SIGTERM)


def force_kill_process_tree(proc):
    """Forcefully kill a process and all of its child processes."""
    pid = proc.pid
    with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            with contextlib.suppress(OSError, ProcessLookupError):
                os.killpg(os.getpgid(pid), signal.SIGKILL)


def start_script(name):
    """Launch a configured script in its own process group and attach log output."""
    with state_lock:
        manual_stop[name] = False
        conf = SCRIPT_CONFIGS.get(name)
        if not conf:
            plog("ERROR", t("common.profile_not_found", name=name))
            return None
        conf = conf.copy()

        if not conf.get("enabled", True):
            plog("WARN", t("start.disabled", name=name), name)
            return None

        init_script_state(name)
        state_info = script_states[name]
        if state_info["status"] == "RUNNING":
            plog("WARN", t("start.already_running", name=name), name)
            return None
        if state_info["status"] == "STOPPING":
            plog("WARN", t("start.stopping", name=name), name)
            return None

        script_dir = resolve_path(conf["path"])
        if not script_dir.exists():
            plog("ERROR", t("start.dir_missing", path=script_dir), name)
            return None
        if not script_dir.is_dir():
            plog("ERROR", t("start.not_dir", path=script_dir), name)
            return None

        script_file = Path(conf["file"])
        if not script_file.is_absolute():
            script_file = script_dir / script_file
        if not script_file.is_file():
            plog("ERROR", t("start.file_missing", path=script_file), name)
            return None

    log_fp = None
    try:
        rotate_logs(name)
        log_fp = open(get_log_path(name), "a", encoding="utf-8", buffering=1)  # noqa: SIM115

        log_fp.write(f"\n{'='*60}\n")
        log_fp.write(f"  Script started  ·  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_fp.write(f"{'='*60}\n\n")
        log_fp.flush()

        env = os.environ.copy()
        custom_env = conf.get("env", {})
        if custom_env:
            for k, v in custom_env.items():
                env[str(k)] = str(v)

        cmd = [sys.executable, "-u", str(script_file)]
        cmd.extend(conf.get("args", []))

        if os.name == "nt":
            proc = subprocess.Popen(
                cmd,
                cwd=str(script_dir),
                stdout=log_fp,
                stderr=log_fp,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            proc = subprocess.Popen(
                cmd,
                cwd=str(script_dir),
                stdout=log_fp,
                stderr=log_fp,
                env=env,
                start_new_session=True,
            )
        with state_lock:
            ps_proc = None
            if psutil is not None:
                with contextlib.suppress(psutil.Error, OSError, ValueError):
                    ps_proc = psutil.Process(proc.pid)
                    # Prime CPU percentage measurement so subsequent calls return non-zero values
                    ps_proc.cpu_percent(interval=None)
            script_processes[name] = {
                "process":    proc,
                "log_fp":     log_fp,
                "start_time": time.time(),
                "psutil_proc": ps_proc,
            }
            state_info["status"] = "RUNNING"
            state_info["pid"] = proc.pid
            state_info["start_time"] = time.time()

        plog("START", t("start.started", name=f"{BOLD}{name}{RESET}", pid=f"{GRAY}PID {proc.pid}{RESET}"), name)
        return proc

    except (OSError, ValueError, subprocess.SubprocessError) as e:
        plog("ERROR", t("start.failed", error=e), name)
        with state_lock:
            init_script_state(name)
            script_states[name]["status"] = "STOPPED"
        if log_fp is not None and not log_fp.closed:
            log_fp.close()
        return None


def stop_script(name):
    """Stop a running script, escalating to force kill if it does not exit within 5 seconds."""
    with state_lock:
        manual_stop[name] = True
        init_script_state(name)
        state_info = script_states[name]

        if state_info["status"] == "STOPPED":
            plog("WARN", t("stop.not_running", name=name), name)
            return False
        if state_info["status"] == "STOPPING":
            plog("WARN", t("stop.already_stopping", name=name), name)
            return False

        entry = script_processes.get(name)
        if not entry:
            state_info["status"] = "STOPPED"
            plog("WARN", t("stop.not_running", name=name), name)
            return False

        proc = entry["process"]
        state_info["status"] = "STOPPING"

    plog("STOP", t("stop.stopping", name=f"{BOLD}{name}{RESET}"), name)

    try:
        kill_process_tree(proc)

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            plog("WARN", t("stop.force_kill", name=name), name)
            force_kill_process_tree(proc)
            proc.wait()

        with contextlib.suppress(OSError, ValueError):
            entry["log_fp"].close()

        with state_lock:
            script_processes.pop(name, None)
            state_info["status"] = "STOPPED"
            state_info["pid"] = None
            state_info["start_time"] = None

        elapsed = time.time() - entry.get("start_time", time.time())
        uptime  = _fmt_uptime(elapsed)
        plog("OK", t("stop.stopped", name=f"{BOLD}{name}{RESET}", uptime=uptime, gray=GRAY, reset=RESET), name)
        return True

    except (OSError, ValueError, subprocess.SubprocessError) as e:
        plog("ERROR", t("stop.failed", name=name, error=e), name)
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
    plog("RESTART", t("restart.restarting", name=f"{BOLD}{name}{RESET}"), name)
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


def status():
    w = 72
    border = rgb(160, 120, 255)
    print()
    print(f"{border}{BOLD}{'═'*w}{RESET}")
    title = f"  {t('status.title')}  "
    print(center_text(f"{BOLD}{WHITE}{title}{RESET}", w))
    print(f"{border}{BOLD}{'─'*w}{RESET}")

    h_name = align_text(t("status.col_name"), 10)
    h_status = align_text(t("status.col_status"), 11)
    h_pid = align_text(t("status.col_pid"), 7)
    h_cpu = align_text(t("status.col_cpu"), 7)
    h_mem = align_text(t("status.col_mem"), 9)
    h_rc = align_text(t("status.col_restarts"), 10)
    h_up = align_text(t("status.col_uptime"), 16)
    headers = f"{BOLD}{WHITE}{h_name}{h_status}{h_pid}{h_cpu}{h_mem}{h_rc}{h_up}{RESET}"
    print(f" {headers}")
    print(f"{border}{BOLD}{'╌'*w}{RESET}")

    with state_lock:
        script_items = list(SCRIPT_CONFIGS.items())

    for name, conf in script_items:
        with state_lock:
            init_script_state(name)
            state_info = script_states[name]

        status_now = state_info["status"]
        enabled = conf.get("enabled", True)

        if not enabled:
            status_str = f"{GRAY}● {t('status.disabled')}{RESET}"
            pid_str    = "-"
            cpu_str    = "-"
            mem_str    = "-"
            up_str     = "-"
        elif status_now == "RUNNING":
            pid = state_info["pid"]
            elapsed = time.time() - state_info["start_time"] if state_info["start_time"] else 0
            up_str  = _fmt_uptime(elapsed)
            status_str = f"{rgb(100,255,160)}{BOLD}● {t('status.running')}{RESET}"
            pid_str    = str(pid)

            if psutil is not None:
                cpu, mem = get_process_stats(name)
                cpu_str = f"{cpu}%"
                mem_str = f"{mem}MB"
            else:
                cpu_str = "N/A"
                mem_str = "N/A"
        elif status_now == "STOPPING":
            status_str = f"{YELLOW}{BOLD}● {t('status.stopping')}{RESET}"
            pid_str    = str(state_info["pid"]) if state_info["pid"] else "-"
            cpu_str    = "-"
            mem_str    = "-"
            up_str     = "-"
        elif status_now == "CRASHED":
            status_str = f"{RED}{BOLD}● {t('status.crashed')}{RESET}"
            pid_str    = "-"
            cpu_str    = "-"
            mem_str    = "-"
            up_str     = "-"
        else:
            status_str = f"{rgb(255,100,100)}{BOLD}● {t('status.stopped')}{RESET}"
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


def print_help():
    section_header(t("help.title"), "◈")
    cmds = [
        ("start <name>",      t("help.start")),
        ("stop <name>",       t("help.stop")),
        ("restart <name>",    t("help.restart")),
        ("startall",          t("help.startall")),
        ("stopall",           t("help.stopall")),
        ("status",            t("help.status")),
        ("monitor",           t("help.monitor")),
        ("scripts",           t("help.scripts")),
        ("log <name> [N]",    t("help.log")),
        ("listen <name> on",  t("help.listen_on")),
        ("listen <name> off", t("help.listen_off")),
        ("add",               t("help.add")),
        ("edit <name>",       t("help.edit")),
        ("remove <name>",     t("help.remove")),
        ("enable <name>",     t("help.enable")),
        ("disable <name>",    t("help.disable")),
        ("config",            t("help.config")),
        ("lang [code]",       t("help.lang")),
        ("clear",             t("help.clear")),
        ("exit",              t("help.exit")),
    ]
    key_color  = rgb(120, 200, 255)
    desc_color = rgb(200, 200, 220)
    for cmd, desc in cmds:
        print(f"  {key_color}{BOLD}{align_text(cmd, 22)}{RESET}  {desc_color}{desc}{RESET}")
    print()


PROMPT = f"\n{rgb(200,150,255)}{BOLD}❯{RESET} "


def _monitor_loop():
    while is_monitoring and running:
        print("\033[H\033[J", end="")
        print_banner()
        status()

        w = min(term_width(), 72)
        msg = t("monitor.running")
        print(center_text(f"{rgb(100,255,160)}{BOLD}{msg}{RESET}", w))
        print()

        time.sleep(1)


def console_listener():
    """Interactive CLI loop for processing user commands."""
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

        if cmd == "help":
            print_help()

        elif cmd == "scripts":
            section_header(t("scripts.title"), "◈")
            with state_lock:
                script_items = list(SCRIPT_CONFIGS.items())
            for name, conf in script_items:
                enabled = conf.get("enabled", True)
                tag = f"{rgb(100,255,150)}[{t('common.enabled')}]{RESET}" if enabled else f"{GRAY}[{t('common.disabled')}]{RESET}"
                print(f"  {BOLD}{name:<10}{RESET} {tag}")
            print()

        elif cmd == "status":
            status()

        elif cmd == "monitor":
            is_monitoring = True
            clear_screen()

            mt = threading.Thread(target=_monitor_loop, daemon=True)
            mt.start()

            try:
                with contextlib.suppress(EOFError, KeyboardInterrupt, OSError):
                    input()
            finally:
                is_monitoring = False
                time.sleep(0.1)
                clear_screen()
                print_banner()
                status()

        elif cmd == "clear":
            clear_screen()
            print_banner()

        elif cmd == "exit":
            running = False
            print()
            plog("SYS", t("exit.received"))
            break

        elif cmd == "startall":
            section_header(t("startall.title"), "▶")
            with state_lock:
                names = list(SCRIPT_CONFIGS.keys())
            for name in names:
                start_script(name)

        elif cmd == "stopall":
            section_header(t("stopall.title"), "■")
            with state_lock:
                names = list(SCRIPT_CONFIGS.keys())
            for name in names:
                stop_script(name)

        elif cmd == "log":
            if len(parts) < 2:
                plog("WARN", t("common.usage", usage="log <name> [N]"))
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", t("common.profile_not_found", name=script_name))
                continue
            n = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 50

            section_header(t("log.title", name=script_name, n=n), "◈")
            lines = tail_log(script_name, n)
            for ln in lines:
                print(f"  {GRAY}│{RESET} {format_log_line(ln)}")
            print(f"  {GRAY}└{'─'*50}{RESET}\n")

        elif cmd == "listen":
            if len(parts) < 3:
                plog("WARN", t("common.usage", usage="listen <name> on/off"))
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", t("common.profile_not_found", name=script_name))
                continue
            mode     = parts[2].lower()

            if mode == "on":
                with state_lock:
                    already_listening = log_listeners.get(script_name)
                if already_listening:
                    plog("WARN", t("listen.already", name=script_name), script_name)
                    continue
                with state_lock:
                    log_listeners[script_name] = True
                listener = threading.Thread(target=listen_log_thread, args=(script_name,), daemon=True)
                with state_lock:
                    listener_threads[script_name] = listener
                listener.start()

            elif mode == "off":
                with state_lock:
                    log_listeners[script_name] = False

            else:
                plog("WARN", t("listen.invalid_mode"))

        elif cmd == "lang":
            available = ", ".join(available_languages())
            if len(parts) < 2:
                plog("INFO", t("lang.current", code=current_lang, name=language_name()))
                plog("INFO", t("lang.available", available=available))
            elif set_language(parts[1]):
                plog("OK", t("lang.switched", code=current_lang, name=language_name()))
            else:
                plog("WARN", t("lang.unknown", code=parts[1], available=available))

        elif cmd == "add":
            interactive_add()

        elif cmd == "edit":
            if len(parts) < 2:
                plog("WARN", t("common.usage", usage="edit <name>"))
                continue
            script_name = parts[1]
            interactive_edit(script_name)

        elif cmd == "remove":
            if len(parts) < 2:
                plog("WARN", t("common.usage", usage="remove <name>"))
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", t("common.profile_not_found", name=script_name))
                continue

            is_running = False
            with state_lock:
                entry = script_processes.get(script_name)
                if entry and entry["process"].poll() is None:
                    is_running = True

            if is_running:
                confirm = input(t("remove.confirm", name=script_name)).strip().lower()
                if confirm != 'y':
                    plog("INFO", t("remove.cancelled"))
                    continue
                stop_script(script_name)

            with state_lock:
                SCRIPT_CONFIGS.pop(script_name, None)
                script_processes.pop(script_name, None)
                restart_history.pop(script_name, None)
                log_listeners.pop(script_name, None)
                listener_threads.pop(script_name, None)
                manual_stop.pop(script_name, None)
                script_states.pop(script_name, None)
            save_configs()
            plog("OK", t("remove.success", name=script_name))

        elif cmd in ("enable", "disable"):
            if len(parts) < 2:
                plog("WARN", t("common.usage", usage=f"{cmd} <name>"))
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", t("common.profile_not_found", name=script_name))
                continue
            with state_lock:
                SCRIPT_CONFIGS[script_name]["enabled"] = (cmd == "enable")
            save_configs()
            plog("OK", t("toggle.enabled" if cmd == "enable" else "toggle.disabled", name=script_name))

        elif cmd == "config":
            section_header(t("config.title"), "⚙")
            with state_lock:
                script_items = list(SCRIPT_CONFIGS.items())
            for name, conf in script_items:
                print(f"  {rgb(140, 200, 255)}{BOLD}{name}{RESET}:")
                print(f"    {GRAY}{t('config.field_path')}:{RESET} {conf['path']}")
                print(f"    {GRAY}{t('config.field_file')}:{RESET} {conf['file']}")
                print(f"    {GRAY}{t('config.field_status')}:{RESET} {t('common.enabled') if conf['enabled'] else t('common.disabled')}")
                print(f"    {GRAY}{t('config.field_auto_restart')}:{RESET} {t('common.yes') if conf['auto_restart'] else t('common.no')}")
                if conf['args']:
                    print(f"    {GRAY}{t('config.field_args')}:{RESET} {' '.join(conf['args'])}")
                if conf['env']:
                    env_str = ", ".join(f"{k}={v}" for k, v in conf['env'].items())
                    print(f"    {GRAY}{t('config.field_env')}:{RESET} {env_str}")
            print()

        elif cmd in ("start", "stop", "restart"):
            if len(parts) < 2:
                plog("WARN", t("common.usage", usage=f"{cmd} <name>"))
                continue
            script_name = parts[1]
            with state_lock:
                exists = script_name in SCRIPT_CONFIGS
            if not exists:
                plog("ERROR", t("common.profile_not_found", name=script_name))
                continue
            if cmd == "start":       start_script(script_name)
            elif cmd == "stop":      stop_script(script_name)
            else:                    restart_script(script_name)

        else:
            plog("WARN", t("cmd.unknown", cmd=f"{BOLD}{cmd}{RESET}", help=f"{CYAN}help{RESET}"))


def graceful_shutdown():
    print()
    plog("SYS", t("shutdown.stopping_all"))
    with state_lock:
        names = list(SCRIPT_CONFIGS.keys())
    for name in names:
        stop_script(name)
    plog("OK", t("shutdown.done"))
    copyright_footer()


def watchdog():
    """Background loop for config hot-reloading and automatic crash recovery."""
    global config_last_mtime

    with contextlib.suppress(OSError):
        if CONFIG_PATH.exists():
            config_last_mtime = CONFIG_PATH.stat().st_mtime

    while running:
        time.sleep(2)

        # Hot-reload configuration file when modified on disk
        try:
            if CONFIG_PATH.exists():
                mtime = CONFIG_PATH.stat().st_mtime
                if mtime != config_last_mtime:
                    config_last_mtime = mtime
                    plog("SYS", t("watchdog.reload"))

                    with state_lock:
                        old_scripts = set(SCRIPT_CONFIGS.keys())

                    load_configs()

                    with state_lock:
                        new_scripts = set(SCRIPT_CONFIGS.keys())

                    removed_scripts = old_scripts - new_scripts
                    for name in removed_scripts:
                        plog("SYS", t("watchdog.removed", name=name), name)
                        stop_script(name)
                        with state_lock:
                            script_states.pop(name, None)

                    for name in new_scripts:
                        with state_lock:
                            conf = SCRIPT_CONFIGS.get(name)
                            enabled = conf.get("enabled", True) if conf else False
                            init_script_state(name)
                            status_now = script_states[name]["status"]

                        if status_now == "RUNNING" and not enabled:
                            plog("SYS", t("watchdog.disabled", name=name), name)
                            stop_script(name)
                        elif status_now == "STOPPED" and enabled:
                            with state_lock:
                                is_manual = manual_stop.get(name, False)
                            if not is_manual:
                                plog("SYS", t("watchdog.enabled", name=name), name)
                                start_script(name)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as e:
            plog("ERROR", t("watchdog.reload_failed", error=e))

        # Detect exited processes and auto-restart if configured
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

            with contextlib.suppress(OSError, ValueError):
                entry["log_fp"].close()

            with state_lock:
                was_manual_stop = manual_stop.get(name, False)
                if was_manual_stop:
                    script_states[name]["status"] = "STOPPED"

            if was_manual_stop:
                plog("STOP", t("watchdog.manual_stop", name=name), name)
                continue

            plog("CRASH" if exit_code != 0 else "STOP", t("watchdog.exited", name=f"{BOLD}{name}{RESET}", code=exit_code), name)

            with state_lock:
                conf = SCRIPT_CONFIGS.get(name)
                auto_restart = conf.get("auto_restart", True) if conf else True

            if auto_restart and not is_restart_limited(name):
                plog("RESTART", t("watchdog.auto_restart", name=f"{BOLD}{name}{RESET}"), name)
                time.sleep(1)
                with state_lock:
                    script_states[name]["restart_count"] += 1
                start_script(name)


def main():
    set_language(detect_language(sys.argv[1:]))
    clear_screen()
    print_banner()

    load_configs()

    plog("SYS",  t("main.started", project=PROJECT_NAME, version=sys.version.split()[0]))
    plog("SYS",  t("main.log_dir", path=LOG_BASE))
    print()

    section_header(t("main.init_title"), "▶")
    for name in SCRIPT_CONFIGS:
        start_script(name)
    print()

    status()

    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()

    cli = threading.Thread(target=console_listener, daemon=True)
    cli.start()
    cli.join()

    graceful_shutdown()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        plog("SYS", t("main.interrupted"))
        graceful_shutdown()
