"""Horario de la agenda como 2.ª fuente del fichaje (sin red, datos inventados)."""
import os, sys, json, logging, io
from datetime import datetime, timedelta
from pathlib import Path
os.environ.update(FICHAJE_URL="https://127.0.0.1:1/fichajes_padres/?p=SECRETO", FICHAJE_DNI="00000000T",
                  FICHAJE_BOT_TOKEN="123456:FAKE-token", FICHAJE_CHAT_ID="-100", FICHAJE_STATE="/tmp/ag/f.json",
                  FICHAJE_HORA="09:00", FICHAJE_HILO="0", TG_BOT_TOKEN="x", TG_CHAT_ID="1", WL_USER="x", WL_PASS="x")
os.makedirs("/tmp/ag", exist_ok=True)
sys.path.insert(0, "/app"); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
buf = io.StringIO()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", handlers=[logging.StreamHandler(buf)])
import monitor as M
import fichaje as F
from fixture import agenda, agenda_real
def res(n, ok): print(("PASS " if ok else "FAIL ") + n)

# ── monitor.py: parse_horario ─────────────────────────────────────────────────
h0 = M.parse_horario(agenda())
h1 = M.parse_horario(agenda(entrada="09:05"))
h2 = M.parse_horario(agenda(entrada="09:05", salida="17:10"))
h3 = M.parse_horario(agenda(con_horario=False))
res(f"(M1) «No disponible» -> {h0}", h0 == {"entrada": None, "salida": None, "ok": True})
res(f"(M2) con entrada -> {h1}; con las dos -> {h2}", h1["entrada"] == "09:05" and h1["salida"] is None and h2["salida"] == "17:10")
res(f"(M3) sin apartado Horario -> ok False ({h3})", h3["ok"] is False)
res("(M4) Horario sigue fuera del mensaje de la agenda", "Horario" not in M.parse_agenda(agenda(entrada="09:05")))
# misma bateria con la estructura REAL (pestaña + info-titulo.cHorario + dos info-texto.corto hermanos)
r0 = M.parse_horario(agenda_real())
r1 = M.parse_horario(agenda_real(entrada="09:05"))
r2 = M.parse_horario(agenda_real(entrada="09:05", salida="17:10"))
r3 = M.parse_horario(agenda_real().replace("<span>Horario</span>", "<span>Otra cosa</span>").replace(">Horario<", ">Pestaña<"))
res(f"(M1r) real, «No disponible» -> {r0}", r0 == {"entrada": None, "salida": None, "ok": True})
res(f"(M2r) real, con entrada -> {r1}; con las dos -> {r2}", r1 == {"entrada": "09:05", "salida": None, "ok": True}
    and r2 == {"entrada": "09:05", "salida": "17:10", "ok": True})
res(f"(M3r) real sin apartado Horario -> ok False ({r3})", r3["ok"] is False and r3["entrada"] is None)
res("(M3r') la 'Entrada: 12:00' de otro apartado no se cuela", M.parse_horario(agenda_real())["entrada"] is None)
p0 = M.parse_horario(agenda_real(con_titulo=False)); p1 = M.parse_horario(agenda_real(entrada="09:05", salida="17:10", con_titulo=False))
res(f"(M1p/M2p) respaldo por texto plano de div.contenido-info -> {p0} / {p1}",
    p0 == {"entrada": None, "salida": None, "ok": True} and p1 == {"entrada": "09:05", "salida": "17:10", "ok": True})

# ── monitor.py: agenda_horario con cache ─────────────────────────────────────
M.STATE_FILE = Path("/tmp/ag/state.json")
M.STATE_FILE.write_text(json.dumps({"agenda_url": "https://agenda2.workandlife.com//info/?p5rkv8nc58hag=SESIONFALSA123"}))
gets = []
HTML = {"v": agenda()}
class R:
    def __init__(self, t): self.content = t.encode("iso-8859-1", "replace"); self.status_code = 200
    def raise_for_status(self): pass
def fake_get(url, timeout=None):
    gets.append(url)
    if HTML["v"] is None: raise M.requests.ConnectionError("x " + url)
    return R(HTML["v"])
