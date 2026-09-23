"""Pruebas principales del fichaje (sin red, datos inventados). Se ejecutan con tests/run.sh."""
import os, sys, stat, logging, importlib, subprocess
from datetime import datetime
os.environ.update(FICHAJE_URL="https://127.0.0.1:1/fichajes_padres/?p=SECRETO", FICHAJE_DNI="00000000T",
                  FICHAJE_BOT_TOKEN="123456:FAKE-token", FICHAJE_CHAT_ID="-100", FICHAJE_STATE="/tmp/f.json",
                  FICHAJE_HORA="09:00")
if os.path.exists("/tmp/f.json"): os.remove("/tmp/f.json")
logging.basicConfig(level=logging.INFO, format="  log %(levelname)s %(message)s")
sys.path.insert(0, "/app"); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fichaje as F
import requests
from fixture import ficha

calls = []
def fake_tg(method, _timeout=None, **body):
    calls.append((method, body))
    if method == "getUpdates": return PENDING.pop(0) if PENDING else []
    if method == "sendMessage": fake_tg.mid += 1; return {"message_id": fake_tg.mid}
    return True
fake_tg.mid = 100
PENDING = []
F._tg = fake_tg
fichados = []
F.estado = lambda st: (False, {"error": None})
F.fichar = lambda st, info: (fichados.append(1) or (True, "OK"))

def cb(data, mid, cid="-100", n=1):
    return {"id": f"cb{n}", "data": data, "from": {"first_name": "K"},
            "message": {"message_id": mid, "chat": {"id": cid}}}
def answers(): return [b["text"] for m, b in calls if m == "answerCallbackQuery"]
def res(name, ok): print(("PASS " if ok else "FAIL ") + name)

now = datetime.now().replace(hour=9, minute=5)
hoy = now.strftime("%Y-%m-%d")

# (1) Si sin pregunta vigente
st = F.load_state(); calls.clear()
F._procesar_callback(st, cb("fichar_si", 55), now)
res("(1) si sin pregunta no ficha y contesta caducada",
    not fichados and answers() == ["Pregunta caducada"]
    and any(m == "editMessageReplyMarkup" and b["message_id"] == 55 for m, b in calls))
st = F.load_state(); st.update(asked_date="2000-01-01", asked_msg_ids=[77]); F._nuevo_dia(st, hoy)
calls.clear(); F._procesar_callback(st, cb("fichar_si", 77), now)
res("(1b) mensaje de otro dia no vale aunque asked_date=hoy", not fichados and answers() == ["Pregunta caducada"])
st = F.load_state(); F.preguntar(st, hoy); mid = st["asked_msg_ids"][-1]
calls.clear(); F._procesar_callback(st, cb("fichar_si", mid), now.replace(hour=12, minute=0))
res("(1c) fuera de la ventana de 3 h -> caducada", not fichados and answers() == ["Pregunta caducada"])

# (2) Si valido ficha una vez; segunda pulsacion no
st = F.load_state(); st["asked_date"] = None; st["q_envios"] = 0; F.preguntar(st, hoy)
F.preguntar(st, hoy, motivo="recordatorio")
ids = list(st["asked_msg_ids"])
calls.clear()
F._procesar_callback(st, cb("fichar_si", ids[0]), now)
quitados = [b["message_id"] for m, b in calls if m == "editMessageReplyMarkup"]
F._procesar_callback(st, cb("fichar_si", ids[1], n=2), now)
F._procesar_callback(st, cb("fichar_si", ids[0], n=3), now)
res(f"(2) si valido ficha una vez (fichados={len(fichados)}, answers={answers()}, quita botones de {quitados})",
    len(fichados) == 1 and answers() == ["Fichando…", "Pregunta caducada", "Pregunta caducada"]
    and ids[1] in quitados and st["done_date"] == hoy)
st2 = F.load_state(); calls.clear(); F._procesar_callback(st2, cb("fichar_si", ids[1], n=4), now)
res("(2b) tras recargar estado tampoco vuelve a fichar", len(fichados) == 1)

# (3) No bloquea un Si posterior
fichados.clear(); st = F.load_state(); st["asked_date"] = None; st["q_envios"] = 0; F.preguntar(st, hoy); mid = st["asked_msg_ids"][-1]
calls.clear()
F._procesar_callback(st, cb("fichar_no", mid), now)
F._procesar_callback(st, cb("fichar_si", mid, n=2), now)
res(f"(3) no bloquea un si posterior (answers={answers()})", not fichados and answers() == ["Vale, hoy no se ficha.", "Pregunta caducada"])

