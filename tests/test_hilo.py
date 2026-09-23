"""Pruebas del hilo de escucha (ronda 5). Hora de pregunta = ahora-5 min para que las guardas
(que en el hilo usan la hora real) den la pregunta por vigente."""
import os, sys, logging, threading, time, json
from datetime import datetime, timedelta
from pathlib import Path
ahora = datetime.now()
os.environ.update(FICHAJE_URL="https://127.0.0.1:1/fichajes_padres/?p=SECRETO", FICHAJE_DNI="00000000T",
                  FICHAJE_BOT_TOKEN="123456:FAKE-token", FICHAJE_CHAT_ID="-100", FICHAJE_STATE="/tmp/h/f.json",
                  FICHAJE_HORA=(ahora - timedelta(minutes=5)).strftime("%H:%M"), FICHAJE_HILO="1")
os.makedirs("/tmp/h", exist_ok=True)
class Captura(logging.Handler):
    def __init__(self): super().__init__(); self.recs = []
    def emit(self, r): self.recs.append((r.levelname, r.getMessage()))
cap = Captura(); logging.basicConfig(level=logging.DEBUG, format="  log %(levelname)s %(message)s")
logging.getLogger("fichaje").addHandler(cap)
logging.getLogger("urllib3").setLevel(logging.WARNING)
sys.path.insert(0, "/app")
import fichaje as F, requests
def res(name, ok): print(("PASS " if ok else "FAIL ") + name)
hoy = ahora.strftime("%Y-%m-%d")
calls, posts = [], []
lock_calls = threading.Lock()
UPD = []
def fake_tg(method, _timeout=None, **b):
    with lock_calls: calls.append((method, b, _timeout))
    if method == "getUpdates":
        time.sleep(0.01)
        with lock_calls:
            u, UPD[:] = list(UPD), []
        return u
    if method == "sendMessage": fake_tg.mid += 1; return {"message_id": fake_tg.mid}
    return True
fake_tg.mid = 100
def fresh(**extra):
    for f in Path("/tmp/h").glob("*"): f.unlink()
    F._ST = None; F._save_ok = True; F._hilo = None; F._relanzamientos.clear(); F._parar.clear()
    st = F.load_state(); st.update(tg_primed=True, tg_offset=10, **extra); F.save_state(st); F._ST = None
    calls.clear(); posts.clear(); UPD.clear(); cap.recs.clear()
    F._tg = fake_tg
def cb(data, mid, uid, texto="🚪 Guardería: hoy no hay entrada fichada\n¿Ficho yo la entrada de hoy?"):
    return {"update_id": uid, "callback_query": {"id": f"c{uid}", "data": data, "from": {"first_name": "Tester"},
            "message": {"message_id": mid, "chat": {"id": -100}, "text": texto}}}
def edits(): return [b for m, b, _ in calls if m == "editMessageText"]
F.estado = lambda st: (False, {"error": None, "pendientes": ["1"]})
def fichar_lento(st, info):
    time.sleep(0.05); posts.append(1); return True, "OK"
F.fichar = fichar_lento

# (a) el hilo procesa la pulsacion: edita el mensaje (texto + linea) y quita botones
fresh(test_date=hoy, test_msg_ids=[500])
UPD.append(cb("test_no", 500, 11, texto="🧪 Prueba del bot de fichaje: pulsa un botón; no hace nada real."))
espera = F._escucha_una_vez()
gu = [(b, t) for m, b, t in calls if m == "getUpdates"][0]
e = edits()
res(f"(a1) una vuelta del hilo: long polling timeout={gu[0]['timeout']} read={gu[1][1]}s, allowed={gu[0]['allowed_updates']}",
    gu[0]["timeout"] == 20 and gu[1][1] == 30 and gu[0]["allowed_updates"] == ["callback_query"] and espera == 0)
res(f"(a2) test_no: mensaje editado sin botones: {e[-1]['text']!r}",
    len(e) == 1 and "reply_markup" not in e[-1] and "Prueba del bot" in e[-1]["text"]
    and e[-1]["text"].splitlines()[-1].startswith("→ prueba recibida: No (Tester) · ") and not posts)
fresh(asked_date=hoy, asked_msg_ids=[101])
UPD.append(cb("fichar_no", 101, 11)); F._escucha_una_vez()
res(f"(a3) fichar_no: {edits()[-1]['text'].splitlines()[-1]!r}", edits()[-1]["text"].splitlines()[-1].startswith("→ No, hoy no (Tester) · ") and not posts)
fresh(asked_date=hoy, asked_msg_ids=[101])
UPD.append(cb("fichar_si", 101, 11)); F._escucha_una_vez()
t = [x["text"] for x in edits()]
res(f"(a4) fichar_si: primero '→ Sí … ⏳ fichando…', luego el resultado ({[x.splitlines()[-1] for x in t]})",
    len(t) == 2 and "→ Sí (Tester) · " in t[0] and t[0].endswith("⏳ fichando…") and "→ Sí (Tester)" in t[1]
    and "Entrada fichada" in t[1] and len(posts) == 1)
# answerCallbackQuery caducado -> debug, no warning
fresh(test_date=hoy, test_msg_ids=[500])
def tg_viejo(method, _timeout=None, **b):
    if method == "answerCallbackQuery":
        r = requests.models.Response(); r.status_code = 400
        r._content = b'{"ok":false,"description":"Bad Request: query is too old and response timeout expired or query ID is invalid"}'
        raise requests.HTTPError("400", response=r)
    return fake_tg(method, _timeout, **b)
F._tg = tg_viejo
UPD.append(cb("test_si", 500, 11)); F._escucha_una_vez()
nivel = [lv for lv, m in cap.recs if "answerCallbackQuery" in m]
res(f"(a5) answerCallbackQuery 400 'too old' -> {nivel}, y el mensaje se edita igual", nivel == ["DEBUG"] and len(edits()) == 1)

