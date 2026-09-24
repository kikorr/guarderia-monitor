"""Recordatorio de SALIDA con pregunta (nunca automatico), revalidacion antes de fichar (entrada y
salida) y entrada con data-p3 cualquiera. Sin red, datos inventados."""
import os, sys, logging, io
from datetime import datetime, timedelta
from pathlib import Path
os.environ.update(FICHAJE_URL="https://127.0.0.1:1/fichajes_padres/?p=SECRETO", FICHAJE_DNI="00000000T",
                  FICHAJE_BOT_TOKEN="123456:FAKE-token", FICHAJE_CHAT_ID="-100", FICHAJE_STATE="/tmp/sa/f.json",
                  FICHAJE_HORA="09:00", FICHAJE_HILO="0")
os.environ.pop("FICHAJE_HORA_SALIDA", None)        # sin definir -> 16:45 por defecto
os.makedirs("/tmp/sa", exist_ok=True)
sys.path.insert(0, "/app"); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
buf = io.StringIO()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", handlers=[logging.StreamHandler(buf)])
import requests, subprocess
import fichaje as F
from fixture import ficha
def res(n, ok): print(("PASS " if ok else "FAIL ") + n)
res(f"(0) FICHAJE_HORA_SALIDA sin definir -> {F.HORA_SALIDA}", F.HORA_SALIDA == "16:45")

base = datetime.now().replace(second=0, microsecond=0)
hoy = base.strftime("%Y-%m-%d")
T = lambda h, m=0: base.replace(hour=h, minute=m)
calls = []
def fake_tg(method, _timeout=None, **b):
    calls.append((method, b))
    if method == "getUpdates": return []
    if method == "sendMessage": fake_tg.mid += 1; return {"message_id": fake_tg.mid}
    return True
fake_tg.mid = 100

class Web:
    """Ficha 'antes' hasta un POST OK (o hasta que alguien ficha en la puerta: .puerta()); luego 'despues'."""
    def __init__(self, antes, despues=None, p3="1", desc="Registro realizado", resultado="OK"):
        self.antes, self.despues, self.p3, self.desc, self.resultado = antes, despues, p3, desc, resultado
        self.posts, self.hecho, self.estados, self.falla = [], False, 0, 0
    def puerta(self): self.hecho = True
    def estado(self, st):
        self.estados += 1
        if self.falla:
            self.falla -= 1
            raise requests.ConnectionError("x " + F.URL_QR)
        ninos = self.despues if (self.hecho and self.despues is not None) else self.antes
        info = dict(F._parse_ficha(ficha(ninos, p3=self.p3)), centro="C1")
        return info["hecho"] and not info["error"], info
    def post(self, url, files=None, **k):           # asignado como metodo ligado: no recibe la Session
        self.posts.append([(n, v[1]) for n, v in files])
        self.hecho = self.resultado == "OK"
        desc, resultado = self.desc, self.resultado
        class R:
            status_code = 200
            def json(self): return {"Resultado": resultado, "Descripcion": desc}
        return R()
AG = {"h": {"entrada": "09:15", "salida": "16:47", "ok": True}}
FICHAR_REAL = F.fichar
def fresh(web, hora="16:45", entrada_hecha=True):
    for f in Path("/tmp/sa").glob("f.json"): f.unlink()
    F._ST = None; F._save_ok = True
    F.HORA_SALIDA = hora; F.HH_S, F.MM_S = F._hora_valida(hora) if hora else (None, None)
    st = F.load_state(); st["tg_primed"] = True
    if entrada_hecha: st.update(done_date=hoy, asked_date=hoy)
    F.save_state(st); F._ST = None
    F._tg = fake_tg; F.estado = web.estado; F.fichar = FICHAR_REAL
    requests.Session.post = web.post
    F.agenda_horario = lambda forzar=False: dict(AG["h"], fecha=hoy)
    calls.clear(); buf.truncate(0); buf.seek(0)
def ticks(desde=(16, 30), hasta=(20, 0), paso=5, lectivo=True):
    t, fin = T(*desde), T(*hasta)
    while t < fin:
        F.tick(t, lambda: lectivo); t += timedelta(minutes=paso)