M.requests.get = fake_get
M._horario_cache.clear()
a = M.agenda_horario(); b = M.agenda_horario()
res(f"(M5) primera llamada descarga, la segunda usa la cache ({len(gets)} GET) -> {a}",
    len(gets) == 1 and a == {"entrada": None, "salida": None, "fecha": datetime.now().strftime("%Y-%m-%d"), "ok": True} and b == a)
HTML["v"] = agenda(entrada="09:12"); c = M.agenda_horario(forzar=True)
res(f"(M6) forzar descarga otra vez ({len(gets)} GET) -> entrada {c['entrada']}", len(gets) == 2 and c["entrada"] == "09:12")
M._horario_cache["leido"] = datetime.now() - timedelta(minutes=40); M.agenda_horario()
res(f"(M7) lectura de hace 40 min -> se descarga ({len(gets)} GET)", len(gets) == 3)
M._horario_cache["fecha"] = "2000-01-01"; M._horario_cache["leido"] = datetime.now(); M.agenda_horario()
res(f"(M8) lectura de otro dia -> se descarga ({len(gets)} GET)", len(gets) == 4)
HTML["v"] = None; d = M.agenda_horario(forzar=True)
res(f"(M9) agenda caida -> ok False sin lanzar ({d})", d["ok"] is False and d["entrada"] is None)
# check_agenda deja el horario en la cache: agenda_horario() no vuelve a descargar
HTML["v"] = agenda(entrada="08:58"); M._horario_cache.clear(); n = len(gets)
M.check_agenda({"agenda_url": json.loads(M.STATE_FILE.read_text())["agenda_url"]}, first_run=True)
e = M.agenda_horario()
res(f"(M10) la comprobacion periodica alimenta la cache (GET extra={len(gets) - n - 1}) -> {e['entrada']}",
    len(gets) == n + 1 and e["entrada"] == "08:58")
logs = buf.getvalue()
res("(M11) los logs no llevan la sesion de la agenda ni nombres", "SESIONFALSA" not in logs and "INVENTADO" not in logs and "<sesion>" in logs)

# ── fichaje.py: la agenda como 2.ª fuente ────────────────────────────────────
calls = []
def fake_tg(method, _timeout=None, **b):
    calls.append((method, b))
    if method == "getUpdates": return []
    if method == "sendMessage": fake_tg.mid += 1; return {"message_id": fake_tg.mid}
    return True
fake_tg.mid = 100
now = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
hoy = now.strftime("%Y-%m-%d")
AG = {"h": None, "forzados": 0, "lanza": False}
def fake_agenda(forzar=False):
    if forzar: AG["forzados"] += 1
    if AG["lanza"]: raise RuntimeError("agenda rota")
    return dict(AG["h"], fecha=hoy) if AG["h"] is not None else {"entrada": None, "salida": None, "fecha": hoy, "ok": False}
posts = []
def fresh(h, estado):
    for f in Path("/tmp/ag").glob("f.json"): f.unlink()
    F._ST = None; F._save_ok = True
    st = F.load_state(); st["tg_primed"] = True; F.save_state(st); F._ST = None
    F._tg = fake_tg; F.agenda_horario = fake_agenda; F.estado = estado
    F.fichar = lambda st, info: (posts.append(1) or (True, "OK"))
    AG.update(h=h, forzados=0, lanza=False); calls.clear(); posts.clear(); buf.truncate(0); buf.seek(0)
def web_ko(st): raise F.requests.ConnectionError("x " + F.URL_QR)
NO = {"entrada": None, "salida": None, "ok": True}
SI = {"entrada": "09:05", "salida": None, "ok": True}
envios = lambda: [b for m, b in calls if m == "sendMessage"]

fresh(SI, web_ko); F.tick(now, lambda: True)
res(f"(a1) ficha caida + agenda con entrada -> hecho sin preguntar ({len(envios())} envios)",
    not envios() and F._ST["done_date"] == hoy and "hecho según la agenda" in buf.getvalue())
fresh(NO, web_ko); F.tick(now, lambda: True)
t = envios()[0]["text"] if envios() else ""
res(f"(a2) ficha caida + agenda sin entrada -> pregunta con advertencia ({t.splitlines()[1:3]})",
    len(envios()) == 1 and envios()[0].get("reply_markup") and "No he podido leer la ficha" in t and "Agenda: entrada no disponible" in t)
