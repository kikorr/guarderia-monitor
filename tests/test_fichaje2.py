"""Permisos del HTML de depuracion, cookies extra e importacion de monitor.py (sin red)."""
import os, stat, sys
os.environ.update(FICHAJE_URL="https://127.0.0.1:1/x/?p=SECRETO", FICHAJE_DNI="1", FICHAJE_BOT_TOKEN="1:a", FICHAJE_CHAT_ID="-1",
                  FICHAJE_STATE="/tmp/f2/f.json", FICHAJE_DEBUG="1", FICHAJE_COOKIES_EXTRA="cc=1; consent = yes ;bad", FICHAJE_HORA="")
os.makedirs("/tmp/f2", exist_ok=True)
sys.path.insert(0, "/app"); os.umask(0o022)
import fichaje as F
def res(n, ok): print(("PASS " if ok else "FAIL ") + n)
F._debug_html("<html>x</html>")
modo = stat.S_IMODE(os.stat(F.DEBUG_HTML).st_mode)
res(f"(D1) HTML de depuracion con permisos {oct(modo)} y HORA vacia -> {F.HORA}", modo == 0o600 and F.HORA == "09:00")
s = F._session({"cookies": {"PHPSESSID": "z"}})
res(f"(D2) cookies de la sesion: {sorted(c.name for c in s.cookies)}", sorted(c.name for c in s.cookies) == ["PHPSESSID", "cc", "consent"])
F._borra_debug_html()
res("(D3) el HTML de depuracion se borra", not F.DEBUG_HTML.exists())
import monitor
res(f"(D4) monitor.py importa; WORK_HOUR {monitor.WORK_HOUR_START}-{monitor.WORK_HOUR_END}, fichaje.ENABLED {monitor.fichaje.ENABLED}",
    (monitor.WORK_HOUR_START, monitor.WORK_HOUR_END) == (7, 17) and monitor.fichaje.ENABLED)
