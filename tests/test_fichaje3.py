"""Disco roto, secretos ilegibles, WORK_HOUR, reintentos y Si pendiente (sin red)."""
import os, sys, logging, json, subprocess, time
from pathlib import Path
from datetime import datetime, timedelta
os.environ.update(FICHAJE_URL="https://127.0.0.1:1/fichajes_padres/?p=SECRETO", FICHAJE_DNI="00000000T",
                  FICHAJE_BOT_TOKEN="123456:FAKE-token", FICHAJE_CHAT_ID="-100", FICHAJE_STATE="/tmp/g/f.json",
                  FICHAJE_HORA="09:00")
os.makedirs("/tmp/g", exist_ok=True)
logging.basicConfig(level=logging.INFO, format="  log %(levelname)s %(message)s")
sys.path.insert(0, "/app")
import fichaje as F
def res(name, ok): print(("PASS " if ok else "FAIL ") + name)
now = datetime.now().replace(hour=9, minute=5, second=0, microsecond=0)
hoy = now.strftime("%Y-%m-%d")
calls, fichados = [], []
SI_UPD = []
def fake_tg(method, _timeout=None, **b):
    calls.append((method, b))
    if method == "getUpdates": return list(SI_UPD)
    if method == "sendMessage": fake_tg.mid += 1; return {"message_id": fake_tg.mid}
    return True
fake_tg.mid = 100
def fresh():
    for f in Path("/tmp/g").glob("*"): f.unlink()
    F.STATE_FILE = Path("/tmp/g/f.json"); F._ST = None; F._save_ok = True
    st = F.load_state(); st["tg_primed"] = True; F.save_state(st); F._ST = None
    calls.clear(); fichados.clear(); SI_UPD.clear()
F._tg = fake_tg
F.fichar = lambda st, info: (fichados.append(1) or (True, "OK"))
F.estado = lambda st: (False, {"error": None, "pendientes": ["1"]})
at = lambda m: now.replace(minute=0) + timedelta(minutes=m)

# (9) MEDIA-A + ronda 3 MEDIA-1: disco roto en el Si -> no ficha; al volver el disco, Telegram reentrega y ficha 1 vez
fresh()
F.tick(at(1), lambda: True)
mid = F._ST["asked_msg_ids"][-1]
SI_UPD.append({"update_id": 50, "callback_query": {"id": "c", "data": "fichar_si", "from": {"first_name": "K"},
                                                   "message": {"message_id": mid, "chat": {"id": "-100"}}}})
F.STATE_FILE = Path("/proc/no/existe/f.json")
for m in range(2, 10):
    F.tick(at(m), lambda: True)
ans = [b["text"] for c, b in calls if c == "answerCallbackQuery"]
res(f"(9a) disco roto en el Si: NO ficha, contesta que lo reintenta, no confirma offset (fichados={len(fichados)}, answers={ans}, offset={F._ST['tg_offset']})",
    len(fichados) == 0 and F._ST["answer"] is None and not F._save_ok and ans[:1] == ["No puedo guardar el estado, no ficho; lo reintento cuando pueda."]
    and F._ST["tg_offset"] < 50)
F.STATE_FILE = Path("/tmp/g/f.json")
for m in range(10, 14):
    F.tick(at(m), lambda: True)
res(f"(9b) disco vuelve: Telegram reentrega el Si y ficha 1 vez (fichados={len(fichados)}), estado guardado (answer={json.loads(Path('/tmp/g/f.json').read_text())['answer']})",
    len(fichados) == 1 and F._save_ok and json.loads(Path('/tmp/g/f.json').read_text())["done_date"] == hoy)

# (10) MEDIA-B
code = ("import os,sys,logging;logging.basicConfig(level=logging.ERROR,format='  log %(levelname)s %(message)s');"
        "sys.path.insert(0,'/app');import fichaje as F;print('  ENABLED',F.ENABLED,'REC',F.RECORDATORIO_MIN,'THREAD',repr(F.THREAD_ID),'STATE',F.STATE_FILE)")
env = dict(os.environ, FICHAJE_DNI_FILE="/", FICHAJE_RECORDATORIO_MIN="abc", FICHAJE_THREAD="tema",
           FICHAJE_HORA="nueve", FICHAJE_STATE="", FICHAJE_DIAS_CERRADO="2026-13,x", FICHAJE_COOKIES_EXTRA=";;=;a")
r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
print(r.stdout + r.stderr, end="")
res("(10a) DNI_FILE ilegible y valores basura: importa, ENABLED=False", r.returncode == 0 and "ENABLED False" in r.stdout)
env = dict(os.environ, FICHAJE_DNI="99999999R", FICHAJE_DNI_FILE="/tmp/g/dni_vacio"); Path("/tmp/g/dni_vacio").write_text("")
r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
res("(10b) _FILE manda sobre la variable (fichero vacio -> desactivado)", "ENABLED False" in r.stdout)
Path("/tmp/g/dni_vacio").unlink()

