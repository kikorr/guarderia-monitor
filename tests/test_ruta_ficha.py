"""Como se llega a la ficha del padre: via cookie (tieneCookie) o via DNI (sin red, ids inventados)."""
import os, sys, logging, io
os.environ.update(FICHAJE_URL="https://127.0.0.1:1/fichajes_padres/?p=SECRETO", FICHAJE_DNI="00000000T",
                  FICHAJE_BOT_TOKEN="123456:FAKE-token", FICHAJE_CHAT_ID="-100", FICHAJE_STATE="/tmp/rf/f.json",
                  FICHAJE_HILO="0", FICHAJE_HORA_SALIDA="")
os.makedirs("/tmp/rf", exist_ok=True)
sys.path.insert(0, "/app"); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
buf = io.StringIO()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", handlers=[logging.StreamHandler(buf)])
import requests
import fichaje as F
from fixture import ficha, respuesta_cookie, formulario_dni
def res(n, ok): print(("PASS " if ok else "FAIL ") + n)

FICHA = ficha([{"id": "4101", "entrada": "09:15"}], padre="55555")
VACIA = ficha([], padre="55555")
class R:
    def __init__(self, t): self.text = t; self.status_code = 200
    def raise_for_status(self): pass
class Sesion:
    """Session falsa: respuestas por ruta. padre_cookie / padre_dni = HTML de compruebaPadre segun los datos."""
    def __init__(self, user, padre_cookie=FICHA, padre_dni=FICHA):
        self.user, self.padre_cookie, self.padre_dni, self.posts = user, padre_cookie, padre_dni, []
        self.cookies = requests.cookies.RequestsCookieJar()
    def post(self, url, data=None, timeout=None, **k):
        self.posts.append((url.rsplit("/", 1)[-1], dict(data or {})))
        if url.endswith("compruebaUser.php"):
            return R(self.user)
        return R(self.padre_cookie if "idUser" in (data or {}) else self.padre_dni)
def run(sesion):
    buf.truncate(0); buf.seek(0)
    html = F._ficha_padre(F.load_state(), sesion, "9")
    return html, F._parse_ficha(html), [(u, d) for u, d in sesion.posts]

# cookie -> 1 POST compruebaPadre con idUser/idCentro/tipo y sin dni
h, info, posts = run(Sesion(respuesta_cookie("55555", "9", "1")))
res(f"(c1) via cookie: {posts}",
    posts == [("compruebaUser.php", {"id": "9"}), ("compruebaPadre.php", {"idUser": "55555", "idCentro": "9", "tipo": "1"})]
    and len(info["alumnos"]) == 1 and not info["error"])
res(f"(c1') log «ficha vía cookie» sin ids: {buf.getvalue().strip()!r}",
    "ficha vía cookie" in buf.getvalue() and "55555" not in buf.getvalue())
# formulario DNI -> ruta DNI
h, info, posts = run(Sesion(formulario_dni()))
res(f"(c2) formulario de DNI -> ruta DNI: {[(u, sorted(d)) for u, d in posts]}",
    posts == [("compruebaUser.php", {"id": "9"}), ("compruebaPadre.php", {"dni": "00000000T", "idCentro": "9"})]
    and len(info["alumnos"]) == 1 and "ficha vía DNI" in buf.getvalue() and "00000000T" not in buf.getvalue())
# respuesta rara -> intenta DNI; si tampoco hay alumnos, error «botones»
h, info, posts = run(Sesion("<div>algo inesperado</div>"))
res(f"(c3) respuesta rara -> prueba el DNI y lee la ficha ({[u for u, d in posts]})",
    [u for u, d in posts] == ["compruebaUser.php", "compruebaPadre.php"] and "dni" in posts[1][1] and len(info["alumnos"]) == 1)
h, info, posts = run(Sesion("<div>algo inesperado</div>", padre_dni=VACIA))
res(f"(c3') ...y si tampoco hay alumnos -> error botones ({info['error_tipo']}: {info['error']})",
    info["error_tipo"] == "botones" and "no lista alumnos" in info["error"])
# ficha via cookie sin alumnos -> reintenta via DNI
h, info, posts = run(Sesion(respuesta_cookie("55555", "9", "1"), padre_cookie=VACIA))
res(f"(c4) cookie sin alumnos -> reintenta via DNI ({[(u, sorted(d)) for u, d in posts]})",
    [sorted(d) for u, d in posts] == [["id"], ["idCentro", "idUser", "tipo"], ["dni", "idCentro"]]
    and len(info["alumnos"]) == 1 and "pruebo vía DNI" in buf.getvalue() and "ficha vía DNI" in buf.getvalue())
h, info, posts = run(Sesion(respuesta_cookie("55555", "9", "1"), padre_cookie=VACIA, padre_dni=VACIA))
res(f"(c4') cookie y DNI sin alumnos -> error botones", info["error_tipo"] == "botones")
# de punta a punta: estado() con la ruta de la cookie (login + compruebaUser + compruebaPadre)
class RG:
    text = "<script>compruebaParametrosLatLong(40.1, -3.7, '9')</script>"; status_code = 200
    def raise_for_status(self): pass
ses = Sesion(respuesta_cookie("55555", "9", "1"))
requests.Session.get = lambda self, url, **k: RG()
requests.Session.post = lambda self, url, **k: ses.post(url, **k)
st = F.load_state(); hecho, info = F.estado(st)
res(f"(c5) estado() via cookie: {len(info['alumnos'])} alumno, entrada {info['alumnos'][0]['entrada']}, sin dni en ningun POST",
    len(info["alumnos"]) == 1 and info["alumnos"][0]["entrada"] == "09:15" and hecho
    and not any("dni" in d for u, d in ses.posts))