preguntas = lambda: [b for m, b in calls if m == "sendMessage" and b.get("reply_markup")]
edits = lambda: [b["text"] for m, b in calls if m == "editMessageText"]
answers = lambda: [b["text"] for m, b in calls if m == "answerCallbackQuery"]
def pulsa(data, mid, t, n="1"):
    F._procesar_callback(F._ST, {"id": "c" + n, "data": data, "from": {"first_name": "Tester"},
                                 "message": {"message_id": mid, "chat": {"id": "-100"}, "text": "pregunta"}}, t)
ENTRADA = [{"id": "4101", "entrada": "09:15"}]
SALIDA = [{"id": "4101", "entrada": "09:15", "salida": "16:47"}]

# (i) 16:45 con entrada y sin salida -> pregunta; Si -> revalida -> 1 POST tipo=data-p3 -> hora de salida
w = Web(ENTRADA, SALIDA, p3="1"); fresh(w); ticks(hasta=(16, 50))
p = preguntas()
datos = [x["callback_data"] for x in p[0]["reply_markup"]["inline_keyboard"][0]] if p else []
res(f"(i) pregunta a las 16:45, sin POST ({p[0]['text'] if p else None!r}; botones {datos})",
    len(p) == 1 and "hay entrada (09:15) y aún no hay salida fichada" in p[0]["text"] and "¿La ficho?" in p[0]["text"]
    and datos == ["salida_si", "salida_no"] and not w.posts)
e0 = w.estados; pulsa("salida_si", F._ST["salida_msg_ids"][-1], T(16, 50))
res(f"(i') Si -> revalida ({w.estados - e0} lecturas: antes y despues del POST), 1 POST {w.posts}, y {edits()[-1].splitlines()[-1]!r}",
    w.estados - e0 == 2 and len(w.posts) == 1 and w.posts[0] == [("chk_4101", "4101"), ("padre", "P1"), ("idCentro", "C1"), ("tipo", "1")]
    and edits()[-1].splitlines()[-1] == "✅ <b>Salida fichada a las 16:47</b> (Tester dijo sí) · agenda: salida 16:47"
    and F._ST["salida_done_date"] == hoy)
ticks(desde=(16, 50))
res(f"(i'') despues, ni mas preguntas ni mas POST ({len(preguntas())} pregunta, {len(w.posts)} POST)", len(preguntas()) == 1 and len(w.posts) == 1)

# (ii) Si, pero al revalidar ya hay salida (alguien la ficho en la puerta) -> 0 POST, «ya constaba»
w = Web(ENTRADA, SALIDA); fresh(w); ticks(hasta=(16, 50)); w.puerta()
pulsa("salida_si", F._ST["salida_msg_ids"][-1], T(16, 55))
res(f"(ii) revalidacion con salida ya hecha -> 0 POST y {edits()[-1].splitlines()[-1]!r}",
    not w.posts and edits()[-1].splitlines()[-1].startswith("✅ Ya constaba la salida a las 16:47 (alguien la fichó); no hago nada")
    and F._ST["salida_done_date"] == hoy and not F._ST["si_salida_pendiente"])

# (iii) lo mismo con la ENTRADA: Si de la mañana, al revalidar ya hay entrada -> 0 POST
w = Web([{"id": "4101"}], ENTRADA); fresh(w, hora="", entrada_hecha=False); F.tick(T(9, 0), lambda: True); w.puerta()
pulsa("fichar_si", F._ST["asked_msg_ids"][-1], T(9, 5))
res(f"(iii) entrada: revalidacion con entrada ya hecha -> 0 POST y {edits()[-1].splitlines()[-1]!r}",
    not w.posts and edits()[-1].splitlines()[-1].startswith("✅ Ya constaba la entrada a las 09:15 (alguien la fichó); no hago nada")
    and F._ST["done_date"] == hoy and not F._ST["si_pendiente"])

