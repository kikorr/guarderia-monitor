"""Token CSRF del login (01-oct-2026): del numerico antiguo a la cadena de 64 caracteres.
Sin red: requests.Session simulada; formularios y tokens INVENTADOS."""
import os, sys, logging, io
os.environ.update(FICHAJE_URL="https://127.0.0.1:1/fichajes_padres/?p=SECRETO", FICHAJE_DNI="00000000T",
                  FICHAJE_BOT_TOKEN="123456:FAKE-token", FICHAJE_CHAT_ID="-100", FICHAJE_STATE="/tmp/lt/f.json",
                  FICHAJE_HILO="0", TG_BOT_TOKEN="x", TG_CHAT_ID="1", WL_USER="usuario-inventado", WL_PASS="clave-inventada")
os.makedirs("/tmp/lt", exist_ok=True)
sys.path.insert(0, "/app")
buf = io.StringIO()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", handlers=[logging.StreamHandler(buf)])
import monitor as M
def res(n, ok): print(("PASS " if ok else "FAIL ") + n)

TOK64 = "a3F9" * 16          # 64 caracteres inventados
assert len(TOK64) == 64
def form(token_input):
    return f'''<html><body><form id="fLogin" name="fLogin" method="post" action="index.php">
      <input type="text" name="usuario" id="usuario"><input type="password" name="contrasena" id="contrasena">
      {token_input}<input type="hidden" name="grecaptcha" id="grecaptcha" value="">
      <button type="submit">Entrar</button></form></body></html>'''
ANTIGUO = form('<input type="hidden" name="_token" id="_token" value="1727512345">')
NUEVO = form(f'<input type="hidden" name="_token" id="_token" value="{TOK64}">')
NUEVO_INVERSO = form(f"<input value='{TOK64}' id='_token' type='hidden' name='_token'>")
SIN_TOKEN = form("")

class R:
    def __init__(self, text, url): self.text, self.url, self.status_code = text, url, 200
    def raise_for_status(self): pass
class Sesion:
    ultimo = None
    def __init__(self): self.posts = []; Sesion.ultimo = self
    def get(self, url, timeout=None, **k): return R(Sesion.pagina, url)
    def post(self, url, data=None, timeout=None, **k):
        self.posts.append((url, dict(data or {})))
        return R("<a href='/logout.php'>Salir</a>", "https://centro-inventado.workandlife.com/inicio.php")
M.requests.Session = Sesion
alertas = []
M.alert_once = lambda key, msg, cooldown_min=180: alertas.append(key)

def login(pagina):
    Sesion.pagina = pagina; M._session = None; M.PORTAL_ORIGIN = ""; alertas.clear()
    buf.truncate(0); buf.seek(0)
    return M.do_login(), Sesion.ultimo

# extractor aislado
res("(T1) extrae token numerico antiguo", M.extract_login_token(ANTIGUO) == "1727512345")
res("(T2) extrae token de 64 caracteres", M.extract_login_token(NUEVO) == TOK64)
res("(T3) atributos en orden inverso y comillas simples", M.extract_login_token(NUEVO_INVERSO) == TOK64)
_bs = M.BeautifulSoup
def _roto(*a, **k): raise RuntimeError("parser roto")
M.BeautifulSoup = _roto
res("(T4) respaldo regex si BeautifulSoup falla (ambos ordenes)",
    M.extract_login_token(NUEVO) == TOK64 and M.extract_login_token(NUEVO_INVERSO) == TOK64
    and M.extract_login_token(ANTIGUO) == "1727512345" and M.extract_login_token(SIN_TOKEN) is None)
M.BeautifulSoup = _bs
res("(T5) sin _token -> None", M.extract_login_token(SIN_TOKEN) is None and M.extract_login_token("") is None)

# do_login de punta a punta con la sesion simulada
for nombre, pagina, esperado in (("antiguo", ANTIGUO, "1727512345"), ("64 car.", NUEVO, TOK64)):
    s, ses = login(pagina)
    ok = (s is ses and len(ses.posts) == 1 and ses.posts[0][0].endswith("/index.php")
          and ses.posts[0][1] == {"usuario": "usuario-inventado", "contrasena": "clave-inventada",
                                  "_token": esperado, "grecaptcha": ""}
          and M.PORTAL_ORIGIN == "https://centro-inventado.workandlife.com" and "Login OK" in buf.getvalue())
    res(f"(L-{nombre}) do_login envia el _token completo y queda logueado", ok)
    res(f"(L-{nombre}') el log no lleva token ni credenciales",
        esperado not in buf.getvalue() and "clave-inventada" not in buf.getvalue())

s, ses = login(SIN_TOKEN)
log_txt = buf.getvalue()
res(f"(L-sin) sin _token: no hay POST, None y error de estructura ({log_txt.strip()!r})",
    s is None and ses.posts == [] and "estructura del formulario" in log_txt and alertas == ["login-token"])