fresh(SI, lambda st: (False, {"error": "la ficha no muestra el botón de registro, mírala tú", "error_tipo": "botones", "pendientes": []}))
F.tick(now, lambda: True)
res(f"(a3) ficha sin boton + agenda con entrada -> hecho, sin aviso ({len(envios())} envios)", not envios() and F._ST["done_date"] == hoy)
fresh(None, web_ko); F.tick(now, lambda: True)
res(f"(a4) ficha caida y agenda tampoco -> como antes: fallo 1/3, sin pregunta (err_count={F._ST['err_count']})",
    not envios() and F._ST["err_count"] == 1 and F._ST["done_date"] != hoy)
fresh(NO, lambda st: (True, {"error": None, "pendientes": []})); F.tick(now, lambda: True)
av = [b["text"] for b in envios()]
res(f"(b1) ficha hecho + agenda sin hora -> relee la agenda ({AG['forzados']} forzada), WARNING y 1 aviso: {av}",
    AG["forzados"] == 1 and len(av) == 1 and "no coinciden" in av[0] and "ficha=entrada hecha" in av[0]
    and "WARNING fichaje: la ficha y la agenda no coinciden" in buf.getvalue() and F._ST["done_date"] == hoy)
F._comparar_con_agenda(F._ST, hoy, True)
res(f"(b1') una sola vez al dia ({len(envios())} envios)", len(envios()) == 1)
fresh(SI, lambda st: (False, {"error": None, "pendientes": ["1"]})); F.tick(now, lambda: True)
tx = [b["text"] for b in envios()]
res(f"(b2) ficha sin entrada + agenda con entrada -> aviso y pregunta igual (manda la ficha): {len(tx)} envios",
    len(tx) == 2 and "ficha=sin entrada, agenda=entrada 09:05" in tx[0] and "¿Ficho yo" in tx[1] and "Agenda: entrada 09:05" in tx[1])
fresh(NO, lambda st: (False, {"error": None, "pendientes": ["1"]})); F.tick(now, lambda: True)
q = envios()[0]["text"]
res(f"(d) la pregunta lleva la linea de la agenda y no nombres: {q.splitlines()[1:3]}",
    "Agenda: entrada no disponible." in q and "INVENTADO" not in q)
# (c) tras fichar OK, la agenda se consulta de nuevo (forzada) y se anade al mensaje
mid = F._ST["asked_msg_ids"][-1]
AG["h"] = {"entrada": "09:07", "salida": None, "ok": True}; calls.clear(); f0 = AG["forzados"]
F._procesar_callback(F._ST, {"id": "c", "data": "fichar_si", "from": {"first_name": "Tester"},
                            "message": {"message_id": mid, "chat": {"id": "-100"}, "text": q}}, now.replace(minute=5))
ed = [b["text"] for m, b in calls if m == "editMessageText"]
res(f"(c1) Si -> ✅ con 'agenda: entrada 09:07' (forzada={AG['forzados'] - f0}, POST={len(posts)})",
    len(posts) == 1 and "Entrada fichada" in ed[-1] and ed[-1].rstrip().endswith("agenda: entrada 09:07") and AG["forzados"] - f0 == 1)
fresh(NO, lambda st: (False, {"error": None, "pendientes": ["1"]})); F.tick(now, lambda: True)
mid = F._ST["asked_msg_ids"][-1]; AG["lanza"] = True; calls.clear()
F._procesar_callback(F._ST, {"id": "c", "data": "fichar_si", "from": {"first_name": "Tester"},
                            "message": {"message_id": mid, "chat": {"id": "-100"}, "text": "p"}}, now.replace(minute=5))
ed = [b["text"] for m, b in calls if m == "editMessageText"]
res(f"(c2) agenda rota tras fichar -> ✅ igual, sin linea de agenda ({ed[-1].splitlines()[-1][:40]!r})",
    len(posts) == 1 and "Entrada fichada" in ed[-1] and "agenda:" not in ed[-1] and F._ST["done_date"] == hoy)
fresh(NO, lambda st: (False, {"error": None, "pendientes": ["1"]})); AG["lanza"] = True; F.tick(now, lambda: True)
res(f"(e) agenda que lanza en el tick -> la pregunta sale igual ({len(envios())} envio)", len(envios()) == 1 and envios()[0].get("reply_markup"))