# (b) carrera hilo/tick con el lock: tick pregunta y recuerda mientras el hilo procesa el Si
fresh()
F.estado = lambda st: (time.sleep(0.03), (False, {"error": None, "pendientes": ["1"]}))[1]
errores = []
ahora_t = datetime.now()
F.tick(ahora_t, lambda: True)                 # pregunta (msg 101) y arranca el hilo real
vivo = F._hilo_vivo()
with lock_calls: UPD.append(cb("fichar_si", 101, 11)); UPD.append(cb("fichar_si", 101, 12))
def ticks():
    try:
        for k in range(200):
            F.tick(ahora_t + timedelta(minutes=k % 60), lambda: True)
    except Exception as ex:
        errores.append(repr(ex))
hs = [threading.Thread(target=ticks) for _ in range(2)]
[h.start() for h in hs]; [h.join() for h in hs]
for _ in range(100):
    if F._ST.get("done_date") == hoy: break
    time.sleep(0.05)
F._parar.set(); F._hilo.join(timeout=25)
st = F._ST
preguntas = sum(1 for m, b, _ in calls if m == "sendMessage" and b.get("reply_markup"))
n_antes = preguntas
for k in range(5): F.tick(ahora_t + timedelta(minutes=40 + k), lambda: True)
tras = sum(1 for m, b, _ in calls if m == "sendMessage" and b.get("reply_markup")) - n_antes
res(f"(b2) tras el Si no sale ninguna pregunta mas ({tras})", tras == 0)
inesperados = [m for lv, m in cap.recs if "inesperado" in m or "procesando un boton" in m]
disco = json.loads(Path("/tmp/h/f.json").read_text())
res(f"(b) carrera: hilo vivo={vivo}, POSTs={len(posts)}, preguntas (pregunta+recordatorio, tope 2)={preguntas}, errores={errores + inesperados}, "
    f"answer={st['answer']} done={st['done_date']==hoy} si_pendiente={st['si_pendiente']} offset={st['tg_offset']}, disco coherente={disco['answer']=='si' and disco['tg_offset']==12}",
    vivo and len(posts) == 1 and preguntas <= 2 and not errores and not inesperados and st["answer"] == "si"
    and st["done_date"] == hoy and not st["si_pendiente"] and st["tg_offset"] == 12 and disco["answer"] == "si" and disco["tg_offset"] == 12)

# (c) hilo muerto: tick lo relanza, maximo 3 por hora; despues, tick lee los botones el mismo
fresh(asked_date=hoy, reminded_date=hoy, answer="no", answer_date=hoy)   # nada que decidir
lanzados = []
def arranca_muerto():
    lanzados.append(1)
    F._hilo = threading.Thread(target=lambda: None); F._hilo.start(); F._hilo.join()
F._arrancar_hilo = arranca_muerto
t0 = datetime.now()
for k in range(6):
    F.tick(t0 + timedelta(minutes=k), lambda: True)
avisos = [m for lv, m in cap.recs if lv == "WARNING" and "hilo de botones" in m]
gu_tick = [b for m, b, _ in calls if m == "getUpdates" and b["timeout"] == 0]
res(f"(c1) arranque + 3 relanzamientos en la hora, luego no ({len(lanzados)} arranques, {len(avisos)} avisos; polls desde tick={len(gu_tick)})",
    len(lanzados) == 4 and len(F._relanzamientos) == 3 and len(gu_tick) >= 2)
F.tick(t0 + timedelta(minutes=70), lambda: True)
res(f"(c2) pasada la hora se puede relanzar otra vez ({len(lanzados)} arranques)", len(lanzados) == 5)

# (d) 409 no tumba el hilo; errores de red con backoff 5->60
import importlib
fresh()
def tg_409(method, _timeout=None, **b):
    if method == "getUpdates":
        r = requests.models.Response(); r.status_code = 409
        raise requests.HTTPError("409 Conflict: terminated by other getUpdates request", response=r)
    return fake_tg(method, _timeout, **b)
F._tg = tg_409
esp = F._escucha_una_vez()
w = [m for lv, m in cap.recs if lv == "WARNING" and "409" in m]
res(f"(d1) 409 -> espera {esp} s y aviso: {w[:1]}", esp == 30 and len(w) == 1)
F._arrancar_hilo = importlib.reload(F)._arrancar_hilo if False else F._arrancar_hilo
F._parar.clear()
real = threading.Thread(target=F._bucle_escucha, daemon=True); F._hilo = real; real.start(); time.sleep(0.3)
res(f"(d2) hilo real con 409: sigue vivo tras el error ({real.is_alive()})", real.is_alive())
F._parar.set(); real.join(timeout=5)
res(f"(d3) y se para limpio con _parar ({not real.is_alive()})", not real.is_alive())
def tg_red(method, _timeout=None, **b):
    if method == "getUpdates": raise requests.ConnectionError("x https://api.telegram.org/bot123456:FAKE-token/getUpdates")
    return fake_tg(method, _timeout, **b)
F._tg = tg_red; F._escucha_una_vez.backoff = 5
serie = [F._escucha_una_vez() for _ in range(6)]
F._tg = fake_tg; ok = F._escucha_una_vez()
fuga = any("FAKE-token" in m or "SECRETO" in m for lv, m in cap.recs)
res(f"(d4) red caida: backoff {serie}, al volver {ok} y backoff reiniciado a {F._escucha_una_vez.backoff}; sin token en log={not fuga}",
    serie == [5, 10, 20, 40, 60, 60] and ok == 0 and F._escucha_una_vez.backoff == 5 and not fuga)