st = F.load_state(); st.update(test_date=hoy, test_msg_ids=[900]); calls.clear()
F._procesar_callback(st, cb("test_si", 900), now); F._procesar_callback(st, cb("test_si", 901, n=2), now)
F._procesar_callback(st, cb("test_no", 900, n=3), now)
res(f"(extra) test_si/test_no: responde sin fichar y valida mensaje (answers={answers()})",
    not fichados and answers() == ["Prueba recibida, no hago nada.", "Pregunta caducada", "Pregunta caducada"])

# (4) primer arranque con updates viejos
os.remove("/tmp/f.json"); fichados.clear()
st = F.load_state(); st.update(asked_date=hoy, asked_msg_ids=[500])
old = [{"update_id": 10 + i, "callback_query": cb("fichar_si", 500, n=i)} for i in range(3)]
PENDING[:] = [old[-1:], []]; calls.clear()
F.poll_telegram(st, now)
gu = [b for m, b in calls if m == "getUpdates"]
res(f"(4) primer arranque descarta pendientes (offset={st['tg_offset']}, primed={st['tg_primed']}, getUpdates offset={gu[0]['offset']})",
    not fichados and not answers() and st["tg_offset"] == 12 and st["tg_primed"] and gu[0]["offset"] == -1)
PENDING[:] = [[{"update_id": 13, "callback_query": cb("fichar_no", 1, n=9)}]]; calls.clear()
F.poll_telegram(st, now)
gu = [b for m, b in calls if m == "getUpdates"]
res(f"(4b) segundo poll usa offset+1={gu[0]['offset']} y procesa", gu[0]["offset"] == 13 and st["tg_offset"] == 13)

# (5) _err nunca contiene SECRETO
errs = []
try:
    requests.get(F.URL_QR, timeout=0.5)
except Exception as e:
    errs.append(e); print("  str(e) crudo contiene SECRETO:", "SECRETO" in str(e))
r = requests.models.Response(); r.status_code = 500; r.url = F.URL_QR
errs.append(requests.HTTPError(f"500 Server Error for url: {F.URL_QR}", response=r))
errs.append(ValueError("algo ?p=SECRETO&x=1")); errs.append(F.FichajeError("fallo en " + F.URL_QR + " dni 00000000T"))
errs.append(requests.ConnectionError("https://api.telegram.org/bot123456:FAKE-token/getUpdates"))
outs = [F._err(e) for e in errs]
for o in outs: print("  _err ->", o)
res("(5) _err no filtra SECRETO/token/DNI", not any(("SECRETO" in o or "FAKE-token" in o or "00000000T" in o) for o in outs))

# (6) ficha REAL (estructura del 23-sep) con fixture sintetico
importlib.reload(F); F._tg = fake_tg
sent = []
class R:
    status_code = 200
    def __init__(self, j): self.j = j
    def json(self): return self.j
RESP = {"Resultado": "OK", "Descripcion": "Registro realizado"}
def fake_post(self, url, files=None, **k): sent.append(files); return R(RESP)
requests.Session.post = fake_post
def enviado(): return [(k, v[1]) for k, v in sent[-1]] if sent else None

a = F._parse_ficha(ficha([{"id": "4101", "entrada": "08:54", "salida": "17:15", "disabled": True}]))
res(f"(6a) entrada y salida hechas + chk disabled/hidden -> hecho True, pendientes [] (tipo_web={a['tipo_web']}, error={a['error']})",
    a["hecho"] is True and a["pendientes"] == [] and not a["error"] and a["alumnos"][0]["entrada"] == "08:54"
    and a["alumnos"][0]["salida"] == "17:15" and a["alumnos"][0]["disabled"])
res("(6a') la info no lleva nombres", "INVENTAD" not in repr(a))

b = F._parse_ficha(ficha([{"id": "4101"}])); b["centro"] = "C1"
res(f"(6b) sin li de Entrada, chk activo sin checked -> hecho False, pendientes {b['pendientes']}",
    b["hecho"] is False and b["pendientes"] == ["4101"] and not b["error"])
F.estado = lambda st: (True, dict(F._parse_ficha(ficha([{"id": "4101", "entrada": "09:01"}])), centro="C1"))
sent.clear(); ok, txt = F.fichar(F.load_state(), b)
res(f"(6b') fichar envia chk_<id> y tipo=1 y comprueba la entrada: {enviado()} -> {ok} {txt!r}",
    ok and enviado() == [("chk_4101", "4101"), ("padre", "P1"), ("idCentro", "C1"), ("tipo", "1")])

