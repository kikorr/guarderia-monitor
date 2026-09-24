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

FICHA = ficha([{"id": "4101", "entrada": "09:15"}])
VACIA = ficha([])
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
