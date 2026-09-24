"""fichaje.py — fichaje de ENTRADA en la guarderia (Work and Life) con bot de Telegram propio.

Por que existe (23-sep-2026): la agenda del dia solo se desbloquea cuando un padre ficha
desde la web de fichajes al dejar al nino. Si se olvida, el monitor no recibe nada en
todo el dia. Decision de diseno: a la hora FICHAJE_HORA de un dia lectivo, si no hay
entrada registrada, se pregunta por Telegram con botones Si/No y, solo si dice Si, el
monitor ficha la entrada. Nunca ficha sin pregunta: un dia de enfermedad o vacaciones
NO debe registrar una entrada.

Como funciona la web (medido con el enlace del QR, en solo lectura):
  - GET  {URL_QR}                                 -> sesion (cookie); el HTML dice centro id y coordenadas
  - POST pages/compruebaUser.php   id=<centro>     -> formulario de DNI (o, con cookie, la ficha del padre)
  - POST pages/compruebaPadre.php  dni=..&idCentro -> ficha: un bloque por nino (.cont_hijos con su
                                                      .chk_alu y el texto "Entrada: HH:MM"/"Salida: HH:MM")
                                                      y un unico boton #btn_alu (padre, centro, tipo_web)
  - POST actions/hacer_fichaje.php (multipart: chk_<id>=<idAlumno> de los ninos + padre, idCentro, tipo=1)
    -> JSON {"Resultado": "OK"|..., "Descripcion": "..."}
  La comprobacion de distancia la hace SOLO el navegador (JavaScript); el servidor no
  recibe coordenadas. Por eso aqui no hay geolocalizacion que simular.
  La ficha real se vio el 23-sep-2026 (con entrada y salida ya hechas) y _parse_ficha sigue esa
  estructura; el caso "sin entrada todavia" (sin el <li>Entrada:>) y el tipo_web que trae el
  boton por la manana son suposiciones razonables, no vistas. Ante cualquier duda NO ficha y avisa.
  Nunca se guardan ni se envian nombres: solo ids, horas y el numero de ninos.

Reglas de seguridad (revision 23-sep-2026):
  - Un "Si" solo vale si responde a una pregunta de HOY (message_id en asked_msg_ids),
    sin respuesta previa y dentro de las 3 h siguientes a FICHAJE_HORA. Si no: "caducada".
  - Al arrancar por primera vez se descartan los botones pendientes en Telegram.
  - Nunca se interpola str(e) en logs ni mensajes: la URL del QR lleva la sesion en ?p=
    y la del bot lleva el token. Se usa _err(e).
  - fichaje.json guarda cookies de sesion: se escribe con permisos 0600.

Secretos (Docker secrets, nunca en el repo): la URL del QR con la sesion del padre/madre dentro,
el DNI y, opcionalmente, un token de bot aparte (por defecto se usa el bot del monitor,
TG_BOT_TOKEN). Ese bot no puede ser uno que otro proceso ya escuche (el de HA): Telegram solo
admite un oyente (getUpdates) por bot.

Estado en /data/fichaje.json: cookies de la web, offset de Telegram, fechas de
pregunta/respuesta/fichaje. Todo lo importante se registra en el log del monitor.
"""
import html as _html
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("fichaje")


def _env_or_file(name, default=""):
    """Misma prioridad que env_or_file() de monitor.py: si existe {NAME}_FILE (Docker secret)
    manda el fichero, aunque este vacio (vacio = fichaje desactivado a proposito); si no, la
    variable NAME. Un fichero ilegible NO puede lanzar aqui (esto corre al importar, y
    tumbaria el monitor entero): se registra y se devuelve el default -> ENABLED=False.
    Un fichero que NO existe cuenta como "no configurado" (p. ej. no se ha creado
    secrets/fichaje_url porque no se quiere el fichaje): se cae a la variable, sin error.
    utf-8-sig: tolera el BOM que mete PowerShell al crear el fichero."""
    p = os.getenv(name + "_FILE")
    if p:
        try:
            with open(p, "r", encoding="utf-8-sig") as fh:
                return fh.read().strip()
        except FileNotFoundError:
            return (os.getenv(name) or default).strip()
        except (OSError, UnicodeError, ValueError) as e:
            log.error(f"fichaje: no puedo leer {name}_FILE ({type(e).__name__}); fichaje desactivado")
            return default
    return (os.getenv(name) or default).strip()


def _env_id(name, fallback=""):
    """Id numerico de tema/hilo; si no es entero se ignora con log.error (no puede lanzar)."""
    v = os.getenv(name, "").strip() or fallback
    if v and not re.fullmatch(r"-?\d+", v):
        log.error(f"fichaje: {name} no es un numero; se ignora")
        return ""
    return v