# (iv) sin entrada ese dia -> no pregunta
w = Web([{"id": "4101"}]); fresh(w); AG["h"] = {"entrada": None, "salida": None, "ok": True}; ticks()
res(f"(iv) sin entrada (y la agenda tampoco) -> no pregunta; ficha cada 60 min: 3 lecturas en la ventana ({w.estados})",
    not preguntas() and not w.posts and w.estados == 3 and "hoy aún no hay entrada" in buf.getvalue()
    and "la agenda sigue sin entrada" in buf.getvalue())
AG["h"] = {"entrada": "09:15", "salida": "16:47", "ok": True}

# (v) salida ya hecha -> no pregunta
w = Web([{"id": "4101", "entrada": "09:15", "salida": "16:20", "disabled": True}]); fresh(w); ticks()
res("(v) salida ya hecha -> no pregunta", not preguntas() and not w.posts and "ya estaba registrada" in buf.getvalue())

# (vi) la revalidacion falla (web caida) -> no POST, reintento a los 10 min con tope
w = Web(ENTRADA, SALIDA); fresh(w); ticks(hasta=(16, 50)); w.falla = 2
pulsa("salida_si", F._ST["salida_msg_ids"][-1], T(16, 50)); n_tras_si = len(w.posts)
ticks(desde=(16, 51), hasta=(17, 30), paso=1)
res(f"(vi) 2 fallos al revalidar -> 0 POST mientras no se lee; al 3.er intento ficha ({n_tras_si} tras el Si, {len(w.posts)} al final; {[e.splitlines()[-1][:45] for e in edits()]})",
    n_tras_si == 0 and len(w.posts) == 1 and any("Aún no he podido fichar la salida" in e for e in edits()) and F._ST["salida_done_date"] == hoy)
w = Web(ENTRADA, SALIDA); fresh(w); ticks(hasta=(16, 50)); w.falla = 99
pulsa("salida_si", F._ST["salida_msg_ids"][-1], T(16, 50)); ticks(desde=(16, 51), hasta=(18, 0), paso=1)
av = [b["text"] for m, b in calls if m == "sendMessage" and not b.get("reply_markup")]
res(f"(vi') siempre caida -> 0 POST, 3 intentos y aviso al rendirse ({av})",
    not w.posts and len(av) == 1 and "no he podido fichar la salida tras 3 intentos" in av[0] and not F._ST["si_salida_pendiente"])

# (vii) FICHAJE_HORA_SALIDA vacia -> nada
w = Web(ENTRADA, SALIDA); fresh(w, hora=""); ticks()
res("(vii) FICHAJE_HORA_SALIDA vacia -> 0 lecturas, sin pregunta", w.estados == 0 and not preguntas())
o = subprocess.run([sys.executable, "-c", "import sys,logging;logging.basicConfig(level=logging.ERROR,format='%(levelname)s %(message)s');"
                    "sys.path.insert(0,'/app');import fichaje as F;print('SAL',repr(F.HORA_SALIDA))"],
                   env=dict(os.environ, FICHAJE_HORA_SALIDA=""), capture_output=True, text=True)
o2 = subprocess.run([sys.executable, "-c", "import sys,logging;logging.basicConfig(level=logging.ERROR,format='%(levelname)s %(message)s');"
                     "sys.path.insert(0,'/app');import fichaje as F;print('SAL',repr(F.HORA_SALIDA))"],
                    env=dict(os.environ, FICHAJE_HORA_SALIDA="25:99"), capture_output=True, text=True)
res(f"(vii') definida vacia -> desactivada ({o.stdout.strip()}); mal escrita -> 16:45 con error ({o2.stdout.strip()})",
    "SAL ''" in o.stdout and "SAL '16:45'" in o2.stdout and "ERROR" in o2.stderr)

# (viii) dia no lectivo o cerrado -> nada
w = Web(ENTRADA, SALIDA); fresh(w); ticks(lectivo=False)
res("(viii) dia no lectivo -> 0 lecturas, sin pregunta", w.estados == 0 and not preguntas())
w = Web(ENTRADA, SALIDA); fresh(w); F.DIAS_CERRADO = {hoy}; ticks(); F.DIAS_CERRADO = set()
res("(viii') dia cerrado -> sin pregunta", w.estados == 0 and not preguntas())