c = F._parse_ficha(ficha([{"id": "4101"}, {"id": "4102", "ausente": True}])); c["centro"] = "C1"
F.estado = lambda st: (True, dict(F._parse_ficha(ficha([{"id": "4101", "entrada": "09:01"}, {"id": "4102", "ausente": True}])), centro="C1"))
sent.clear(); ok, txt = F.fichar(F.load_state(), c)
res(f"(6c) dos ninos, uno ausente -> pendientes {c['pendientes']}, envia {enviado()}",
    c["pendientes"] == ["4101"] and ok and [x for x in enviado() if x[0].startswith("chk_")] == [("chk_4101", "4101")])
c2 = F._parse_ficha(ficha([{"id": "4101", "entrada": "08:50"}, {"id": "4102", "ausente": True}]))
res("(6c') el unico presente con entrada y el otro ausente -> hecho True", c2["hecho"] is True)

d = F._parse_ficha(ficha([{"id": "4101"}], p3="2")); d["centro"] = "C1"
sent.clear()
try:
    F.fichar(F.load_state(), d); lanzo = None
except F.FichajeNoTransitorio as e:
    lanzo = F._err(e)
res(f"(6d) tipo_web 2 -> error_tipo {d['error_tipo']}, fichar no hace POST ({lanzo})",
    d["error_tipo"] == "tipo" and lanzo and "tipo 2" in lanzo and not sent)
# y en el flujo de las 09:00: aviso y dia marcado, sin pregunta
os.remove("/tmp/f.json"); F._ST = None; F._save_ok = True
st = F.load_state(); st["tg_primed"] = True; F.save_state(st); F._ST = None
F.estado = lambda st: (False, dict(F._parse_ficha(ficha([{"id": "4101"}], p3="2")), centro="C1"))
calls.clear()
for m in range(0, 50): F.tick(now.replace(minute=m), lambda: True)
envios = [b.get("text", "") for m, b in calls if m == "sendMessage"]
res(f"(6d') a las 09:00 con tipo 2: 1 aviso, ninguna pregunta ({[e[:60] for e in envios]})",
    len(envios) == 1 and "tipo 2" in envios[0] and not any(b.get("reply_markup") for m, b in calls if m == "sendMessage"))

e = F._parse_ficha(ficha([{"id": "4101"}], btn=False))
res(f"(6e) sin #btn_alu -> error botones ({e['error']})", e["error_tipo"] == "botones" and not e["hecho"])
f = F._parse_ficha(ficha([]))
res(f"(6f) sin alumnos -> error ({f['error']})", f["error_tipo"] == "botones" and "no lista alumnos" in f["error"] and not f["hecho"])
g = F._parse_ficha(ficha([{"id": "4101"}])); g["centro"] = "C1"
F.estado = lambda st: (False, dict(F._parse_ficha(ficha([{"id": "4101"}])), centro="C1"))   # tras el POST sigue sin entrada
sent.clear()
try:
    F.fichar(F.load_state(), g); lanzo = None
except F.FichajeNoTransitorio as ex:
    lanzo = F._err(ex)
res(f"(6g) JSON OK pero la ficha no muestra la entrada -> no reintenta ({len(sent)} POST, {lanzo})",
    len(sent) == 1 and lanzo and "la web dice OK pero la ficha no muestra la entrada" in lanzo)
# por el camino del Si: 1 POST, si_pendiente False, sin reintentos
os.remove("/tmp/f.json"); F._ST = None
st = F.load_state(); st.update(tg_primed=True, asked_date=hoy, asked_msg_ids=[7], answer="si", answer_date=hoy,
                               si_pendiente=True, si_msg_id=7, si_quien="K")
F.save_state(st); F._ST = None; sent.clear(); calls.clear()
for m in range(10, 60): F.tick(now.replace(minute=m), lambda: True)
edits = [b["text"][:40] for m, b in calls if m == "editMessageText"]
res(f"(6g') Si con OK no verificado: {len(sent)} POST, si_pendiente={F._ST['si_pendiente']}, edits={edits}",
    len(sent) == 1 and not F._ST["si_pendiente"] and len(edits) == 1)
