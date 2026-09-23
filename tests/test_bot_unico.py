"""Un solo bot (TG_BOT_TOKEN por defecto) y enmascarado de errores en monitor.py (sin red)."""
import os, sys, subprocess, re, logging, io
def res(n, ok): print(("PASS " if ok else "FAIL ") + n)
os.makedirs("/tmp/s", exist_ok=True)
open("/tmp/s/tg_token", "w").write("111111:MONITOR-tok\n")
BASE = dict(os.environ, FICHAJE_URL="https://127.0.0.1:1/f/?p=SECRETO", FICHAJE_DNI="00000000T", FICHAJE_CHAT_ID="-100",
            FICHAJE_STATE="/tmp/s/f.json", FICHAJE_HILO="0", TG_CHAT_ID="1", WL_USER="x", WL_PASS="clave-falsa-123")
BASE.pop("FICHAJE_BOT_TOKEN", None); BASE.pop("TG_BOT_TOKEN", None)
code = ("import sys;sys.path.insert(0,'/app');import fichaje as F;"
        "print('ENABLED',F.ENABLED);print('TG_MONITOR',F.TG.endswith('111111:MONITOR-tok'));print('TG_FICHAJE',F.TG.endswith('222222:FICHAJE-tok'));"
        "print('LIMPIA',F._limpia('x 111111:MONITOR-tok y 222222:FICHAJE-tok'))")
def run(env):
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    return r.stdout + r.stderr
o = run(dict(BASE, TG_BOT_TOKEN_FILE="/tmp/s/tg_token"))
res(f"(a) sin FICHAJE_BOT_TOKEN y con TG_BOT_TOKEN_FILE -> ENABLED y mismo bot ({' '.join(o.split()[:4])})",
    "ENABLED True" in o and "TG_MONITOR True" in o)
o = run(dict(BASE, TG_BOT_TOKEN_FILE="/tmp/s/tg_token", FICHAJE_BOT_TOKEN="222222:FICHAJE-tok"))
res(f"(b) con ambos gana FICHAJE_BOT_TOKEN ({' '.join(o.split()[:6])})", "TG_FICHAJE True" in o and "TG_MONITOR False" in o)
lim = o.split("LIMPIA", 1)[1].strip()
res(f"(b') _limpia enmascara los dos tokens: {lim!r}", "MONITOR-tok" not in lim and "FICHAJE-tok" not in lim)
o = run(dict(BASE))
res(f"(a') sin ningun token -> desactivado ({o.split()[:2]})", "ENABLED False" in o)

# monitor.py
os.environ.update(dict(BASE, TG_BOT_TOKEN="333333:MON-tok"))
sys.path.insert(0, "/app")
import monitor as M, requests
r = requests.models.Response(); r.status_code = 400; r.url = "https://api.telegram.org/bot123:ABC/sendMessage"
e = requests.HTTPError("400 Client Error: Bad Request for url: https://api.telegram.org/bot123:ABC/sendMessage", response=r)
t = M.err_txt(e)
res(f"(c) err_txt de un HTTPError de Telegram: {t!r}", "123:ABC" not in t and "HTTP 400" in t and t.startswith("HTTPError"))
t2 = M.err_txt(requests.ConnectionError("https://api.telegram.org/bot333333:MON-tok/getMe ?p=SECRETO p5rkv8nc58hag=ZZZ9 clave-falsa-123"))
res(f"(c') err_txt enmascara token, ?p=, sesion de agenda y WL_PASS: {t2!r}",
    not any(x in t2 for x in ("MON-tok", "SECRETO", "ZZZ9", "clave-falsa")))
src = open("/app/monitor.py").read()
hits = [l for l in src.splitlines() if "{e}" in l]
res(f"(d) grep '{{e}}' en monitor.py: {len(hits)} lineas", not hits)
res("(d') sin str(e) fuera de comentarios", not [l for l in src.splitlines() if "str(e)" in l and not l.strip().startswith("#") and "# _err" not in l])
buf = io.StringIO(); h = logging.StreamHandler(buf); M.log.addHandler(h)
from bs4 import BeautifulSoup
M.extract_agenda_url(BeautifulSoup('<a href="https://agenda2.workandlife.com/x.php?p5rkv8nc58hag=SESIONFALSA&a=1">agenda</a>', "html.parser"))
res(f"(e) 'Agenda URL found' enmascara la sesion: {buf.getvalue().strip()!r}", "SESIONFALSA" not in buf.getvalue() and "<sesion>" in buf.getvalue())

# (f) secretos opcionales que no existen: sin error, se cae a la variable y el fichaje queda desactivado
code_f = ("import sys,logging;logging.basicConfig(level=logging.INFO,format='LOG %(levelname)s %(message)s');"
          "sys.path.insert(0,'/app');import fichaje as F;print('ENABLED',F.ENABLED)")
env = dict(BASE, TG_BOT_TOKEN_FILE="/tmp/s/tg_token", FICHAJE_URL_FILE="/tmp/s/no_existe", FICHAJE_DNI_FILE="/tmp/s/tampoco")
env.pop("FICHAJE_URL", None); env.pop("FICHAJE_DNI", None)
r = subprocess.run([sys.executable, "-c", code_f], env=env, capture_output=True, text=True)
o = r.stdout + r.stderr
res(f"(f) secrets/fichaje_* sin crear -> desactivado y sin ERROR en el log ({o.split()[-2:]})",
    "ENABLED False" in o and "LOG ERROR" not in o and r.returncode == 0)
# (g) fichero creado con PowerShell (BOM UTF-8 + salto de linea) -> se lee bien
open("/tmp/s/tg_bom", "w", encoding="utf-8-sig").write("111111:MONITOR-tok\r\n")
r = subprocess.run([sys.executable, "-c", code], env=dict(BASE, TG_BOT_TOKEN_FILE="/tmp/s/tg_bom"), capture_output=True, text=True)
res("(g) secreto con BOM y CRLF (PowerShell) se lee igual", "TG_MONITOR True" in r.stdout)
r = subprocess.run([sys.executable, "-c", "import sys;sys.path.insert(0,'/app');import os;os.environ['TG_BOT_TOKEN_FILE']='/tmp/s/tg_bom';"
                    "import monitor;print('MON', monitor.TG_BOT_TOKEN == '111111:MONITOR-tok')"],
                   env=dict(BASE, TG_BOT_TOKEN_FILE="/tmp/s/tg_bom"), capture_output=True, text=True, cwd="/tmp")
res("(g') monitor.py tambien lee el secreto con BOM", "MON True" in r.stdout)