# (ix) la entrada sigue igual y no exige tipo_web==1 (data-p3="2")
w = Web([{"id": "4101"}], ENTRADA, p3="2"); fresh(w, hora="", entrada_hecha=False); F.tick(T(9, 0), lambda: True)
pulsa("fichar_si", F._ST["asked_msg_ids"][-1], T(9, 5))
res(f"(ix) entrada con data-p3=2: 1 POST con tipo=2 y entrada comprobada ({w.posts[0][-1] if w.posts else None}; {edits()[-1].splitlines()[-1]!r})",
    len(w.posts) == 1 and w.posts[0][-1] == ("tipo", "2")
    and edits()[-1].splitlines()[-1] == "✅ <b>Entrada fichada a las 09:15</b> (Tester dijo sí) · agenda: entrada 09:15"
    and F._ST["done_date"] == hoy)

# (x) No -> «Vale, hoy no se ficha la salida» y no vuelve a preguntar
w = Web(ENTRADA, SALIDA); fresh(w); ticks(hasta=(16, 50))
pulsa("salida_no", F._ST["salida_msg_ids"][-1], T(16, 50)); ticks(desde=(16, 50))
res(f"(x) No -> {answers()[-1]!r}, {edits()[-1].splitlines()[-1][:22]!r}, 1 sola pregunta y 0 POST",
    answers()[-1] == "Vale, hoy no se ficha la salida." and edits()[-1].splitlines()[-1].startswith("→ No, hoy no (Tester)")
    and len(preguntas()) == 1 and not w.posts)

# (xi) sin respuesta -> un recordatorio a los 30 min; maximo 2 preguntas; caduca a las 3 h
w = Web(ENTRADA, SALIDA); fresh(w); ticks(hasta=(20, 30))
p = preguntas()
res(f"(xi) sin respuesta: {len(p)} preguntas (la 2.ª es recordatorio) y 0 POST", len(p) == 2 and "recordatorio" in p[1]["text"] and not w.posts)
pulsa("salida_si", F._ST["salida_msg_ids"][-1], T(19, 50))
res("(xi') un Si pasadas las 3 h -> caducada, 0 POST", not w.posts and answers()[-1] == "Pregunta caducada")
# (xii) si la ficharon en la puerta antes del recordatorio, no se recuerda
w = Web(ENTRADA, SALIDA); fresh(w); ticks(hasta=(17, 0)); w.puerta(); ticks(desde=(17, 0))
res(f"(xii) salida hecha en la puerta antes del recordatorio -> sin recordatorio ({len(preguntas())} pregunta)",
    len(preguntas()) == 1 and F._ST["salida_done_date"] == hoy)


# ══ Ronda 10 ══════════════════════════════════════════════════════════════════
# (r2a) recordatorio de ENTRADA: si ya la ficharon en la puerta, se calla (relee la ficha)
w = Web([{"id": "4101"}], ENTRADA); fresh(w, hora="", entrada_hecha=False); F.tick(T(9, 0), lambda: True); w.puerta()
ticks(desde=(9, 1), hasta=(10, 0))
res(f"(r2a) entrada fichada en la puerta antes del recordatorio -> sin recordatorio ({len(preguntas())} pregunta)",
    len(preguntas()) == 1 and F._ST["done_date"] == hoy and "no recuerdo" in buf.getvalue()
    and any(m == "editMessageReplyMarkup" for m, b in calls))
# (r2b) recordatorio de ENTRADA con la ficha caida -> no recuerda a ciegas; reintenta a los 10 min
w = Web([{"id": "4101"}], ENTRADA); fresh(w, hora="", entrada_hecha=False); F.tick(T(9, 0), lambda: True)
w.falla = 1; ticks(desde=(9, 1), hasta=(10, 0), paso=1)
p = preguntas()
res(f"(r2b) entrada: relectura caida a las 9:30 -> nada; a las 9:40 recuerda ({len(p)} preguntas, err_recordatorio={F._ST['err_recordatorio']}, err_count={F._ST['err_count']})",
    len(p) == 2 and "recordatorio" in p[1]["text"] and F._ST["err_recordatorio"] == 1 and F._ST["err_count"] == 0)