# ══ Ronda 13 ══════════════════════════════════════════════════════════════════
def fresh_state():
    if os.path.exists("/tmp/rf/f.json"): os.remove("/tmp/rf/f.json")
    F._ST = None
# (p1) tieneCookie con OTRO centro -> WARNING sin ids y ruta del DNI
fresh_state()
h, info, posts = run(Sesion(respuesta_cookie("55555", "8", "1")))
res(f"(p1) cookie de otro centro -> ruta DNI, sin idUser ({[sorted(d) for u, d in posts]})",
    [sorted(d) for u, d in posts] == [["id"], ["dni", "idCentro"]] and "otro centro" in buf.getvalue()
    and "55555" not in buf.getvalue() and "ficha vía DNI" in buf.getvalue())
# (p2) la ficha via cookie trae un data-p1 distinto del idUser enviado -> error no transitorio, sin POST de fichaje
def estado_con(sesion):
    requests.Session.post = lambda self, url, **k: sesion.post(url, **k)
    return F.estado(F.load_state())
requests.Session.get = lambda self, url, **k: RG()
fresh_state()
otra = ficha([{"id": "4101"}], padre="77777")
hecho, info = estado_con(Sesion(respuesta_cookie("55555", "9", "1"), padre_cookie=otra))
res(f"(p2) cookie con data-p1 distinto -> {info['error_tipo']}: {info['error']}",
    info["error_tipo"] == "padre" and not hecho and "no corresponde al padre esperado" in info["error"])
try:
    F.fichar(F.load_state(), info); lanzo = None
except F.FichajeNoTransitorio as e:
    lanzo = F._err(e)
res(f"(p2b) fichar() con ese info -> no transitorio y sin POST ({lanzo})", bool(lanzo) and "no corresponde" in lanzo)
# (p3) padre_id: se guarda en la 1.a lectura por DNI; luego otra ficha -> error
fresh_state()
buf.truncate(0); buf.seek(0)
hecho, info = estado_con(Sesion(formulario_dni(), padre_dni=ficha([{"id": "4101"}], padre="55555")))
st = F.load_state()
res(f"(p3) 1.a lectura por DNI guarda padre_id ({st.get('padre_id')!r}) y no lo escribe en el log",
    st.get("padre_id") == "55555" and not info["error"] and "55555" not in buf.getvalue())
hecho, info = estado_con(Sesion(formulario_dni(), padre_dni=ficha([{"id": "4101"}], padre="77777")))
res(f"(p3b) lectura posterior con otro data-p1 -> {info['error_tipo']}", info["error_tipo"] == "padre")
hecho, info = estado_con(Sesion(respuesta_cookie("55555", "9", "1")))
res("(p3c) con el mismo padre (via cookie) -> sin error", not info["error"] and len(info["alumnos"]) == 1)
# (p3d) en el flujo de las 09:00: aviso y dia marcado, sin pregunta
calls = []
def fake_tg(method, _timeout=None, **b):
    calls.append((method, b))
    return {"message_id": 1} if method == "sendMessage" else ([] if method == "getUpdates" else True)
F._tg = fake_tg
st = F.load_state(); st.update(tg_primed=True); F.save_state(st); F._ST = None
s77 = Sesion(formulario_dni(), padre_dni=ficha([{"id": "4101"}], padre="77777"))
requests.Session.post = lambda self, url, **k: s77.post(url, **k)
from datetime import datetime
F.tick(datetime.now().replace(hour=9, minute=0), lambda: True)
env = [b for m, b in calls if m == "sendMessage"]
res(f"(p3d) 09:00 con otro padre -> 1 aviso y ninguna pregunta ({[e['text'][:60] for e in env]})",
    len(env) == 1 and not env[0].get("reply_markup") and "no corresponde al padre esperado" in env[0]["text"])
# (p4) HTTPError en el POST via cookie -> cae a la ruta del DNI
class Sesion500(Sesion):
    def post(self, url, data=None, timeout=None, **k):
        if "idUser" in (data or {}):
            self.posts.append(("compruebaPadre.php", dict(data)))
            class E:
                status_code = 500; text = ""
                def raise_for_status(self):
                    r = requests.models.Response(); r.status_code = 500
                    raise requests.HTTPError("500", response=r)
            return E()
        return super().post(url, data=data, timeout=timeout, **k)
fresh_state()
h, info, posts = run(Sesion500(respuesta_cookie("55555", "9", "1")))
res(f"(p4) 500 en la ruta cookie -> ruta DNI ({[sorted(d) for u, d in posts]})",
    [sorted(d) for u, d in posts] == [["id"], ["idCentro", "idUser", "tipo"], ["dni", "idCentro"]]
    and len(info["alumnos"]) == 1 and "falló (HTTPError HTTP 500)" in buf.getvalue())
# (p5) _pide_dni por estructura, no por texto; _parse_ficha no marca dni si hay alumnos
res("(p5) texto o script que menciona el DNI no es un formulario",
    not F._pide_dni("<script>function comprobarPadreValido(){}</script><p>introduce tu DNI</p>")
    and F._pide_dni(formulario_dni()) and F._pide_dni('<div data-fn="comprobarPadreValido"></div>'))
con_texto = ficha([{"id": "4101"}], padre="55555").replace("Por defecto", "Si no te reconoce, introduce tu DNI. Por defecto")
inf = F._parse_ficha(con_texto)
res(f"(p5b) ficha con alumnos y el texto «introduce tu DNI» -> sin error dni ({inf['error_tipo']})",
    inf["error_tipo"] is None and len(inf["alumnos"]) == 1)