def _hora_valida(s):
    """'HH:MM' -> (hh, mm) o None."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s or "")
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    return (hh, mm) if 0 <= hh <= 23 and 0 <= mm <= 59 else None


URL_QR = _env_or_file("FICHAJE_URL")          # https://agenda2.workandlife.com/fichajes_padres/?p=...
DNI = _env_or_file("FICHAJE_DNI").upper().replace(" ", "").replace("-", "")
# Un solo bot para todo (ronda 6): por defecto el del monitor (TG_BOT_TOKEN/_FILE); FICHAJE_BOT_TOKEN
# es un override opcional para quien quiera un bot aparte. El bot NO puede ser uno que otro proceso
# ya escuche con getUpdates (p. ej. el de Home Assistant): Telegram solo admite un oyente por bot.
_TG_TOKEN_MONITOR = _env_or_file("TG_BOT_TOKEN")
BOT_TOKEN = _env_or_file("FICHAJE_BOT_TOKEN") or _TG_TOKEN_MONITOR
CHAT_ID = os.getenv("FICHAJE_CHAT_ID", "").strip() or os.getenv("TG_CHAT_ID", "").strip()
THREAD_ID = _env_id("FICHAJE_THREAD") or _env_id("TG_THREAD_AGENDA")   # invalido -> cae al de la agenda
# Avisos tecnicos (web caida, ficha rara): al hilo/chat de Sistema del monitor si existe.
SISTEMA_CHAT = os.getenv("SISTEMA_CHAT_ID", "").strip() or CHAT_ID
SISTEMA_THREAD = _env_id("TG_THREAD_SISTEMA")

HORA = os.getenv("FICHAJE_HORA", "").strip() or "09:00"     # cuando se pregunta
if _hora_valida(HORA) is None:
    log.error("fichaje: FICHAJE_HORA no es HH:MM valido; uso 09:00")
    HORA = "09:00"
HH, MM = _hora_valida(HORA)
VENTANA = timedelta(hours=3)                                 # validez de la pregunta
try:
    RECORDATORIO_MIN = int(os.getenv("FICHAJE_RECORDATORIO_MIN", "").strip() or 30)
except ValueError:
    log.error("fichaje: FICHAJE_RECORDATORIO_MIN no es un entero; uso 30")
    RECORDATORIO_MIN = 30
if RECORDATORIO_MIN < 0:
    log.error("fichaje: FICHAJE_RECORDATORIO_MIN negativo; uso 1 (0 = sin recordatorio)")
    RECORDATORIO_MIN = 1
# Cierres del centro que no son festivo nacional (festivos de Madrid, puentes...): AAAA-MM-DD,AAAA-MM-DD
DIAS_CERRADO = {d.strip() for d in os.getenv("FICHAJE_DIAS_CERRADO", "").split(",") if d.strip()}
for _d in sorted(DIAS_CERRADO):
    try:
        datetime.strptime(_d, "%Y-%m-%d")
    except ValueError:
        log.error(f"fichaje: FICHAJE_DIAS_CERRADO tiene una fecha mal escrita: {_d!r} (formato AAAA-MM-DD)")
# Cookies extra (p. ej. la del consentimiento "Aceptar todas"): "nombre=valor;nombre2=valor2"
COOKIES_EXTRA = {}
for _c in os.getenv("FICHAJE_COOKIES_EXTRA", "").split(";"):
    if "=" in _c:
        _k, _v = _c.split("=", 1)
        if _k.strip():
            COOKIES_EXTRA[_k.strip()] = _v.strip()
CENTRO = os.getenv("FICHAJE_CENTRO", "").strip()             # vacio = se lee del HTML
STATE_FILE = Path(os.getenv("FICHAJE_STATE", "").strip() or "/data/fichaje.json")
if not STATE_FILE.is_absolute():                             # relativo -> dentro de /data
    STATE_FILE = Path("/data") / STATE_FILE
DEBUG = os.getenv("FICHAJE_DEBUG", "").strip() == "1"
DEBUG_HTML = STATE_FILE.parent / "fichaje_ultimo.html"
UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"  # UA reducido generico de Chrome movil

ENABLED = bool(URL_QR and DNI and BOT_TOKEN and CHAT_ID)
# Escucha de botones en un hilo propio (ronda 5). FICHAJE_HILO=0 la desactiva y tick() vuelve a
# leer los botones cada 30 s (modo antiguo; lo usan las pruebas y sirve de plan B).
HILO = os.getenv("FICHAJE_HILO", "1").strip() != "0"
TG = f"https://api.telegram.org/bot{BOT_TOKEN}"


class FichajeError(RuntimeError):
    """Error propio: su mensaje lo escribimos nosotros y es seguro mostrarlo."""


def _limpia(s):
    s = re.sub(r"\?p=[^\s'\"&]+", "?p=<oculto>", s)
    s = re.sub(r"bot\d+:[\w-]+", "bot<oculto>", s)
    for tok in {BOT_TOKEN, _TG_TOKEN_MONITOR}:
        if tok:
            s = s.replace(tok, "<oculto>")
    if DNI:
        s = s.replace(DNI, "<DNI>")
    if URL_QR:
        s = s.replace(URL_QR, "<URL_QR>")
    return s


def _err(e):
    """Describe una excepcion SIN su str(): tipo + status HTTP. Solo los FichajeError llevan texto."""
    partes = [type(e).__name__]
    resp = getattr(e, "response", None)
    if resp is not None and getattr(resp, "status_code", None) is not None:
        partes.append(f"HTTP {resp.status_code}")
    if isinstance(e, FichajeError):
        partes.append(str(e))
    return _limpia(" ".join(partes))


# ── estado ────────────────────────────────────────────────────────────────────
def load_state():
    d = {"cookies": {}, "tg_offset": 0, "tg_primed": False,
         "si_pendiente": False, "si_msg_id": None, "si_quien": None, "si_texto_base": None,
         "err_fichar": 0, "err_fichar_until": None, "q_date": None, "q_envios": 0,
         "aviso_pendiente": None, "nota_pregunta": None, "discrepancia_date": None,
         "asked_date": None, "asked_msg_ids": [], "reminded_date": None,
         "answer": None, "answer_date": None, "done_date": None,
         "err_date": None, "err_count": 0, "err_until": None,
         "test_date": None, "test_msg_ids": [], "last_estado": None}
    try:
        d.update(json.loads(STATE_FILE.read_text()))
    except Exception:
        pass
    if not isinstance(d.get("asked_msg_ids"), list):
        d["asked_msg_ids"] = []
    if not isinstance(d.get("test_msg_ids"), list):
        d["test_msg_ids"] = []
    return d


# El monitor guarda el estado EN MEMORIA entre ticks (_ST) y solo lo lee de disco al arrancar.
# Motivo (revision 23-sep, MEDIA-A): si el disco falla, releer en cada tick perdia answer y
# tg_offset y el mismo "Si" se fichaba una vez por tick. Unica excepcion: test_date/test_msg_ids,
# que escribe el comando manual test-bot desde otro proceso y se incorporan si el fichero cambia.
_ST = None
_mtime = None          # (sin uso desde la ronda 3; se conserva por compatibilidad con pruebas)
_ultimo_texto = None   # contenido exacto que dejo este proceso en el fichero
_save_ok = True        # False mientras no se pueda escribir: no se procesan botones
_ult_aviso = {}


def _warn_throttled(clave, texto, cada_min=30, nivel=logging.WARNING):
    """Un fallo persistente daria un log cada 30 s: se repite como mucho cada `cada_min` o si cambia."""
    ahora = datetime.now()
    prev = _ult_aviso.get(clave)
    if prev and prev[1] == texto and ahora - prev[0] < timedelta(minutes=cada_min):
        return
    _ult_aviso[clave] = (ahora, texto)
    log.log(nivel, texto)


def _stat_mtime():
    try:
        return STATE_FILE.stat().st_mtime_ns
    except (OSError, ValueError):
        return None


def save_state(st):
    """Guarda con permisos 0600. Devuelve True/False; el fallo se registra (con freno)."""
    global _save_ok, _mtime, _ultimo_texto
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.touch(0o600)
        os.chmod(tmp, 0o600)          # por si ya existia con otros permisos
        texto = json.dumps(st, indent=2, ensure_ascii=False)
        tmp.write_text(texto)
        tmp.replace(STATE_FILE)
        os.chmod(STATE_FILE, 0o600)
    except (OSError, ValueError) as e:
        _save_ok = False
        _warn_throttled("save", f"fichaje: no puedo guardar el estado ({_err(e)}); no proceso botones hasta poder escribir",
                        nivel=logging.ERROR)
        return False
    if not _save_ok:
        log.info("fichaje: el estado vuelve a guardarse")
    _save_ok = True
    _mtime = _stat_mtime()
    _ultimo_texto = texto
    return True


def _estado_memoria():
    """Estado del proceso: se carga de disco una sola vez; luego solo se fusionan las claves de test-bot.
    Un cambio externo se detecta comparando el contenido (el mtime puede no cambiar si la escritura
    cae en el mismo instante) y, tras fusionar, se reescribe la memoria a disco (BAJA-3, ronda 3)."""
    global _ST, _mtime, _ultimo_texto
    if _ST is None:
        _ST = load_state()
        _mtime = _stat_mtime()
        try:
            _ultimo_texto = STATE_FILE.read_text()
        except (OSError, ValueError):
            _ultimo_texto = None
        return _ST
    try:
        actual = STATE_FILE.read_text()
    except (OSError, ValueError):
        return _ST
    if _ultimo_texto is not None and actual != _ultimo_texto:
        try:
            disco = json.loads(actual)
            if disco.get("test_date"):
                _ST["test_date"] = disco["test_date"]
                _ST["test_msg_ids"] = list(disco.get("test_msg_ids") or [])
        except Exception:
            pass
        save_state(_ST)       # el fichero no se queda como lo dejo el otro proceso (answer, offset...)
    return _ST


def _debug_html(html):
    if not DEBUG:
        return
    try:
        fd = os.open(DEBUG_HTML, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(html)
        os.chmod(DEBUG_HTML, 0o600)
    except (OSError, ValueError):
        pass


def _borra_debug_html():
    try:
        DEBUG_HTML.unlink()
    except OSError:
        pass


# ── web de fichajes ───────────────────────────────────────────────────────────
def _base():
    u = urlsplit(URL_QR)
    return f"{u.scheme}://{u.netloc}"


def _session(st):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "X-Requested-With": "XMLHttpRequest",
                      "Referer": _base() + "/fichajes_padres/"})
    host = urlsplit(URL_QR).hostname
    for k, v in (st.get("cookies") or {}).items():
        s.cookies.set(k, v, domain=host)
    for k, v in COOKIES_EXTRA.items():            # consentimiento de cookies, etc.
        s.cookies.set(k, v, domain=host)
    return s


def _keep_cookies(st, s):
    st["cookies"] = {c.name: c.value for c in s.cookies}


def _texto(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", BeautifulSoup(t, "html.parser").get_text(" ")).strip()


def _login(st, s):
    r = s.get(URL_QR, timeout=30)
    r.raise_for_status()
    m = re.search(r"compruebaParametrosLatLong\(([-\d.]+),\s*([-\d.]+),\s*'?(\d+)'?\)", r.text)
    centro = CENTRO or (m.group(3) if m else "")
    if not centro:
        raise FichajeError("la pagina del QR no trae el id del centro (¿sesion caducada?)")
    _keep_cookies(st, s)
    return centro


def _ficha_padre(st, s, centro):
    """Devuelve el HTML de la ficha del padre (alumnos + botones). Pasa por el DNI si hace falta."""
    r = s.post(_base() + "/fichajes_padres/pages/compruebaUser.php", data={"id": centro}, timeout=30)
    r.raise_for_status()
    html = r.text
    if 'id="dni"' in html or "introduce tu DNI" in html:
        r = s.post(_base() + "/fichajes_padres/pages/compruebaPadre.php",
                   data={"dni": DNI, "idCentro": centro}, timeout=30)
        r.raise_for_status()
        html = r.text
    _keep_cookies(st, s)
    _debug_html(html)
    return html


_RE_ENTRADA = re.compile(r"Entrada:\s*(\d{1,2}:\d{2})")
_RE_SALIDA = re.compile(r"Salida:\s*(\d{1,2}:\d{2})")


def _parse_ficha(html):
    """Lee la ficha del padre tal como es de verdad (vista el 23-sep-2026 21:10):

    - Un solo boton #btn_alu (data-fn="guardaAccesoAlumno", data-p1=padre, data-p2=centro,
      data-p3=tipo). El TIPO lo decide el servidor (tipo_web); no hay botones de entrada/salida.
    - form#fRegistro con un input.chk_alu por nino (name=chk_<id>, value=<idAlumno>,
      data-ausente). El HTML NO trae 'checked' (los marca el JS al cargar); una casilla
      'disabled' es un nino que ya no admite registro (p. ej. entrada y salida hechas).
    - El estado del dia va en TEXTO dentro de div.cont_hijos: <li>Entrada: HH:MM - ...</li> y
      <li>Salida: HH:MM - ...</li>. Sin entrada, ese li no existe.
    Aqui NO se guarda ningun nombre: solo ids, banderas y horas."""
    soup = BeautifulSoup(html, "html.parser")
    texto = _texto(html)
    info = {"padre": None, "centro_web": None, "tipo_web": None, "alumnos": [], "pendientes": [],
            "hecho": False, "error": None, "error_tipo": None}
    for chk in soup.find_all("input", class_="chk_alu"):
        caja = chk.find_parent("div", class_="cont_hijos") or chk.parent
        t = caja.get_text(" ") if caja else ""
        me, ms = _RE_ENTRADA.search(t), _RE_SALIDA.search(t)
        aid = chk.get("value") or (re.search(r"(\d+)$", chk.get("id") or "") or [None, None])[1]
        info["alumnos"].append({
            "id": aid,
            "campo": chk.get("name") or f"chk_{aid}",           # nombre del campo en el multipart
            "disabled": chk.has_attr("disabled"),
            "ausente": str(chk.get("data-ausente", "0")).strip() == "1",
            "entrada": me.group(1) if me else None,
            "salida": ms.group(1) if ms else None,
        })
    # boton: #btn_alu con data-p1/2/3; se aceptan tambien otros data-fn guardaAcceso* o un onclick
    btn = soup.find(id="btn_alu") or soup.find(attrs={"data-fn": re.compile("guardaAcceso")})
    if btn is not None and btn.get("data-p1"):
        info["padre"], info["centro_web"], info["tipo_web"] = (btn.get("data-p1"), btn.get("data-p2"),
                                                               (btn.get("data-p3") or "").strip() or None)
    else:
        for el in soup.find_all(attrs={"onclick": re.compile("guardaAcceso")}):
            m = re.search(r"guardaAcceso\w*\(\s*'?(\w+)'?\s*,\s*'?(\w+)'?\s*,\s*'?(\d)'?", el["onclick"])
            if m:
                info["padre"], info["centro_web"], info["tipo_web"] = m.group(1), m.group(2), m.group(3)
                break
    presentes = [a for a in info["alumnos"] if not a["ausente"]]
    info["pendientes"] = [a["id"] for a in presentes if not a["entrada"] and not a["disabled"]]
    if "DNI" in texto and "introduce" in texto.lower():
        info["error_tipo"] = "dni"
        info["error"] = "la web sigue pidiendo el DNI: ¿DNI incorrecto, sesion del QR caducada o falta aceptar las cookies (FICHAJE_COOKIES_EXTRA)?"
    elif not info["alumnos"]:
        info["error_tipo"] = "botones"
        info["error"] = "la ficha no lista alumnos, mírala tú"
    elif not info["padre"]:
        info["error_tipo"] = "botones"
        info["error"] = "la ficha no muestra el botón de registro, mírala tú"
    else:
        # hecho = todos los ninos no ausentes tienen hora de entrada (todos ausentes: nada que fichar)
        info["hecho"] = all(a["entrada"] for a in presentes)
        if not info["hecho"] and not info["pendientes"]:
            info["error_tipo"] = "botones"
            info["error"] = "hay niños sin entrada pero la ficha no deja marcarlos, mírala tú"
        elif not info["hecho"] and info["tipo_web"] != "1":
            info["error_tipo"] = "tipo"
            info["error"] = (f"la web propone un registro de tipo {info['tipo_web']}, no una entrada; "
                             "no ficho, mírala tú")
    return info


def estado(st):
    """Consulta la web. Devuelve (hecho, info). hecho=True si todos los ninos no ausentes tienen entrada."""
    s = _session(st)
    centro = _login(st, s)
    info = _parse_ficha(_ficha_padre(st, s, centro))
    info["centro"] = centro
    hecho = bool(info["hecho"]) and not info["error"]
    st["last_estado"] = {"cuando": datetime.now().isoformat(timespec="seconds"), "hecho": hecho,
                         "alumnos": len(info["alumnos"]), "pendientes": len(info["pendientes"]),
                         "tipo_web": info["tipo_web"], "error": info["error"]}
    save_state(st)
    return hecho, info


class FichajeNoTransitorio(FichajeError):
    """Error que no se arregla reintentando: se avisa y se deja el dia (como 'sin botones')."""


def fichar(st, info):
    """Ficha la ENTRADA (tipo 1) de los ninos pendientes (sin entrada, no ausentes, casilla activa).
    Devuelve (ok, mensaje) o lanza FichajeError (transitorio) / FichajeNoTransitorio."""
    if info.get("error"):
        if info.get("error_tipo") == "dni":
            raise FichajeError(info["error"])
        raise FichajeNoTransitorio(info["error"])
    if not info.get("padre"):
        raise FichajeNoTransitorio("no encuentro el id del padre en la ficha")
    if info.get("tipo_web") != "1":
        raise FichajeNoTransitorio(f"la web propone un registro de tipo {info.get('tipo_web')}, "
                                   "no una entrada; no ficho")
    pendientes = list(info.get("pendientes") or [])
    if not pendientes:
        raise FichajeNoTransitorio("no hay ningún niño pendiente de entrada que se pueda marcar")
    campos = {a["id"]: a["campo"] for a in info.get("alumnos") or []}
    data = [(campos.get(a) or f"chk_{a}", a) for a in pendientes]      # como $('.chk_alu:checked')
    data += [("padre", info["padre"]), ("idCentro", info.get("centro_web") or info["centro"]), ("tipo", "1")]
    files = [(k, (None, str(v))) for k, v in data]   # multipart, como FormData del navegador
    s = _session(st)
    r = s.post(_base() + "/fichajes_padres/actions/hacer_fichaje.php", files=files, timeout=30)
    _keep_cookies(st, s)
    try:
        j = r.json()
    except Exception:
        return False, f"respuesta no JSON (HTTP {r.status_code})"
    desc = _limpia(str(j.get("Descripcion") or j.get("Resultado") or "sin descripcion"))[:300]
    if str(j.get("Resultado", "")).upper() != "OK":
        return False, desc
    # comprobacion: la ficha debe mostrar ahora la entrada de esos ninos. Si no, NO se reintenta el POST.
    try:
        _, info2 = estado(st)
        horas = {a["id"]: a["entrada"] for a in info2.get("alumnos") or []}
        faltan = [a for a in pendientes if not horas.get(a)]
    except Exception as e:
        log.error(f"fichaje: no pude releer la ficha tras fichar: {_err(e)}")
        faltan = pendientes
    if faltan:
        raise FichajeNoTransitorio("la web dice OK pero la ficha no muestra la entrada, míralo tú")
    _borra_debug_html()
    n = len(pendientes)
    return True, f"{desc} ({n} niño{'s' if n != 1 else ''}, entrada comprobada en la ficha)"


# ── Telegram (bot propio) ─────────────────────────────────────────────────────
def _tg(method, _timeout=(5, 15), **body):
    r = requests.post(f"{TG}/{method}", json=body, timeout=_timeout)
    if r.status_code == 429:
        # sin dormir: esto corre dentro del bucle del monitor; se reintenta en el siguiente tick
        log.warning(f"fichaje: Telegram {method}: 429 (retry-after {r.headers.get('Retry-After', '?')} s)")
    r.raise_for_status()
    return r.json().get("result")


def _msg(text, botones=None, chat=None, thread=None, _timeout=(5, 30)):
    chat = chat or CHAT_ID
    thread = THREAD_ID if thread is None else thread
    body = {"chat_id": chat, "text": text, "parse_mode": "HTML"}
    if thread:
        body["message_thread_id"] = int(thread)
    if botones:
        body["reply_markup"] = {"inline_keyboard": [botones]}
    return _tg("sendMessage", _timeout=_timeout, **body)


def _aviso(text):
    """Aviso tecnico: al hilo/chat de Sistema si esta configurado; si falla, al chat del fichaje."""
    if SISTEMA_THREAD or SISTEMA_CHAT != CHAT_ID:
        try:
            return _msg(text, chat=SISTEMA_CHAT, thread=SISTEMA_THREAD)
        except Exception as e:
            log.warning(f"fichaje: no pude avisar en Sistema ({_err(e)}); lo mando al chat del fichaje")
    return _msg(text)


def _edit(msg_id, text):
    try:
        _tg("editMessageText", chat_id=CHAT_ID, message_id=msg_id, text=text, parse_mode="HTML")
    except Exception as e:
        log.warning(f"fichaje: no pude editar el mensaje {msg_id}: {_err(e)}")


def _quitar_botones(msg_ids):
    for mid in msg_ids or []:
        if not mid:
            continue
        try:
            _tg("editMessageReplyMarkup", chat_id=CHAT_ID, message_id=mid,
                reply_markup={"inline_keyboard": []})
        except Exception as e:     # 400 "message is not modified" si ya no tenia: da igual
            log.debug(f"fichaje: quitar botones de {mid}: {_err(e)}")


def _answer(cb_id, text):
    """Respuesta al toque (el aviso flotante). Caduca a los pocos segundos: por eso el feedback
    que de verdad se ve es la edicion del mensaje (_marcar_pulsado)."""
    try:
        _tg("answerCallbackQuery", callback_query_id=cb_id, text=text[:180])
    except Exception as e:
        resp = getattr(e, "response", None)
        cuerpo = ""
        try:
            cuerpo = (resp.text or "").lower() if resp is not None else ""
        except Exception:
            pass
        if getattr(resp, "status_code", None) == 400 and ("too old" in cuerpo or "query id is invalid" in cuerpo):
            log.debug(f"fichaje: answerCallbackQuery caducado ({_err(e)})")     # normal si se tarda
        else:
            log.warning(f"fichaje: answerCallbackQuery: {_err(e)}")


def _texto_pulsado(msg, linea):
    base = _html.escape(msg.get("text") or "")
    return (base + "\n" if base else "") + linea


def _marcar_pulsado(msg, linea):
    """Edita el mensaje pulsado: su texto original + una linea con lo que se ha hecho, y sin botones
    (editMessageText sin reply_markup los quita). Devuelve el texto nuevo (HTML)."""
    nuevo = _texto_pulsado(msg, linea)
    _edit(msg.get("message_id"), nuevo)
    return nuevo


def _con_base(st, linea):
    base = st.get("si_texto_base")
    return f"{base}\n{linea}" if base else linea


BOTONES = [{"text": "✅ Sí, ficha", "callback_data": "fichar_si"},
           {"text": "❌ No, hoy no", "callback_data": "fichar_no"}]
BOTONES_TEST = [{"text": "✅ Sí (prueba)", "callback_data": "test_si"},
                {"text": "❌ No (prueba)", "callback_data": "test_no"}]


def _hora_pregunta(now):
    return now.replace(hour=HH, minute=MM, second=0, microsecond=0)


def _nuevo_dia(st, hoy):
    """Marca que hoy ya se ha tratado. Si es un dia nuevo, olvida los mensajes y la respuesta
    de dias anteriores: un boton viejo NUNCA debe casar con la pregunta de hoy."""
    if st.get("si_pendiente") and st.get("answer_date") != hoy:
        _cerrar_si_pendiente(st)
    if st.get("asked_date") != hoy:
        st["asked_date"] = hoy
        st["asked_msg_ids"] = []
        st["answer"] = None
        st["answer_date"] = None


# ── 2.ª fuente: el «Horario» de la agenda (24-sep-2026) ───────────────────────
# monitor.py inyecta aqui su agenda_horario() (sin import circular). None = sin 2.ª fuente: todo
# funciona como antes. Nada de la agenda puede bloquear el tick ni el fichaje (try/except).
agenda_horario = None


def _agenda(forzar=False):
    """Horario de hoy segun la agenda, o None si no hay fuente o no se ha podido leer."""
    fn = agenda_horario
    if fn is None:
        return None
    try:
        h = fn(forzar=forzar)
        return h if h and h.get("ok") else None
    except Exception as e:
        log.warning(f"fichaje: agenda no disponible ({_err(e)})")
        return None


def _txt_agenda(h):
    return f"entrada {h['entrada']}" if h.get("entrada") else "entrada no disponible"


def _hecho_por_agenda(st, hoy, h, motivo):
    st["done_date"] = hoy
    _nuevo_dia(st, hoy)
    save_state(st)
    log.info(f"fichaje: hecho según la agenda ({_txt_agenda(h)}); {motivo}")


def _comparar_con_agenda(st, hoy, ficha_hecho):
    """(b) Si la ficha y la agenda no coinciden: WARNING y aviso a Sistema una vez al dia. Manda la
    ficha web. Si la ficha dice hecho y la agenda no, se relee la agenda (puede ir con retraso)."""
    try:
        h = _agenda()
        if h is None:
            return None
        if bool(h.get("entrada")) != ficha_hecho and ficha_hecho:
            h = _agenda(forzar=True) or h
        if bool(h.get("entrada")) != ficha_hecho and st.get("discrepancia_date") != hoy:
            st["discrepancia_date"] = hoy
            save_state(st)
            txt = (f"la ficha y la agenda no coinciden: ficha={'entrada hecha' if ficha_hecho else 'sin entrada'}, "
                   f"agenda={_txt_agenda(h)}")
            log.warning(f"fichaje: {txt}")
            _avisar(st, f"⚠️ Guardería (fichaje): {txt}. Mando la ficha web.")
        return h
    except Exception as e:
        log.warning(f"fichaje: comparando con la agenda: {_err(e)}")
        return None


MAX_PREGUNTAS_DIA = 2     # envios de la pregunta con botones por dia (pregunta + recordatorio o reintento)


def _es_timeout(e):
    """Solo clasifica (no se registra el texto): un timeout de lectura pudo entregar el mensaje."""
    return (isinstance(e, requests.Timeout) or "timeout" in type(e).__name__.lower()
            or "timeout" in str(e).lower())


def preguntar(st, hoy, motivo=""):
    n = st.get("pendientes_n")
    cuantos = (f"\n{n} niño{'s' if n != 1 else ''} sin entrada." if isinstance(n, int) and n > 0 else "")
    h = _agenda()
    linea_agenda = f"\nAgenda: {_txt_agenda(h)}." if h else ""
    nota = st.get("nota_pregunta")
    linea_nota = f"\n{nota[1]}" if isinstance(nota, list) and len(nota) == 2 and nota[0] == hoy else ""
    txt = ("🚪 <b>Guardería: hoy no hay entrada fichada</b>" + (f" ({motivo})" if motivo else "") +
           cuantos + linea_agenda + linea_nota + "\n¿Ficho yo la entrada de hoy? Si no han ido, pulsa No.")
    if st.get("q_date") != hoy:
        st["q_date"], st["q_envios"] = hoy, 0
    if (st.get("q_envios") or 0) >= MAX_PREGUNTAS_DIA:
        # un envio que dio timeout pudo llegar igualmente: no se manda una tercera pregunta con botones
        _nuevo_dia(st, hoy)
        save_state(st)
        if not st.get("asked_msg_ids"):
            raise FichajeError(f"la pregunta no ha salido tras {MAX_PREGUNTAS_DIA} envios")
        log.warning(f"fichaje: ya van {MAX_PREGUNTAS_DIA} envios de la pregunta hoy; no mando mas")
        return
    if st.get("asked_date") == hoy:
        _quitar_botones(st.get("asked_msg_ids"))       # recordatorio: los mensajes anteriores se quedan sin botones
    _nuevo_dia(st, hoy)
    save_state(st)
    try:
        r = _msg(txt, BOTONES)
    except Exception as e:
        # si fue un timeout, Telegram pudo entregarla: cuenta como envio y se deja asked_date=hoy
        # (el recordatorio, si queda cupo, sera el segundo y ultimo). Si no llego, no cuenta y la
        # primera pregunta se reintenta via tick() (con el tope de 3 fallos).
        if _es_timeout(e):
            st["q_envios"] = (st.get("q_envios") or 0) + 1
        elif not st["asked_msg_ids"] and not motivo:
            st["asked_date"] = None
        save_state(st)
        raise
    st["q_envios"] = (st.get("q_envios") or 0) + 1
    mid = r.get("message_id") if r else None
    if mid:
        st["asked_msg_ids"].append(mid)
    save_state(st)
    log.info(f"fichaje: pregunta enviada (msg {mid})")


def _caducada(cb, msg_id, motivo):
    _answer(cb["id"], "Pregunta caducada")
    _quitar_botones([msg_id])
    log.info(f"fichaje: boton ignorado ({motivo})")


def _procesar_callback(st, cb, now=None):
    now = now or datetime.now()
    data = cb.get("data", "")
    msg = cb.get("message") or {}
    msg_id = msg.get("message_id")
    if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
        _answer(cb["id"], "Este chat no es el del fichaje.")
        return
    hoy = now.strftime("%Y-%m-%d")
    quien = _html.escape((cb.get("from") or {}).get("first_name", "alguien"))
    hhmm = datetime.now().strftime("%H:%M")      # hora real de proceso (now puede ser simulado)
    if data in ("test_si", "test_no"):
        if st.get("test_date") != hoy or msg_id not in (st.get("test_msg_ids") or []):
            return _caducada(cb, msg_id, "prueba de otro dia o mensaje desconocido")
        _answer(cb["id"], "Prueba recibida, no hago nada.")
        _marcar_pulsado(msg, f"→ prueba recibida: {'Sí' if data == 'test_si' else 'No'} ({quien}) · {hhmm}")
        st["test_msg_ids"] = [m for m in st["test_msg_ids"] if m != msg_id]
        save_state(st)
        log.info(f"fichaje: prueba de botones OK ({data})")
        return
    if data not in ("fichar_si", "fichar_no"):
        return _caducada(cb, msg_id, f"callback desconocido {data[:20]!r}")
    # validez: pregunta de hoy, este mensaje, sin respuesta previa, dentro de la ventana
    if st.get("asked_date") != hoy:
        return _caducada(cb, msg_id, "no hay pregunta de hoy")
    if msg_id not in (st.get("asked_msg_ids") or []):
        return _caducada(cb, msg_id, "mensaje que no es de la pregunta de hoy")
    if st.get("answer") is not None:
        return _caducada(cb, msg_id, f"ya se respondio ({st.get('answer')})")
    if now >= _hora_pregunta(now) + VENTANA:
        return _caducada(cb, msg_id, "fuera de la ventana de 3 h")
    otros = [m for m in st["asked_msg_ids"] if m != msg_id]
    if data == "fichar_no":
        st["answer"], st["answer_date"] = "no", hoy
        save_state(st)
        _answer(cb["id"], "Vale, hoy no se ficha.")
        _marcar_pulsado(msg, f"→ No, hoy no ({quien}) · {hhmm}")
        _quitar_botones(otros)
        log.info("fichaje: respuesta NO")
        return
    # fichar_si: se marca la respuesta ANTES de tocar la web (en memoria y en disco), para que un
    # segundo toque no fiche otra vez; si_pendiente sobrevive a un reinicio y tick() lo reintenta.
    st["answer"], st["answer_date"] = "si", hoy
    st["si_pendiente"], st["si_msg_id"], st["si_quien"] = True, msg_id, quien
    if not save_state(st):
        # MEDIA-1 (ronda 3): sin el Si en disco NO se ficha. Si el proceso muriera tras el POST,
        # al reiniciar Telegram reentregaria el Si y pasaria todas las guardas -> doble fichaje.
        # Se deshace en memoria, no se quitan los botones y poll_telegram no avanza el offset:
        # Telegram lo reentrega cuando el disco vuelva y entonces se ficha (si sigue en la ventana).
        st["answer"], st["answer_date"] = None, None
        st["si_pendiente"], st["si_msg_id"], st["si_quien"] = False, None, None
        _answer(cb["id"], "No puedo guardar el estado, no ficho; lo reintento cuando pueda.")
        log.error("fichaje: Si recibido pero el estado no se guarda; no ficho hasta poder escribir")
        return "reintentar"
    _answer(cb["id"], "Fichando…")
    st["si_texto_base"] = _texto_pulsado(msg, f"→ Sí ({quien}) · {hhmm}")
    _edit(msg_id, st["si_texto_base"] + "\n⏳ fichando…")      # quita los botones al momento
    save_state(st)
    _quitar_botones(otros)
    log.info("fichaje: respuesta SI")
    _intentar_fichar(st, now, hoy)


def _intentar_fichar(st, now, hoy):
    """Ficha tras un Si (desde el boton o reintento de tick). Sus fallos tienen tope propio (err_fichar).

    Hueco conocido (BAJA-4, ronda 3): entre un POST correcto y el save_state que apunta done_date,
    si el proceso muere, al reiniciar si_pendiente sigue True y se reintenta. La UNICA defensa
    contra el doble fichaje en ese caso es estado()/_parse_ficha: que la ficha muestre ya la hora
    de ENTRADA de esos ninos (hecho=True). Estructura vista de verdad el 23-sep; el caso "sin
    entrada todavia" (sin <li>Entrada:>) es una suposicion razonable, no se ha visto."""
    quien = st.get("si_quien") or "alguien"
    if st.get("done_date") == hoy:
        ok, texto = True, "ya constaba la entrada de hoy"
    else:
        try:
            hecho, info = estado(st)
            ok, texto = (True, "ya constaba la entrada de hoy") if hecho else fichar(st, info)
        except FichajeNoTransitorio as e:
            # no se arregla reintentando (tipo de registro raro, ficha sin boton, OK sin entrada
            # visible...): se deja el Si, se dice en el mensaje y se avisa a Sistema. Sin mas POST.
            texto = _err(e).replace("FichajeNoTransitorio ", "")
            st["si_pendiente"] = False
            save_state(st)
            log.error(f"fichaje: no ficho ({texto})")
            _edit(st.get("si_msg_id"), _con_base(st, f"⚠️ <b>No he fichado</b> ({quien} dijo sí): {texto}\n"
                                       "Míralo en la web o hazlo desde la puerta."))
            _avisar(st, f"⚠️ Guardería (fichaje): {texto}")
            return False
        except Exception as e:
            ok, texto = False, f"error hablando con la web: {_err(e)}"
    if ok:
        st["done_date"] = hoy
        st["si_pendiente"] = False
        save_state(st)
        h = _agenda(forzar=True)       # (c) confirmacion informativa; nunca hace fallar el fichaje
        if h is not None:
            texto += f"\nagenda: {'entrada ' + h['entrada'] if h.get('entrada') else 'aún sin hora'}"
        _edit(st.get("si_msg_id"), _con_base(st, f"✅ <b>Entrada fichada</b> ({quien} dijo sí): {texto}"))
        log.info(f"fichaje: entrada fichada: {texto}")
        return True
    if _fallo(st, now, hoy, texto, tipo="fichar"):
        _edit(st.get("si_msg_id"), _con_base(st, f"⚠️ <b>No he podido fichar</b> ({quien} dijo sí) tras "
                                   f"{MAX_ERRORES_DIA} intentos: {texto}\nHabrá que hacerlo desde la puerta."))
    else:
        _edit(st.get("si_msg_id"), _con_base(st, f"⏳ {quien} dijo sí, pero aún no he podido fichar: {texto}\n"
                                   f"Lo reintento en 10 min ({st['err_fichar']}/{MAX_ERRORES_DIA})."))
    return False