# (r2c) recordatorio de SALIDA con la ficha caida -> no recuerda a ciegas; tope 3 y aviso
w = Web(ENTRADA, SALIDA); fresh(w); ticks(hasta=(17, 14), paso=1); w.falla = 99
ticks(desde=(17, 14), hasta=(18, 30), paso=1)
av = [b["text"] for m, b in calls if m == "sendMessage" and not b.get("reply_markup")]
res(f"(r2c) salida: relectura siempre caida -> sin recordatorio, 3 intentos y aviso ({len(preguntas())} pregunta; {av})",
    len(preguntas()) == 1 and len(av) == 1 and "no he podido comprobar la salida" in av[0])
w = Web(ENTRADA, SALIDA); fresh(w); ticks(hasta=(17, 14), paso=1); w.falla = 1
ticks(desde=(17, 14), hasta=(18, 0), paso=1)
p = preguntas()
res(f"(r2c') salida: un fallo al releer -> el recordatorio sale 10 min despues ({len(p)} preguntas)",
    len(p) == 2 and "recordatorio" in p[1]["text"])

# (r3) llegada tardia: a las 16:45 no hay entrada; la agenda la ve a las 17:40 -> se relee la ficha y se pregunta
class Tarde(Web):
    def estado(self, st):
        self.estados += 1
        ninos = ENTRADA if self.hecho else [{"id": "4101"}]
        info = dict(F._parse_ficha(ficha(ninos, p3=self.p3)), centro="C1")
        return info["hecho"], info
w = Tarde([{"id": "4101"}]); fresh(w); AG["h"] = {"entrada": None, "salida": None, "ok": True}
ticks(desde=(16, 30), hasta=(17, 40))
e_antes = w.estados
w.hecho = True; AG["h"] = {"entrada": "17:35", "salida": None, "ok": True}; ticks(desde=(17, 40), hasta=(20, 0))
p = preguntas()
res(f"(r3) llegada tardia: sin tocar la ficha mientras la agenda no tiene entrada ({e_antes} lectura hasta 17:40); luego pregunta ({len(p)})",
    e_antes == 1 and len(p) >= 1 and "hay entrada (09:15)" in p[0]["text"])
AG["h"] = {"entrada": "09:15", "salida": "16:47", "ok": True}
w = Tarde([{"id": "4101"}]); fresh(w); F.agenda_horario = None; ticks(desde=(16, 30), hasta=(21, 0))
res(f"(r3') sin agenda: relee la ficha cada 30 min solo dentro de la ventana ({w.estados} lecturas de 16:45 a 19:45)",
    w.estados == 6 and not preguntas())

# (r4) la Descripcion del servidor no va a Telegram ni al log INFO; estilo unificado
w = Web([{"id": "4101"}], ENTRADA, desc="Registro de PERSONA INVENTADA realizado"); fresh(w, hora="", entrada_hecha=False)
F.tick(T(9, 0), lambda: True); pulsa("fichar_si", F._ST["asked_msg_ids"][-1], T(9, 5))
todo_tg = " ".join(str(b) for m, b in calls)
res(f"(r4) entrada: sin la Descripcion en Telegram ni en el log; {edits()[-1].splitlines()[-1]!r}",
    "PERSONA" not in todo_tg and "PERSONA" not in buf.getvalue()
    and edits()[-1].splitlines()[-1] == "✅ <b>Entrada fichada a las 09:15</b> (Tester dijo sí) · agenda: entrada 09:15")
w = Web(ENTRADA, SALIDA, desc="Salida de PERSONA INVENTADA"); fresh(w); ticks(hasta=(16, 50))
pulsa("salida_si", F._ST["salida_msg_ids"][-1], T(16, 50))
todo_tg = " ".join(str(b) for m, b in calls)
res(f"(r4') salida: igual; {edits()[-1].splitlines()[-1]!r}",
    "PERSONA" not in todo_tg and "PERSONA" not in buf.getvalue()
    and edits()[-1].splitlines()[-1] == "✅ <b>Salida fichada a las 16:47</b> (Tester dijo sí) · agenda: salida 16:47")