h = F._parse_ficha(ficha([], pide_dni=True))
res("(6h) sigue pidiendo DNI -> error dni", h["error_tipo"] == "dni" and not h["hecho"])
# pregunta con el numero de ninos, sin nombres
os.remove("/tmp/f.json"); F._ST = None
st = F.load_state(); st["tg_primed"] = True; F.save_state(st); F._ST = None
F.estado = lambda st: (False, dict(F._parse_ficha(ficha([{"id": "4101"}, {"id": "4102"}, {"id": "4103", "entrada": "08:40"}])), centro="C1"))
calls.clear(); F.tick(now.replace(minute=0), lambda: True)
preg = [b["text"] for m, b in calls if m == "sendMessage"]
res(f"(6i) la pregunta dice cuantos faltan y no lleva nombres ({preg[0].splitlines()[1] if preg else None!r})",
    len(preg) == 1 and "2 niños sin entrada" in preg[0] and "INVENTAD" not in preg[0])

# (7) HORA invalida
for bad in ("25:00", "9h", "", "09:60"):
    os.environ["FICHAJE_HORA"] = bad
    importlib.reload(F)
    print(f"  FICHAJE_HORA={bad!r} -> HORA={F.HORA} ({F.HH},{F.MM})")
res("(7) HORA invalida no revienta y usa 09:00", F.HORA == "09:00")
os.environ["FICHAJE_HORA"] = "09:00"; importlib.reload(F); F._tg = fake_tg

# (8) permisos + ALTA-3/BAJA-2 via tick
os.umask(0o022)
if os.path.exists("/tmp/f.json"): os.remove("/tmp/f.json")
F.save_state(F.load_state())
res(f"(8) fichaje.json modo {oct(stat.S_IMODE(os.stat('/tmp/f.json').st_mode))}", stat.S_IMODE(os.stat('/tmp/f.json').st_mode) == 0o600)

def boom(method, _timeout=None, **b):
    r = requests.models.Response(); r.status_code = 401
    raise requests.HTTPError("401 for url https://api.telegram.org/bot123456:FAKE-token/sendMessage", response=r)
F._tg = boom
F.estado = lambda st: (False, {"error": None, "pendientes": ["1"]})
os.remove("/tmp/f.json"); st = F.load_state(); st["tg_primed"] = True; F.save_state(st); F._ST = None
try:
    for m in range(0, 60, 1):
        F.tick(now.replace(minute=m), lambda: True)
    st = F.load_state()
    res(f"(ALTA-3) Telegram 401 no sale de tick; err_count={st['err_count']} asked={st['asked_date']==hoy} reminded={st['reminded_date']==hoy}",
        st["err_count"] == 3 and st["reminded_date"] == hoy)
except Exception as e:
    res(f"(ALTA-3) tick lanzó {type(e).__name__}", False)
F._tg = fake_tg
def web_ko(st): raise requests.ConnectionError("x " + F.URL_QR)
F.estado = web_ko
os.remove("/tmp/f.json"); st = F.load_state(); st["tg_primed"] = True; F.save_state(st); F._ST = None; calls.clear()
for m in range(0, 59, 1):
    F.tick(now.replace(minute=m), lambda: True)
sends = [b["text"] for mm, b in calls if mm == "sendMessage"]
res(f"(BAJA-2) error de web: 1 aviso, sin recordatorio ({len(sends)} envios: {sends})", len(sends) == 1 and "SECRETO" not in sends[0])
F.DIAS_CERRADO = {hoy}; F.estado = lambda st: (_ for _ in ()).throw(AssertionError("no deberia mirar la web"))
os.remove("/tmp/f.json"); st = F.load_state(); st["tg_primed"] = True; F.save_state(st); F._ST = None; calls.clear()
F.tick(now, lambda: True)
res("(BAJA-3) dia cerrado: ni web ni pregunta", not [c for c in calls if c[0] == "sendMessage"])

# (CLI) una excepcion se imprime con _err, sin traceback ni token (sin red: ConnectionError)
env = dict(os.environ, FICHAJE_STATE="/tmp/cli.json")
r = subprocess.run([sys.executable, "/app/fichaje.py", "test-bot"], env=env, capture_output=True, text=True, timeout=60)
out = r.stdout + r.stderr
print("  CLI test-bot ->", out.strip().splitlines()[-1] if out.strip() else "(nada)")
res("(CLI) test-bot con fallo: sin traceback, sin token, sin ?p=",
    r.returncode == 1 and "Traceback" not in out and "FAKE-token" not in out and "SECRETO" not in out and out.strip().startswith("error:"))