def _cerrar_si_pendiente(st):
    """Un Si de un dia anterior que nunca llego a fichar: cierre duro, se dice y se limpia."""
    quien = st.get("si_quien") or "alguien"
    fecha = st.get("answer_date")
    st["si_pendiente"] = False
    save_state(st)
    log.error(f"fichaje: el Si del {fecha} no se llego a fichar; lo cierro")
    _edit(st.get("si_msg_id"), _con_base(st, f"⚠️ <b>No pude fichar</b> la entrada del {fecha} ({quien} dijo sí)."))
    _avisar(st, f"⚠️ Guardería: {quien} dijo sí el {fecha}, pero no pude fichar la entrada. Revisa la ficha.")


MAX_ERRORES_DIA = 3
# Dos contadores con su tope y su pausa (BAJA-6, ronda 3):
#   err_count / err_until               -> comprobar la web y preguntar (tipo "estado")
#   err_fichar / err_fichar_until       -> fichar tras un Si (tipo "fichar")
_CONTADORES = {"estado": ("err_count", "err_until"), "fichar": ("err_fichar", "err_fichar_until")}


def _en_pausa(st, now, tipo):
    hasta = st.get(_CONTADORES[tipo][1])
    return bool(hasta) and now.isoformat() < hasta


def _fallo(st, now, hoy, desc, tipo="estado"):
    """Cuenta un fallo y pausa 10 min. Al tercero del dia se rinde y avisa. Devuelve True si se rinde.
    estado: marca el dia (sin mas preguntas ni recordatorio). fichar: suelta el Si pendiente."""
    kc, ku = _CONTADORES[tipo]
    st[kc] = (st.get(kc) or 0) + 1
    st[ku] = (now + timedelta(minutes=10)).isoformat()
    if st[kc] < MAX_ERRORES_DIA:
        log.error(f"fichaje: fallo al {'fichar' if tipo == 'fichar' else 'comprobar/preguntar'} ({desc}); "
                  f"reintento en 10 min ({st[kc]}/{MAX_ERRORES_DIA})")
        save_state(st)
        return False
    if tipo == "fichar":
        st["si_pendiente"] = False
        save_state(st)
        log.error(f"fichaje: {st[kc]} fallos al fichar hoy ({desc}); lo dejo")
        _avisar(st, f"⚠️ Guardería: dijeron que sí, pero no he podido fichar la entrada tras "
                    f"{MAX_ERRORES_DIA} intentos ({desc}). Hay que hacerlo desde la puerta.")
        return True
    _nuevo_dia(st, hoy)
    st["reminded_date"] = hoy
    save_state(st)
    log.error(f"fichaje: {st[kc]} fallos hoy ({desc}); no lo intento mas hasta mañana")
    _avisar(st, f"⚠️ Guardería: no he podido comprobar el fichaje de hoy tras {MAX_ERRORES_DIA} intentos "
                f"({desc}). Míralo tú.")
    return True