F.DEBUG = True
w = Web([{"id": "4101"}], ENTRADA, desc="Registro de PERSONA INVENTADA realizado"); fresh(w, hora="", entrada_hecha=False)
F.tick(T(9, 0), lambda: True); pulsa("fichar_si", F._ST["asked_msg_ids"][-1], T(9, 5)); F.DEBUG = False
res("(r4'') con FICHAJE_DEBUG=1 la Descripcion va solo al log", "PERSONA" in buf.getvalue()
    and "PERSONA" not in " ".join(str(b) for m, b in calls))

# (r5) todos ausentes -> no «ya constaba», sino «hoy constan todos como ausentes»
w = Web([{"id": "4101"}], [{"id": "4101", "ausente": True}]); fresh(w, hora="", entrada_hecha=False)
F.tick(T(9, 0), lambda: True); w.puerta()
pulsa("fichar_si", F._ST["asked_msg_ids"][-1], T(9, 5))
res(f"(r5) todos ausentes al revalidar -> 0 POST y {edits()[-1].splitlines()[-1]!r}",
    not w.posts and edits()[-1].splitlines()[-1] == "ℹ️ Hoy constan todos como ausentes; no hay nada que fichar")
w = Web([{"id": "4101", "ausente": True}]); fresh(w); ticks()
res(f"(r5') salida con todos ausentes -> sin pregunta y una sola lectura ({w.estados})",
    not preguntas() and w.estados == 1 and "todos como ausentes" in buf.getvalue())

# (r6) load_state sanea salida_msg_ids
Path("/tmp/sa/f.json").write_text('{"salida_msg_ids": "basura", "asked_msg_ids": 7}')
st = F.load_state()
res(f"(r6) load_state sanea salida_msg_ids y asked_msg_ids ({st['salida_msg_ids']}, {st['asked_msg_ids']})",
    st["salida_msg_ids"] == [] and st["asked_msg_ids"] == [])


# ══ Ronda 11 ══════════════════════════════════════════════════════════════════
# (q1) Resultado del servidor (texto libre) ni a Telegram ni al log; solo con FICHAJE_DEBUG=1
w = Web(ENTRADA, SALIDA, resultado="KO: PERSONA INVENTADA no autorizada"); fresh(w); ticks(hasta=(16, 50))
pulsa("salida_si", F._ST["salida_msg_ids"][-1], T(16, 50)); ticks(desde=(16, 51), hasta=(17, 40), paso=1)
todo = " ".join(str(b) for m, b in calls) + buf.getvalue()
res(f"(q1) Resultado KO con texto libre: sin el texto en Telegram ni en el log; «la web no lo ha aceptado» ({len(w.posts)} POST)",
    "PERSONA" not in todo and "la web no lo ha aceptado" in todo and len(w.posts) == 3)
F.DEBUG = True
w = Web(ENTRADA, SALIDA, resultado="KO: PERSONA INVENTADA no autorizada"); fresh(w); ticks(hasta=(16, 50))
pulsa("salida_si", F._ST["salida_msg_ids"][-1], T(16, 50)); F.DEBUG = False
res("(q1') con FICHAJE_DEBUG=1 el Resultado va solo al log", "PERSONA" in buf.getvalue()
    and "PERSONA" not in " ".join(str(b) for m, b in calls))

# (q2) la relectura del recordatorio tiene su propio contador (no gasta err_count de la mañana)
w = Web([{"id": "4101"}], ENTRADA); fresh(w, hora="", entrada_hecha=False); w.falla = 2
F.agenda_horario = None                                         # sin agenda: la mañana reintenta la ficha
ticks(desde=(9, 0), hasta=(9, 25), paso=1)                     # 9:00 y 9:10 fallan, 9:20 pregunta
ec = F._ST["err_count"]; w.falla = 1
ticks(desde=(9, 25), hasta=(10, 0), paso=1)                    # 9:30 falla la relectura, 9:40 recuerda
p = preguntas(); av = [b["text"] for m, b in calls if m == "sendMessage" and not b.get("reply_markup")]
res(f"(q2) 2 fallos por la mañana + 1 en la relectura -> recordatorio a las 9:40, sin aviso (err_count={ec}->{F._ST['err_count']}, err_recordatorio={F._ST['err_recordatorio']}, {len(p)} preguntas)",
    ec == 2 and F._ST["err_count"] == 2 and F._ST["err_recordatorio"] == 1 and len(p) == 2 and "recordatorio" in p[1]["text"] and not av)