# (11) WORK_HOUR
for a, b in (("7:00", "17"), ("18", "9"), ("8", "16")):
    code2 = ("import logging,sys;logging.basicConfig(level=logging.ERROR,format='  log %(levelname)s %(message)s');"
             "sys.path.insert(0,'/app');import monitor;print('  ->',monitor.WORK_HOUR_START,monitor.WORK_HOUR_END)")
    env = dict(os.environ, WORK_HOUR_START=a, WORK_HOUR_END=b, TG_BOT_TOKEN="x", TG_CHAT_ID="1", WL_USER="x", WL_PASS="x")
    r = subprocess.run([sys.executable, "-c", code2], env=env, capture_output=True, text=True, cwd="/tmp")
    esperado = "-> 8 16" if a == "8" else "-> 7 17"
    res(f"(11) WORK_HOUR {a}/{b} {esperado}", r.returncode == 0 and esperado in r.stdout)

# (12) reintentos de la web
fresh()
seq = [(False, {"error": "la web sigue pidiendo el DNI", "error_tipo": "dni"}), (False, {"error": None, "pendientes": ["1"]})]
F.estado = lambda st: seq.pop(0) if seq else (False, {"error": None, "pendientes": ["1"]})
for m in range(0, 25):
    F.tick(at(m), lambda: True)
sends = [b["text"][:50] for c, b in calls if c == "sendMessage"]
res(f"(12a) DNI transitorio: 1 fallo, pregunta a los 10 min, sin aviso ({len(sends)} envio)",
    len(sends) == 1 and "entrada fichada" in sends[0] and F._ST["err_count"] == 1)
fresh()
def web_ko(st): raise F.requests.ConnectionError("x " + F.URL_QR)
F.estado = web_ko
for m in range(0, 40):
    F.tick(at(m), lambda: True)
sends = [b["text"] for c, b in calls if c == "sendMessage"]
res(f"(12b) web caida: 3 intentos, 1 aviso al tercero, sin pregunta ni recordatorio ({sends})",
    len(sends) == 1 and "tras 3 intentos" in sends[0] and "SECRETO" not in sends[0] and F._ST["reminded_date"] == hoy)
fresh()
F.estado = lambda st: (False, {"error": "la ficha no muestra el botón de registro, mírala tú", "error_tipo": "botones"})
for m in range(0, 40):
    F.tick(at(m), lambda: True)
sends = [b["text"] for c, b in calls if c == "sendMessage"]
res(f"(12c) sin boton: aviso y dia marcado al primer intento ({len(sends)} envio)", len(sends) == 1 and "botón" in sends[0])

# (13) Si pendiente tras reinicio
fresh()
st = F.load_state()
st.update(asked_date=hoy, asked_msg_ids=[7], answer="si", answer_date=hoy, si_pendiente=True, si_msg_id=7, si_quien="K")
F.save_state(st); F._ST = None
F.estado = lambda st: (False, {"error": None, "pendientes": ["1"]})
for m in range(20, 30):
    F.tick(at(m), lambda: True)
res(f"(13a) Si pendiente tras reinicio: ficha 1 vez (fichados={len(fichados)})",
    len(fichados) == 1 and F._ST["done_date"] == hoy and not F._ST["si_pendiente"])
fresh()
st = F.load_state()
st.update(asked_date=hoy, asked_msg_ids=[7], answer="si", answer_date=hoy, si_pendiente=True, si_msg_id=7, si_quien="K")
F.save_state(st); F._ST = None
F.fichar = lambda st, info: (fichados.append(1) or (False, "KO del servidor"))
for m in range(20, 80):
    F.tick(at(m), lambda: True)
edits = [b["text"][:40] for c, b in calls if c == "editMessageText"]
res(f"(13b) Si que siempre falla: 3 intentos y se rinde (intentos={len(fichados)}, edits={edits})",
    len(fichados) == 3 and not F._ST["si_pendiente"] and F._ST["done_date"] != hoy)

# (14) test-bot desde otro proceso
F.fichar = lambda st, info: (fichados.append(1) or (True, "OK"))
fresh(); F.tick(at(1), lambda: True)
time.sleep(0.01)
d = json.loads(Path("/tmp/g/f.json").read_text()); d.update(test_date=hoy, test_msg_ids=[4242]); Path("/tmp/g/f.json").write_text(json.dumps(d))
SI_UPD.append({"update_id": 99, "callback_query": {"id": "t", "data": "test_si", "from": {"first_name": "K"},
                                                   "message": {"message_id": 4242, "chat": {"id": "-100"}}}})
calls.clear(); F.tick(at(2), lambda: True)
ans = [b["text"] for c, b in calls if c == "answerCallbackQuery"]
res(f"(14) test-bot externo reconocido y sin fichar ({ans})", ans == ["Prueba recibida, no hago nada."] and not fichados)