MAX_AVISO_INTENTOS = 3


def _avisar(st, texto):
    """Aviso tecnico que no se pierde: si Telegram falla se guarda y tick() lo reintenta (hasta 3 veces)."""
    try:
        _aviso(texto)
        return True
    except Exception as e:
        log.error(f"fichaje: no pude avisar por Telegram ({_err(e)}); lo reintento en los siguientes ticks")
        st["aviso_pendiente"] = {"texto": texto, "intentos": 1}
        save_state(st)
        return False


def _reintentar_aviso(st):
    ap = st.get("aviso_pendiente")
    if not ap:
        return
    try:
        _aviso(ap["texto"])
        st["aviso_pendiente"] = None
        log.info("fichaje: aviso pendiente entregado")
    except Exception as e:
        ap["intentos"] = (ap.get("intentos") or 0) + 1
        if ap["intentos"] >= MAX_AVISO_INTENTOS:
            log.error(f"fichaje: aviso perdido tras {ap['intentos']} intentos ({_err(e)})")
            st["aviso_pendiente"] = None
    save_state(st)


def _get_updates(offset, espera):
    return _tg("getUpdates", _timeout=(5, espera + 10), offset=offset, timeout=espera,
               allowed_updates=["callback_query"]) or []


def poll_telegram(st, now=None, espera=0, lanzar=False):
    """Lee las pulsaciones del bot propio y las procesa. La espera larga (long polling) va FUERA del
    lock; el procesado, DENTRO (asi el hilo y tick() no pisan el estado a la vez). Sin lanzar=True
    nunca lanza (modo tick); el hilo pide lanzar=True para gestionar el backoff y el 409."""
    with _LOCK:
        primed = st.get("tg_primed")
        offset = (st.get("tg_offset") or 0) + 1
    try:
        if not primed:
            # primer arranque: descartar lo pendiente (callbacks de hasta 24 h) sin procesarlo
            upd = _get_updates(-1, 0)
            with _LOCK:
                if upd:
                    st["tg_offset"] = max(u["update_id"] for u in upd)
                st["tg_primed"] = True
                save_state(st)
            log.info("fichaje: primer arranque, descartados los botones pendientes en Telegram")
            return
        upd = _get_updates(offset, espera)
    except Exception as e:
        if lanzar:
            raise
        _warn_throttled("getUpdates", f"fichaje: getUpdates: {_err(e)}")
        return
    with _LOCK:
        if upd and st is _ST:
            _estado_memoria()                   # recoge un test-bot enviado durante la espera larga
        for u in upd:
            if not _save_ok:
                # el estado no se esta guardando: no proceso mas; estos updates vuelven en el siguiente poll
                break
            prev = st.get("tg_offset") or 0
            if u.get("update_id", 0) <= prev:
                continue                        # ya procesado (p. ej. por el modo tick)
            try:
                st["tg_offset"] = max(prev, u["update_id"])
                if "callback_query" in u and _procesar_callback(st, u["callback_query"], now) == "reintentar":
                    st["tg_offset"] = prev          # no se confirma: Telegram lo reentregara
                    break
            except Exception as e:
                log.error(f"fichaje: error procesando un boton: {_err(e)}")
        if upd:
            save_state(st)