w = Web([{"id": "4101"}], ENTRADA); fresh(w, hora="", entrada_hecha=False); F.agenda_horario = None
F.tick(T(9, 0), lambda: True); w.falla = 99
ticks(desde=(9, 1), hasta=(11, 0), paso=1)
av = [b["text"] for m, b in calls if m == "sendMessage" and not b.get("reply_markup")]
res(f"(q2') relectura siempre caida -> 3 intentos, WARNING, sin aviso ni recordatorio; la pregunta sigue viva ({len(preguntas())} pregunta, avisos={av})",
    len(preguntas()) == 1 and not av and F._ST["err_recordatorio"] == 3 and "hoy no recuerdo" in buf.getvalue()
    and F._ST["answer"] is None)
w.falla = 0; pulsa("fichar_si", F._ST["asked_msg_ids"][-1], T(11, 0))
res(f"(q2'') ...y un Si posterior ficha ({len(w.posts)} POST)", len(w.posts) == 1 and F._ST["done_date"] == hoy)

# (q3) salida_recheck_at corrupto: load_state lo sanea y el tick no cae en _fallo
Path("/tmp/sa/f.json").write_text('{"salida_recheck_at": "no-es-fecha", "salida_ultima_lectura": 12}')
st = F.load_state()
res(f"(q3) load_state sanea salida_recheck_at/ultima_lectura ({st['salida_recheck_at']}, {st['salida_ultima_lectura']})",
    st["salida_recheck_at"] is None and st["salida_ultima_lectura"] is None)
w = Web(ENTRADA, SALIDA); fresh(w); F._ST = F.load_state(); F._ST.update(tg_primed=True, salida_recheck_at="basura")
F.tick(T(16, 45), lambda: True)
res(f"(q3') valor corrupto en memoria -> se descarta y pregunta, sin fallo (err_salida={F._ST['err_salida']})",
    F._ST["err_salida"] == 0 and len(preguntas()) == 1)

# (q4) llegada tardia: la agenda no veta la ficha; con agenda sin entrada, cada 60 min; con entrada, cada 30
w = Web([{"id": "4101"}]); fresh(w); AG["h"] = {"entrada": None, "salida": None, "ok": True}
ticks(desde=(16, 30), hasta=(20, 0), paso=1)
lect_60 = w.estados
w = Web([{"id": "4101"}]); fresh(w); AG["h"] = {"entrada": "10:00", "salida": None, "ok": True}
ticks(desde=(16, 30), hasta=(20, 0), paso=1)
res(f"(q4) agenda sin entrada -> {lect_60} lecturas (max 3); agenda con entrada -> {w.estados} (cada 30 min)",
    lect_60 == 3 and w.estados == 6)
AG["h"] = {"entrada": "09:15", "salida": "16:47", "ok": True}

# (q5) Si cuando la relectura del recordatorio ya dio la entrada por hecha -> «Ya constaba», 0 POST
w = Web([{"id": "4101"}], ENTRADA); fresh(w, hora="", entrada_hecha=False); F.tick(T(9, 0), lambda: True)
mid = F._ST["asked_msg_ids"][-1]; w.puerta(); ticks(desde=(9, 1), hasta=(9, 35))
pulsa("fichar_si", mid, T(9, 35))
res(f"(q5) Si tras la relectura del recordatorio -> answer {answers()[-1]!r}, 0 POST, {edits()[-1].splitlines()[-1][:62]!r}",
    answers()[-1] == "Ya constaba" and not w.posts
    and edits()[-1].splitlines()[-1].startswith("✅ Ya constaba la entrada a las 09:15 (alguien la fichó); no hago nada")
    and F._ST["answer"] == "si" and not F._ST["si_pendiente"])
pulsa("fichar_si", mid, T(9, 36), "2")
res("(q5') un segundo toque -> caducada", answers()[-1] == "Pregunta caducada" and not w.posts)