# ── hilo de escucha de botones (ronda 5) ──────────────────────────────────────
# Motivo: con tick() cada 30 s una pulsacion tardaba hasta 30 s en procesarse; el
# answerCallbackQuery caducaba ("query is too old") y no se veia nada. El hilo hace long polling
# (getUpdates timeout=20) y procesa al momento. Todo acceso a _ST va bajo _LOCK, tambien en tick().
# Nota: mientras se ficha (web, hasta ~1 min) el lock esta cogido y tick() espera; es a proposito
# (garantiza un solo POST) y ocurre como mucho una vez al dia.
_LOCK = threading.RLock()
_hilo = None
_parar = threading.Event()             # solo para pruebas
_relanzamientos = []                   # instantes en que tick() relanzo el hilo (tope por hora)
MAX_RELANZ_HORA = 3
ESPERA_LARGA = 20                      # s de long polling


def _escucha_una_vez():
    """Una vuelta del hilo. Nunca lanza. Devuelve cuantos segundos esperar antes de la siguiente."""
    try:
        with _LOCK:
            st = _estado_memoria()
            if not _save_ok:
                save_state(st)
            disco_ok = _save_ok
        if not disco_ok:
            return 30                  # sin poder guardar no se procesan botones
        poll_telegram(st, None, espera=ESPERA_LARGA, lanzar=True)
        _escucha_una_vez.backoff = 5
        return 0
    except Exception as e:
        resp = getattr(e, "response", None)
        if getattr(resp, "status_code", None) == 409:
            log.warning("fichaje: getUpdates 409 Conflict (otro oyente del mismo bot, p. ej. 'fichaje.py poll'); espero 30 s")
            return 30
        espera = getattr(_escucha_una_vez, "backoff", 5)
        _warn_throttled("hilo", f"fichaje: escucha de botones: {_err(e)}; reintento en {espera} s")
        _escucha_una_vez.backoff = min(espera * 2, 60)
        return espera


_escucha_una_vez.backoff = 5


def _bucle_escucha():
    log.info("fichaje: escucha de botones en marcha")
    while not _parar.is_set():
        try:
            espera = _escucha_una_vez()
        except BaseException:          # ni siquiera un fallo raro aqui tumba el hilo
            espera = 60
        if espera:
            _parar.wait(espera)


def _hilo_vivo():
    return _hilo is not None and _hilo.is_alive()


def _arrancar_hilo():
    global _hilo
    _hilo = threading.Thread(target=_bucle_escucha, name="fichaje-botones", daemon=True)
    _hilo.start()


def _asegurar_hilo(now):
    """Desde tick(): arranca el hilo la primera vez y lo relanza si ha muerto (max 3 por hora)."""
    if not (ENABLED and HILO) or _hilo_vivo():
        return
    if _hilo is None:
        _arrancar_hilo()
        return
    hace_una_hora = now - timedelta(hours=1)
    _relanzamientos[:] = [t for t in _relanzamientos if t > hace_una_hora]
    if len(_relanzamientos) >= MAX_RELANZ_HORA:
        _warn_throttled("hilo-muerto", f"fichaje: el hilo de botones ha muerto {len(_relanzamientos)} veces "
                                       "en la ultima hora; no lo relanzo, leo los botones desde tick()")
        return
    log.warning("fichaje: el hilo de botones estaba muerto; lo relanzo")
    _relanzamientos.append(now)
    _arrancar_hilo()


# ── entrada desde el bucle principal del monitor ──────────────────────────────
def _decidir(st, now, hoy, es_dia_lectivo):
    # 1) Si pendiente: sus reintentos NO dependen de la ventana de 3 h (el Si ya fue valido);
    #    los acota el tope de 3 fallos (err_fichar) y el cierre duro al cambiar de dia.
    if st.get("si_pendiente"):
        if st.get("answer_date") != hoy:
            _cerrar_si_pendiente(st)
        elif st.get("done_date") == hoy:
            st["si_pendiente"] = False
            save_state(st)
        else:
            if not _en_pausa(st, now, "fichar"):
                _intentar_fichar(st, now, hoy)
            return
    hora_pregunta = _hora_pregunta(now)
    if hoy in DIAS_CERRADO or not es_dia_lectivo():
        return
    if not (hora_pregunta <= now < hora_pregunta + VENTANA):
        return
    if _en_pausa(st, now, "estado"):
        return                                   # pausa tras un fallo, para no martillear
    if st.get("asked_date") != hoy and st.get("done_date") != hoy:
        # un fallo de la web (o que siga pidiendo el DNI) sale como excepcion: tick() lo reintenta
        # hasta 3 veces con pausa de 10 min y solo al tercero avisa y marca el dia (_fallo).
        # (a) Con la agenda como respaldo: entrada con hora -> hecho; sin hora -> se pregunta igual
        #     avisando de que la ficha no se ha leido. Sin agenda: como siempre.
        try:
            hecho, info = estado(st)
            fallo_ficha = FichajeError(info["error"]) if info.get("error") and info.get("error_tipo") == "dni" else None
        except Exception as e:
            hecho, info, fallo_ficha = False, {}, e
        if fallo_ficha is not None:
            h = _agenda()
            if h is None:
                raise fallo_ficha
            if h.get("entrada"):
                _hecho_por_agenda(st, hoy, h, f"la ficha web no se ha podido leer ({_err(fallo_ficha)})")
                return
            log.warning(f"fichaje: la ficha web no se ha podido leer ({_err(fallo_ficha)}); "
                        "la agenda dice que no hay entrada: pregunto igual")
            st["nota_pregunta"] = [hoy, "⚠️ No he podido leer la ficha de fichajes: si pulsas Sí, puede fallar."]
            st["pendientes_n"] = None
            preguntar(st, hoy)
            return
        if hecho:
            _comparar_con_agenda(st, hoy, True)
            st["done_date"] = hoy
            _nuevo_dia(st, hoy)
            save_state(st)
            log.info("fichaje: la entrada de hoy ya estaba registrada; no pregunto")
        elif info.get("error"):
            # la ficha no deja fichar (sin boton, tipo raro...): no es transitorio
            h = _agenda()
            if h is not None and h.get("entrada"):
                _hecho_por_agenda(st, hoy, h, f"la ficha web no sirve ({info['error']})")
            elif h is not None:
                log.warning(f"fichaje: {info['error']}; la agenda dice que no hay entrada: pregunto igual")
                st["nota_pregunta"] = [hoy, f"⚠️ La ficha de fichajes da un problema ({info['error']}): "
                                            "si pulsas Sí, puede fallar."]
                st["pendientes_n"] = len(info.get("pendientes") or []) or None
                preguntar(st, hoy)
            else:
                # sin agenda: se avisa y se marca al primer intento (como antes)
                _nuevo_dia(st, hoy)
                st["reminded_date"] = hoy
                save_state(st)
                log.warning(f"fichaje: {info['error']}")
                _avisar(st, f"⚠️ Guardería (fichaje): {info['error']}")
        else:
            _comparar_con_agenda(st, hoy, False)
            st["pendientes_n"] = len(info.get("pendientes") or [])   # solo el numero, nunca nombres
            preguntar(st, hoy)
    elif (st.get("asked_date") == hoy and st.get("answer") is None and RECORDATORIO_MIN
          and st.get("done_date") != hoy and st.get("reminded_date") != hoy
          and now >= hora_pregunta + timedelta(minutes=RECORDATORIO_MIN)):
        st["reminded_date"] = hoy
        save_state(st)
        preguntar(st, hoy, motivo="recordatorio, sin respuesta")


def tick(now, es_dia_lectivo):
    """Llamar cada ~30 s. es_dia_lectivo: callable() -> bool (laborable y no festivo). Nunca lanza."""
    if not ENABLED:
        return
    try:
        with _LOCK:
            st = _estado_memoria()               # el estado se carga ANTES de arrancar el hilo
            hoy = now.strftime("%Y-%m-%d")
            if st.get("err_date") != hoy:
                st["err_date"] = hoy
                st["err_count"], st["err_until"], st["err_fichar"], st["err_fichar_until"] = 0, None, 0, None
            if not _save_ok:
                save_state(st)                   # reintenta escribir; si sigue fallando, sin botones
        _asegurar_hilo(now)
        if _save_ok and not _hilo_vivo():
            poll_telegram(st, now)               # modo antiguo: sin hilo (FICHAJE_HILO=0 o tope de relanzamientos)
        with _LOCK:
            _reintentar_aviso(st)
            try:
                _decidir(st, now, hoy, es_dia_lectivo)
            except Exception as e:
                _fallo(st, now, hoy, _err(e), tipo="estado")
    except Exception as e:                       # ultimo cinturon: nada de fichaje llega al monitor
        log.error(f"fichaje: error inesperado en tick: {_err(e)}")


# ── uso manual: docker exec guarderia-monitor python fichaje.py estado|fichar|test-bot|poll ──
# estado y fichar escriben fichaje.json (cookies, last_estado); fichar es un Si explicito SIN pregunta.
# poll es de SOLO LECTURA: lista lo pendiente sin avanzar el offset ni procesar (quien ficha es el monitor);
# con el monitor en marcha puede dar 409 (dos oyentes del mismo bot): inocuo. test-bot solo envia.
def _cli(cmd):
    st = load_state()
    if cmd == "estado":
        hecho, info = estado(st)
        # sin nombres: ids, banderas y horas; padre/centro solo como "presente"
        print(json.dumps({"hecho": hecho, "tipo_web": info.get("tipo_web"), "padre": bool(info.get("padre")),
                          "alumnos": info.get("alumnos"), "pendientes": info.get("pendientes"),
                          "error": info.get("error"), "error_tipo": info.get("error_tipo")},
                         ensure_ascii=False, indent=2))
    elif cmd == "fichar":
        # manual y explicito (lo teclea el usuario): equivale a un Si, SIN pregunta
        hecho, info = estado(st)
        print("ya hecho" if hecho else fichar(st, info))
    elif cmd == "test-bot":
        r = _msg("🧪 Prueba del bot de fichaje: pulsa un botón; no hace nada real.", BOTONES_TEST)
        hoy = datetime.now().strftime("%Y-%m-%d")
        st = load_state()
        if st.get("test_date") != hoy:
            st["test_date"], st["test_msg_ids"] = hoy, []
        if r and r.get("message_id"):
            st["test_msg_ids"].append(r["message_id"])
        save_state(st)
        print(f"enviado, message_id={r.get('message_id') if r else None}")
    elif cmd == "poll":
        # offset = el ya confirmado por el monitor + 1: no confirma nada nuevo ni procesa botones
        # timeout=0 y sin allowed_updates (no cambia el filtro del bot). Con el monitor en marcha su
        # hilo esta en long polling y esto puede dar 409 Conflict: es inocuo, basta repetirlo.
        upd = _tg("getUpdates", _timeout=(5, 10), offset=(st.get("tg_offset") or 0) + 1, timeout=0) or []
        print(f"{len(upd)} pendientes (offset guardado {st.get('tg_offset')})")
        for u in upd:
            cq = u.get("callback_query") or {}
            print(f"  update {u.get('update_id')}: {cq.get('data')!r} en mensaje {(cq.get('message') or {}).get('message_id')}")
    else:
        print("uso: python fichaje.py estado|fichar|test-bot|poll")
        return 2
    return 0


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if not ENABLED:
        print("fichaje deshabilitado: faltan URL, DNI, token del bot o chat_id"); sys.exit(2)
    try:
        sys.exit(_cli(sys.argv[1] if len(sys.argv) > 1 else "estado"))
    except Exception as e:      # nunca el traceback: requests lo imprime con la URL bot<token> o ?p=
        print(f"error: {_err(e)}", file=sys.stderr)
        sys.exit(1)
