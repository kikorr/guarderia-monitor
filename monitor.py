import os
import io
import re
import json
import time
import random
import logging
import logging.handlers
import zipfile
import html
import threading
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()


def env_or_file(name, default=""):
    """Lee un secreto de {NAME}_FILE (Docker secret en /run/secrets) si existe;
    si no, cae a la variable de entorno NAME. Permite sacar credenciales de
    Config.Env (no aparecen en docker inspect). utf-8-sig: tolera el BOM de
    PowerShell."""
    path = os.getenv(name + "_FILE")
    if path:
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                return fh.read().strip()
        except OSError:
            pass
    return os.getenv(name, default)


# 23-sep-2026: nunca str(e) crudo en logs ni en Telegram. Un HTTPError de requests lleva la URL
# completa: https://api.telegram.org/bot<TOKEN>/... (el token acababa en monitor.log y docker logs),
# y las URLs del portal llevan la sesion (?p=..., p5rkv8nc58hag=...).
_MASCARAS = (
    (re.compile(r"bot\d+:[\w-]+"), "bot<oculto>"),
    (re.compile(r"\?p=[^\s&'\"]+"), "?p=<oculto>"),
    (re.compile(r"p5rkv8nc58hag=[^\s&'\"]+"), "<sesion>"),
)


def enmascara(texto):
    """Quita token de bot y parametros de sesion de cualquier texto que vaya a log o a Telegram."""
    texto = str(texto)
    for rx, sust in _MASCARAS:
        texto = rx.sub(sust, texto)
    # valores ya cargados (desde *_FILE o del entorno); se buscan en tiempo de ejecucion
    for secreto in (globals().get("WL_PASS"), globals().get("TG_BOT_TOKEN"),
                    os.getenv("WL_PASS"), os.getenv("TG_BOT_TOKEN")):
        if secreto and len(secreto) >= 6:
            texto = texto.replace(secreto, "<oculto>")
    return texto


def err_txt(e):
    """Tipo de excepcion + 'HTTP nnn' si hay respuesta + su mensaje ENMASCARADO (max 200)."""
    partes = [type(e).__name__]
    resp = getattr(e, "response", None)
    if resp is not None and getattr(resp, "status_code", None) is not None:
        partes.append(f"HTTP {resp.status_code}")
    msg = enmascara(e)[:200]
    if msg:
        partes.append(f"- {msg}")
    return " ".join(partes)


# --- Config ---
# NO hay URL de aula en la configuración: el centro, las aulas y la agenda se
# descubren tras el login (ver discover_aulas). Con MURO_URL fijo, el sid del
# curso anterior dejó de existir y el portal rebotaba a la home sin dar error:
# el monitor llevaba días leyendo la portada creyendo que era el muro del aula.
WL_USER = env_or_file("WL_USER")
WL_PASS = env_or_file("WL_PASS")
# Portal de familias de Workandlife. Es el mismo para todos los centros;
# se deja configurable por si algún centro usa otro punto de entrada.
WL_LOGIN_URL = os.getenv("WL_LOGIN_URL", "https://comunidaddefamilias.com").rstrip("/")
# Telegram (envío directo, sin Home Assistant)
TG_BOT_TOKEN = env_or_file("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
# Threads (temas) opcionales. Déjalos vacíos si usas un chat normal sin temas.
TG_THREAD_MURO = os.getenv("TG_THREAD_MURO", "").strip()
TG_THREAD_AGENDA = os.getenv("TG_THREAD_AGENDA", "").strip()
TG_THREAD_SISTEMA = os.getenv("TG_THREAD_SISTEMA", "").strip()
# Grupo distinto para sistema/alertas (opcional). Por defecto, el mismo del muro.
SISTEMA_CHAT_ID = os.getenv("SISTEMA_CHAT_ID", "").strip() or TG_CHAT_ID
TG_API = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"

# Destino secundario opcional (paridad multi-grupo)
TG_CHAT_ID_2 = os.getenv("TG_CHAT_ID_2", "").strip()
TG_THREAD_AGENDA_2 = os.getenv("TG_THREAD_AGENDA_2", "").strip()

# Lista de destinos para agenda: cada uno es (chat_id, thread_id)
AGENDA_TARGETS = [(TG_CHAT_ID, TG_THREAD_AGENDA)]
if TG_CHAT_ID_2 and TG_THREAD_AGENDA_2:
    AGENDA_TARGETS.append((TG_CHAT_ID_2, TG_THREAD_AGENDA_2))

# Filtro opcional de aulas (regex sobre el nombre). Vacío = todas las que
# devuelva el portal, que es lo que queremos por defecto.
AULAS_INCLUDE = os.getenv("AULAS_INCLUDE", "").strip()

# Hora a partir de la cual, en día lectivo, avisamos si la agenda sigue vacía.
# 0 desactiva el aviso.
AGENDA_EMPTY_ALERT_HOUR = int(os.getenv("AGENDA_EMPTY_ALERT_HOUR", "15") or 0)

# Origen del centro (p.ej. https://TUCENTRO.workandlife.com). Se rellena en el
# login a partir de la redirección del portal: tampoco se configura a mano.
PORTAL_ORIGIN = ""

STATE_FILE = Path("/data/state.json")
LOG_FILE = Path("/data/monitor.log")
MEDIA_DIR = Path("/data/media")

# Intervalos aleatorios (min, max) en minutos
MURO_INTERVAL = (50, 70)
AGENDA_INTERVAL = (25, 35)

# Pasada nocturna del muro TODOS los días (~esta hora, con jitter) para pillar
# publicaciones de tardes/fines de semana. Vacío para desactivar. Solo muro
# (la agenda no aplica fuera de días lectivos).
EVENING_MURO_HOUR = os.getenv("EVENING_MURO_HOUR", "22").strip()

# Días que se conserva la caché de media ya enviada (es solo caché: los ficheros
# ya están subidos a Telegram). Sin límite el volumen crece sin freno (~0.5 GB/mes).
MEDIA_RETENTION_DAYS = int(os.getenv("MEDIA_RETENTION_DAYS", "30"))

# Límite práctico de subida del Bot API (50 MB); dejamos margen.
TG_MAX_FILE_BYTES = 49 * 1024 * 1024

# Reintentos antes de dar una publicación por perdida (no marcarla vista al 1er fallo)
PUB_MAX_ATTEMPTS = 3

# Asegura que /data existe antes de configurar el log en fichero
Path("/data").mkdir(parents=True, exist_ok=True)

# --- Logging (rotativo: 5 MB x 3 — sin rotación el log crece sin límite 24/7) ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"),
    ],
)
log = logging.getLogger("guarderia")

# Sesión HTTP reutilizable para Telegram (keep-alive: evita un handshake TLS por llamada)
_tg = requests.Session()


# --- State ---
def load_state():
    default = {
        "pub_ids": [],
        "baseline_done": False,
        "pub_fail_counts": {},
        "agenda_url": None,
        "aulas": {},
        "agenda_unknown_labels": [],
        "agenda_empty_alert_date": None,
        "agenda_snapshot": {},
        "agenda_message_ids": [],
        "last_agenda_date": None,
        "last_muro_check": None,
        "last_agenda_check": None,
    }
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # state.json corrupto: apartarlo y re-baselinear (sin notificaciones)
            log.error(f"state.json corrupto ({err_txt(e)}) — se aparta y se re-baselinea")
            try:
                STATE_FILE.replace(STATE_FILE.with_suffix(".corrupt"))
            except OSError:
                pass
            return default
        # Migración: estados antiguos sin flag — si ya hay pub_ids, el baseline se hizo
        state.setdefault("baseline_done", bool(state.get("pub_ids")))
        state.setdefault("pub_fail_counts", {})
        state.setdefault("aulas", {})
        state.setdefault("agenda_unknown_labels", [])
        return state
    return default


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        tmp.replace(STATE_FILE)
    except OSError as e:
        # Sin esto, un disco lleno mataba el proceso en bucle (save fuera de try en el caller)
        log.error(f"save_state FALLÓ: {err_txt(e)}")
        alert_once("save-state", f"⚠️ No puedo guardar el estado del monitor ({err_txt(e)}). ¿Disco lleno?")


# --- Alertas con cooldown (evita spamear Telegram con el mismo problema cada ciclo) ---
_last_alerts = {}


def alert_once(key, message, cooldown_min=180):
    """Envía una alerta como máximo una vez cada cooldown_min por clave."""
    now = datetime.now()
    last = _last_alerts.get(key)
    if last and (now - last) < timedelta(minutes=cooldown_min):
        log.info(f"Alerta '{key}' suprimida (cooldown): {message}")
        return
    _last_alerts[key] = now
    notify_ha("alert", message=message)


# --- Envío de eventos: directo a Telegram (sin Home Assistant) ---
def notify_ha(event_type, **payload):
    """Enruta cada evento directamente a Telegram. (Nombre conservado por compatibilidad.)"""
    if event_type == "muro_text":
        tg_send_message(payload.get("message", ""), TG_THREAD_MURO)
    elif event_type == "muro_photo":
        tg_send_file("sendPhoto", "photo", MEDIA_DIR / payload["file"],
                     payload.get("caption"), TG_THREAD_MURO)
    elif event_type == "muro_video":
        tg_send_file("sendVideo", "video", MEDIA_DIR / payload["file"],
                     payload.get("caption"), TG_THREAD_MURO)
    elif event_type in ("alert", "status", "session_expired"):
        # session_expired antes caía al else y la alerta se perdía en un warning
        tg_send_message(payload.get("message", ""), TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)
    else:
        log.warning(f"Evento desconocido: {event_type}")


# --- Telegram directo ---
def _retry_after_seconds(response, default=5):
    """Extrae parameters.retry_after de una respuesta 429 de Telegram."""
    try:
        return int(response.json().get("parameters", {}).get("retry_after", default))
    except Exception:
        return default


def clip_html(msg, limit=4000):
    """Recorta un mensaje YA escapado sin partir entidades HTML (&amp; etc. no llevan \\n ni espacios)."""
    if len(msg) <= limit:
        return msg
    cut = msg[:limit]
    for sep in ("\n", " "):
        if sep in cut:
            cut = cut.rsplit(sep, 1)[0]
            break
    return cut + "\n\n[…texto recortado]"


def tg_send_message(text, thread_id, chat_id=None, max_retries=4):
    """Envia mensaje a Telegram y devuelve message_id. Reintenta en 429/errores transitorios."""
    target_chat = chat_id if chat_id is not None else TG_CHAT_ID
    body = {"chat_id": target_chat, "text": clip_html(text), "parse_mode": "HTML"}
    if thread_id:
        body["message_thread_id"] = int(thread_id)
    for attempt in range(1, max_retries + 1):
        try:
            r = _tg.post(f"{TG_API}/sendMessage", json=body, timeout=30)
            if r.status_code == 429:
                wait = min(_retry_after_seconds(r) + 1, 60)
                log.warning(f"TG sendMessage 429; espero {wait}s ({attempt}/{max_retries})")
                time.sleep(wait)
                continue
            r.raise_for_status()
            msg_id = r.json().get("result", {}).get("message_id")
            log.info(f"TG sent message_id={msg_id} chat={target_chat} thread={thread_id}")
            return msg_id
        except Exception as e:
            if attempt < max_retries:
                wait = 2 * attempt
                log.warning(f"TG send error chat={target_chat}: {err_txt(e)}; reintento en {wait}s ({attempt}/{max_retries})")
                time.sleep(wait)
                continue
            log.error(f"TG send error definitivo chat={target_chat} thread={thread_id}: {err_txt(e)}")
    return None


def tg_delete_message(message_id, chat_id=None):
    """Borra un mensaje de Telegram. Usa TG_CHAT_ID si chat_id es None."""
    target_chat = chat_id if chat_id is not None else TG_CHAT_ID
    try:
        r = _tg.post(
            f"{TG_API}/deleteMessage",
            json={"chat_id": target_chat, "message_id": message_id},
            timeout=10,
        )
        log.info(f"TG deleted message_id={message_id} chat={target_chat} (ok={r.json().get('ok')})")
    except Exception as e:
        log.warning(f"TG delete error chat={target_chat} mid={message_id}: {err_txt(e)}")


def tg_send_file(method, field, file_path, caption, thread_id, chat_id=None, max_retries=4):
    """Sube una foto/vídeo directamente a Telegram (multipart). method=sendPhoto|sendVideo.
    Reintenta en 429 respetando retry_after (evita perder fotos en ráfagas del muro)."""
    body = {"chat_id": chat_id if chat_id is not None else TG_CHAT_ID}
    if caption:
        body["caption"] = caption
        body["parse_mode"] = "HTML"
    if thread_id:
        body["message_thread_id"] = int(thread_id)
    name = Path(file_path).name
    for attempt in range(1, max_retries + 1):
        try:
            with open(file_path, "rb") as fh:
                r = _tg.post(f"{TG_API}/{method}", data=body,
                             files={field: fh}, timeout=180)
            if r.status_code == 429:
                wait = min(_retry_after_seconds(r) + 1, 60)
                log.warning(f"TG {method} 429 rate-limit ({name}); espero {wait}s (intento {attempt}/{max_retries})")
                time.sleep(wait)
                continue
            r.raise_for_status()
            log.info(f"TG {method} ok ({name})")
            return True
        except Exception as e:
            if attempt < max_retries:
                wait = 2 * attempt
                log.warning(f"TG {method} error ({name}): {err_txt(e)}; reintento en {wait}s ({attempt}/{max_retries})")
                time.sleep(wait)
                continue
            log.error(f"TG {method} error definitivo ({file_path}): {err_txt(e)}")
            return False
    log.error(f"TG {method} agotados reintentos ({file_path})")
    return False


def tg_send_media_group(items, thread_id, chat_id=None, max_retries=4):
    """Envía un álbum (2-10 fotos/vídeos mezclados) en UNA llamada sendMediaGroup.
    items: lista de dicts {path: Path, kind: 'photo'|'video', caption: str|None}.
    Un álbum de 10 fotos = 1 llamada API en vez de 10 → evita las tormentas de 429."""
    target_chat = chat_id if chat_id is not None else TG_CHAT_ID
    media = []
    for i, it in enumerate(items):
        entry = {"type": it["kind"], "media": f"attach://f{i}"}
        if it.get("caption"):
            entry["caption"] = it["caption"]
            entry["parse_mode"] = "HTML"
        media.append(entry)
    body = {"chat_id": target_chat, "media": json.dumps(media)}
    if thread_id:
        body["message_thread_id"] = int(thread_id)
    names = ", ".join(Path(it["path"]).name for it in items)
    for attempt in range(1, max_retries + 1):
        files = {}
        try:
            try:
                files = {f"f{i}": open(it["path"], "rb") for i, it in enumerate(items)}
                r = _tg.post(f"{TG_API}/sendMediaGroup", data=body, files=files, timeout=300)
            finally:
                for fh in files.values():
                    fh.close()
            if r.status_code == 429:
                wait = min(_retry_after_seconds(r) + 1, 60)
                log.warning(f"TG álbum 429; espero {wait}s (intento {attempt}/{max_retries})")
                time.sleep(wait)
                continue
            r.raise_for_status()
            log.info(f"TG álbum ok ({len(items)} items: {names})")
            return True
        except Exception as e:
            if attempt < max_retries:
                wait = 3 * attempt
                log.warning(f"TG álbum error ({names}): {err_txt(e)}; reintento en {wait}s ({attempt}/{max_retries})")
                time.sleep(wait)
                continue
            log.error(f"TG álbum error definitivo ({names}): {err_txt(e)}")
    return False


def chunk_albums(seq, size=10):
    """Trocea en álbumes de hasta `size`. Si el último quedaría con 1 solo item,
    se rebalancea (9+2) porque sendMediaGroup exige mínimo 2."""
    chunks = [list(seq[i:i + size]) for i in range(0, len(seq), size)]
    if len(chunks) >= 2 and len(chunks[-1]) == 1:
        chunks[-1].insert(0, chunks[-2].pop())
    return chunks


def send_media_batch(media_list, thread_id, chat_id=None):
    """Envía una lista de medias [{path, kind, caption?}] en álbumes con fallback individual.
    Devuelve el nº de ficheros que NO se pudieron entregar."""
    failed = 0
    sendable = []
    for m in media_list:
        try:
            size = Path(m["path"]).stat().st_size
        except OSError:
            failed += 1
            continue
        if size > TG_MAX_FILE_BYTES:
            log.warning(f"{Path(m['path']).name}: {size / 1e6:.0f} MB > límite 50 MB del Bot API — omitido")
            alert_once("oversize", f"⚠️ Un vídeo del muro supera los 50 MB del Bot API y no se puede enviar ({Path(m['path']).name}).", cooldown_min=720)
            failed += 1
            continue
        sendable.append(m)

    if not sendable:
        return failed
    if len(sendable) == 1:
        m = sendable[0]
        method, field = ("sendPhoto", "photo") if m["kind"] == "photo" else ("sendVideo", "video")
        if not tg_send_file(method, field, m["path"], m.get("caption"), thread_id, chat_id=chat_id):
            failed += 1
        return failed

    for chunk in chunk_albums(sendable, 10):
        if len(chunk) == 1:
            m = chunk[0]
            method, field = ("sendPhoto", "photo") if m["kind"] == "photo" else ("sendVideo", "video")
            if not tg_send_file(method, field, m["path"], m.get("caption"), thread_id, chat_id=chat_id):
                failed += 1
        elif not tg_send_media_group(chunk, thread_id, chat_id=chat_id):
            # Fallback: si el álbum falla tras los reintentos, intentar los items de uno en uno
            log.warning(f"Álbum falló — fallback individual de {len(chunk)} items")
            for m in chunk:
                method, field = ("sendPhoto", "photo") if m["kind"] == "photo" else ("sendVideo", "video")
                if not tg_send_file(method, field, m["path"], m.get("caption"), thread_id, chat_id=chat_id):
                    failed += 1
                time.sleep(1)
        time.sleep(3)  # respiro entre álbumes (cada álbum cuenta como N mensajes para el límite del grupo)
    return failed


def tg_send_agenda_to_all(text):
    """Envia el mensaje de agenda a todos los AGENDA_TARGETS. Devuelve lista paralela de message_ids."""
    ids = []
    for chat_id, thread_id in AGENDA_TARGETS:
        ids.append(tg_send_message(text, thread_id, chat_id=chat_id))
    return ids


def tg_delete_agenda_in_all(message_ids):
    """Borra los mensajes de agenda previos en cada destino. message_ids es lista paralela a AGENDA_TARGETS."""
    if not message_ids:
        return
    for (chat_id, _), mid in zip(AGENDA_TARGETS, message_ids):
        if mid:
            tg_delete_message(mid, chat_id=chat_id)


# --- Helpers ---
def easter_date(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(year, month, day).date()


def is_spanish_holiday(dt):
    d = dt.date() if isinstance(dt, datetime) else dt
    year = d.year
    fixed = [
        (1, 1), (1, 6), (5, 1), (8, 15),
        (10, 12), (11, 1), (12, 6), (12, 8), (12, 25),
    ]
    if (d.month, d.day) in fixed:
        return True
    easter = easter_date(year)
    if d in (easter - timedelta(days=3), easter - timedelta(days=2)):
        return True
    return False


# 23-sep-2026: horario de monitorizacion parametrizable (antes 07:00-17:00 fijo).
# Un valor no entero o START >= END no tumba el arranque: log.error y 7/17 (como FICHAJE_HORA).
def _work_hours():
    try:
        ini = int(os.getenv("WORK_HOUR_START", "").strip() or 7)
        fin = int(os.getenv("WORK_HOUR_END", "").strip() or 17)
    except ValueError:
        log.error("WORK_HOUR_START/WORK_HOUR_END no son horas enteras (p. ej. 7 y 17); uso 7-17")
        return 7, 17
    if not (0 <= ini < fin <= 24):
        log.error(f"WORK_HOUR_START={ini} / WORK_HOUR_END={fin} no forman un horario valido; uso 7-17")
        return 7, 17
    return ini, fin


WORK_HOUR_START, WORK_HOUR_END = _work_hours()


def is_working_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if is_spanish_holiday(now):
        return False
    return WORK_HOUR_START <= now.hour < WORK_HOUR_END


def random_wait(interval):
    return timedelta(minutes=random.randint(*interval))


def next_evening_sweep():
    """Próxima pasada nocturna del muro (~EVENING_MURO_HOUR, jitter 0-25min)."""
    now = datetime.now()
    target = now.replace(hour=int(EVENING_MURO_HOUR), minute=random.randint(0, 25),
                         second=0, microsecond=0)
    # Si ya pasó la hora objetivo (o acabamos de barrer esta noche), programar mañana.
    # Sin el 2º término, tras barrer a las 22:05 el jitter podía recaer a las 22:17 y repetir.
    if target <= now or now.hour >= int(EVENING_MURO_HOUR):
        target += timedelta(days=1)
    return target


def prune_media(days=MEDIA_RETENTION_DAYS):
    """Borra de la caché los ficheros ya enviados con más de `days` días (el volumen crecía sin freno)."""
    if days <= 0 or not MEDIA_DIR.exists():
        return
    cutoff = time.time() - days * 86400
    n = freed = 0
    for f in MEDIA_DIR.iterdir():
        try:
            st = f.stat()
            if f.is_file() and st.st_mtime < cutoff:
                freed += st.st_size
                f.unlink()
                n += 1
        except OSError:
            pass
    if n:
        log.info(f"Media prune: {n} ficheros borrados, {freed / 1e6:.0f} MB liberados")


def daily_reset_if_needed(state):
    today = datetime.now().strftime("%Y-%m-%d")
    last_date = state.get("last_agenda_date")
    if last_date != today:
        log.info(f"New day ({today}) — silent agenda reset")
        state["agenda_snapshot"] = {}
        state["agenda_message_ids"] = []
        state.pop("agenda_message_id", None)
        state["last_agenda_date"] = today
        save_state(state)
        return True
    return False


def get_agenda_message_ids(state):
    """Devuelve lista de message_ids alineada a AGENDA_TARGETS. Migra state antiguo (agenda_message_id escalar)."""
    ids = state.get("agenda_message_ids")
    if ids is None:
        legacy = state.get("agenda_message_id")
        ids = [legacy] if legacy else []
    # padding hasta len(AGENDA_TARGETS) por si añadimos destinos posteriormente
    while len(ids) < len(AGENDA_TARGETS):
        ids.append(None)
    return ids


# --- Extraer URL de la agenda desde la pagina del aula ---
def extract_agenda_url(soup):
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "agenda2.workandlife.com" in href:
            log.info(f"Agenda URL found: {enmascara(href)}")
            return href
        link_text = a_tag.get_text(strip=True).lower()
        if "agenda" in link_text and "workandlife" in href:
            log.info(f"Agenda URL found (by text): {enmascara(href)}")
            return href
    for iframe in soup.find_all("iframe", src=True):
        if "agenda2.workandlife.com" in iframe["src"]:
            log.info(f"Agenda URL found (iframe): {enmascara(iframe['src'])}")
            return iframe["src"]
    return None


# --- Login / Session ---
_session = None


def get_session():
    """Devuelve una sesion autenticada, haciendo login si es necesario."""
    global _session
    if _session:
        return _session
    return do_login()


def do_login():
    """Login en el portal de familias y devuelve sesion autenticada."""
    global _session
    log.info("Logging in to Workandlife...")
    s = requests.Session()
    try:
        # Obtener token CSRF
        resp = s.get(WL_LOGIN_URL + "/", timeout=15)
        resp.raise_for_status()
        m = re.search(r'_token.*?value="(\d+)"', resp.text)
        if not m:
            log.error("Login: no _token found")
            return None
        token = m.group(1)

        # POST login
        r = s.post(WL_LOGIN_URL + "/index.php", data={
            "usuario": WL_USER,
            "contrasena": WL_PASS,
            "_token": token,
            "grecaptcha": "",
        }, timeout=15)

        if "incorrecto" in r.text.lower():
            log.error("Login failed: credentials rejected")
            alert_once("login-creds", "⚠️ Login Workandlife fallido. Revisa usuario/contraseña.", cooldown_min=360)
            return None

        # El portal redirige al subdominio del centro: de ahí sale el origen,
        # así no hay que configurarlo (ni deducirlo troceando una URL del .env).
        global PORTAL_ORIGIN
        PORTAL_ORIGIN = origin_of(r.url) or PORTAL_ORIGIN
        if not PORTAL_ORIGIN:
            log.error("Login: no pude determinar el dominio del centro")
            return None

        log.info(f"Login OK (centro: {PORTAL_ORIGIN})")
        _session = s
        return s
    except Exception as e:
        log.error(f"Login error: {err_txt(e)}")
        return None


def origin_of(url):
    """esquema://host de una URL, o "" si no se puede determinar."""
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def _looks_logged_in(resp):
    """Marcador de sesión viva. Se usa el enlace de logout, que solo aparece
    autenticado: el marcador anterior era 'user-post', pero un aula recién
    creada no tiene ninguna publicación y provocaba un re-login en cada ciclo."""
    return "/logout.php" in resp.text


def get_authed(url, timeout=30):
    """GET autenticado con un único re-login si la sesión ha caducado."""
    global _session
    session = get_session()
    if not session:
        return None
    for intento in (1, 2):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
        except Exception as e:
            log.error(f"GET {enmascara(url)} falló: {err_txt(e)}")
            return None
        if _looks_logged_in(resp):
            return resp
        if intento == 2:
            log.error("Re-login no restauró el acceso al portal")
            alert_once("relogin", "⚠️ Re-login no restauró el acceso al portal.", cooldown_min=360)
            return None
        log.warning("Session expired, re-login...")
        _session = None
        session = do_login()
        if not session:
            alert_once("relogin", "⚠️ Sesión expirada y re-login fallido.", cooldown_min=360)
            return None
    return None


# --- Descubrimiento dinámico de aulas ---
_AULA_SID_RE = re.compile(r"aula\.php\?sid=([^&\"'\s]+)")


def discover_aulas():
    """Lista viva de aulas de la familia, leída de /aulas.php tras el login.
    Devuelve (aulas, soup) donde cada aula es {sid, name, url}. Sustituye a la
    URL fija del .env: si el niño cambia de aula o de curso, sale sola."""
    url = f"{PORTAL_ORIGIN}/aulas.php"
    resp = get_authed(url)
    if resp is None:
        raise RuntimeError(f"no pude leer {url}")

    soup = BeautifulSoup(resp.text, "html.parser")
    aulas, seen = [], set()
    for a_tag in soup.find_all("a", href=True):
        m = _AULA_SID_RE.search(a_tag["href"])
        if not m:
            continue
        sid = m.group(1)
        if sid in seen:
            continue
        seen.add(sid)
        aulas.append({
            "sid": sid,
            "name": a_tag.get_text(" ", strip=True) or sid,
            "url": urljoin(resp.url, a_tag["href"]),
        })

    if AULAS_INCLUDE:
        try:
            filtro = re.compile(AULAS_INCLUDE, re.IGNORECASE)
            aulas = [a for a in aulas if filtro.search(a["name"])]
        except re.error as e:
            log.error(f"AULAS_INCLUDE no es una regex válida ({err_txt(e)}) — se ignora el filtro")

    log.info(f"Aulas descubiertas: {[a['name'] for a in aulas]}")
    return aulas, soup


def fetch_aula(aula):
    """Página del muro de un aula, o None si no se puede usar."""
    resp = get_authed(aula["url"])
    if resp is None:
        return None
    # Un sid que ya no existe NO da 404: el portal rebota a la home y seguiríamos
    # leyendo el muro equivocado en silencio. Comprobarlo por la URL final.
    if "aula.php" not in resp.url:
        log.error(f"Aula '{aula['name']}' (sid={aula['sid']}): el portal rebota a {enmascara(resp.url)}")
        alert_once(
            f"aula-sid-{aula['sid']}",
            f"⚠️ El aula «{html.escape(aula['name'])}» ya no existe en el portal "
            f"(rebota a la portada). La salto; si vuelve, se re-descubre sola.",
            cooldown_min=1440)
        return None
    return resp


def report_aula_changes(state, aulas, silent=False):
    """Avisa cuando cambia la lista de aulas (curso nuevo, alta, baja, renombrado)."""
    current = {a["sid"]: a["name"] for a in aulas}
    previous = state.get("aulas") or {}
    state["aulas"] = current
    if not previous or silent:
        return
    added = [n for s, n in current.items() if s not in previous]
    removed = [n for s, n in previous.items() if s not in current]
    renamed = [f"{previous[s]} → {n}" for s, n in current.items()
               if s in previous and previous[s] != n]
    if not (added or removed or renamed):
        return
    lines = ["🔄 <b>Cambios en las aulas del portal</b>"]
    if added:
        lines.append("➕ Nuevas: " + ", ".join(html.escape(x) for x in added))
    if removed:
        lines.append("➖ Ya no están: " + ", ".join(html.escape(x) for x in removed))
    if renamed:
        lines.append("✏️ Renombradas: " + ", ".join(html.escape(x) for x in renamed))
    lines.append("<i>No hay que tocar nada: el monitor sigue las aulas que devuelve el portal.</i>")
    notify_ha("status", message="\n".join(lines))


def update_agenda_url(state, soup, silent=False):
    """La agenda es por familia y su enlace está en el pie de CUALQUIER página
    del portal, no dentro de un aula concreta: así no depende del aula."""
    agenda_url = extract_agenda_url(soup)
    if not agenda_url:
        if not state.get("agenda_url"):
            log.warning("No agenda URL found and none saved in state")
            alert_once("agenda-url",
                       "⚠️ No encuentro el enlace de la agenda en el portal.", cooldown_min=720)
        return
    old_url = state.get("agenda_url")
    if old_url != agenda_url:
        log.info(f"Agenda URL updated: {enmascara(agenda_url)}")
        if old_url and not silent:
            notify_ha("status", message="🔄 URL de agenda actualizada automáticamente.")
    state["agenda_url"] = agenda_url


# --- Module 1: Muro del Aula ---
_muro_fail_count = 0


def _extract_pub_media(session, pub_id):
    """Descarga el ZIP de una publicación y extrae sus medias a MEDIA_DIR.
    Devuelve (media_list, skipped) o lanza excepción si la descarga/extracción falla.
    NO envía nada: así un fallo aquí permite reintentar sin duplicar mensajes."""
    zip_url = f"{PORTAL_ORIGIN}/descargar_publicacion.php?pub={pub_id}"
    zip_resp = session.get(zip_url, timeout=120)
    zip_resp.raise_for_status()
    if "zip" not in zip_resp.headers.get("Content-Type", ""):
        log.warning(f"pub={pub_id}: not a ZIP response")
        return None, 0  # respuesta rara del servidor: sin media que extraer

    media_list, skipped = [], 0
    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
        files = zf.namelist()
        log.info(f"pub={pub_id}: ZIP with {len(files)} files")
        for fname in files:
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext in ("jpg", "jpeg", "png", "webp", "avif"):
                kind = "photo"
            elif ext in ("mp4", "mov", "avi", "webm"):
                kind = "video"
            else:
                log.info(f"Skipping unknown file type: {fname}")
                skipped += 1
                continue
            safe_name = f"muro_{pub_id[:8]}_{fname}"
            path = MEDIA_DIR / safe_name
            path.write_bytes(zf.read(fname))
            media_list.append({"path": path, "kind": kind, "caption": None})
    return media_list, skipped


def extract_post_text(post):
    """Texto de una publicación del muro, sin el relleno de los reproductores."""
    # Quitar multimedia: el <p> de fallback dentro de <video>/<audio>
    # ("Tu navegador no implementa el elemento video.") NO es texto del post
    for media in post.find_all(["video", "audio", "source", "iframe"]):
        media.decompose()
    # <br> -> salto de línea real (conserva los párrafos del post)
    for br in post.find_all("br"):
        br.replace_with("\n")
    parts = []
    for p in post.find_all("p"):
        t = "\n".join(ln.strip() for ln in p.get_text().split("\n")).strip()
        while "\n\n\n" in t:           # colapsa 3+ saltos a párrafo doble
            t = t.replace("\n\n\n", "\n\n")
        if len(t) > 20:
            parts.append(t)
    return "\n\n".join(parts).strip()


def check_muro(state, first_run=False):
    global _muro_fail_count
    # Si el baseline inicial nunca llegó a guardarse (p.ej. fallo de red en el arranque),
    # seguir en modo baseline: sin esto, el siguiente ciclo trataba TODO el histórico
    # del muro como "nuevo" y lo enviaba entero a Telegram.
    first_run = first_run or not state.get("baseline_done", False)
    log.info("Checking muro..." + (" (baseline)" if first_run else ""))
    if not get_session():
        alert_once("login", "⚠️ No hay sesion activa. Error de login.", cooldown_min=360)
        return

    try:
        aulas, portal_soup = discover_aulas()
    except Exception as e:
        _muro_fail_count += 1
        log.error(f"Muro fetch error ({_muro_fail_count} seguidos): {err_txt(e)}")
        # Solo alertar a partir del 2º fallo consecutivo (los hipos puntuales se auto-resuelven)
        if _muro_fail_count >= 2:
            alert_once("muro-fetch", "⚠️ Error listando las aulas del portal (2+ intentos).", cooldown_min=360)
        return

    if not aulas:
        alert_once("aulas-vacias",
                   "⚠️ El portal no devuelve ninguna aula. ¿Ha cambiado la web o la matrícula?",
                   cooldown_min=720)
        return

    _muro_fail_count = 0
    report_aula_changes(state, aulas, silent=first_run)
    # La agenda se saca del portal, no de un aula: así no depende de acertar con el aula.
    update_agenda_url(state, portal_soup, silent=first_run)

    # Recoger publicaciones de TODAS las aulas descubiertas. El pub id es único
    # en el portal, así que un post que aparezca en dos aulas no se duplica.
    all_pub_ids = set()
    new_pubs = []
    for aula in aulas:
        resp = fetch_aula(aula)
        if resp is None:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        n_aula = 0
        for post in soup.find_all("div", class_="user-post"):
            dl_link = post.find("a", href=lambda h: h and "descargar_publicacion" in h)
            if not dl_link:
                continue
            pub_param = dl_link["href"].split("pub=")[-1]
            n_aula += 1
            if pub_param in all_pub_ids:
                continue
            all_pub_ids.add(pub_param)
            if pub_param not in state.get("pub_ids", []):
                new_pubs.append({"pub": pub_param,
                                 "text": extract_post_text(post),
                                 "aula": aula["name"]})
        log.info(f"  Aula '{aula['name']}': {n_aula} publicaciones")

    log.info(f"Muro: {len(all_pub_ids)} publicaciones en {len(aulas)} aula(s), "
             f"{len(new_pubs)} nuevas")

    if first_run:
        state["pub_ids"] = list(all_pub_ids)
        state["baseline_done"] = True
        log.info("Muro baseline saved")
    else:
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

        for pub in new_pubs:
            pub_id = pub["pub"]
            fails = state.setdefault("pub_fail_counts", {})

            # Fase 1: descargar y extraer (sin enviar nada) — si falla, se REINTENTA
            # en el próximo ciclo en vez de marcar la publicación como vista y perderla.
            try:
                media_list, _ = _extract_pub_media(get_session(), pub_id)
            except Exception as e:
                n = fails.get(pub_id, 0) + 1
                fails[pub_id] = n
                if n >= PUB_MAX_ATTEMPTS:
                    log.error(f"pub={pub_id}: {n} intentos fallidos, se descarta: {err_txt(e)}")
                    alert_once(f"pub-{pub_id}",
                               f"⚠️ No pude descargar una publicación del muro tras {n} intentos (pub={pub_id}).")
                    state.setdefault("pub_ids", []).append(pub_id)
                    fails.pop(pub_id, None)
                else:
                    log.warning(f"pub={pub_id}: fallo de descarga (intento {n}/{PUB_MAX_ATTEMPTS}), se reintentará: {err_txt(e)}")
                continue

            # Fase 2: entregar. A partir de aquí marcamos vista SIEMPRE (reintentar
            # duplicaría mensajes); los fallos parciales se avisan por alerta.
            undelivered = 0
            if pub["text"]:
                origen = f" · {html.escape(pub['aula'])}" if pub.get("aula") else ""
                msg = f"📋 <b>Nueva publicación</b>{origen} ({now_str})\n\n{html.escape(pub['text'])}"
                if tg_send_message(msg, TG_THREAD_MURO) is None:
                    undelivered += 1
                time.sleep(1)

            if media_list:
                undelivered += send_media_batch(media_list, TG_THREAD_MURO)

            state.setdefault("pub_ids", []).append(pub_id)
            fails.pop(pub_id, None)
            if undelivered:
                alert_once(f"pubsend-{pub_id}",
                           f"⚠️ Publicación {pub_id}: {undelivered} elemento(s) no se pudieron enviar a Telegram.")

    state["last_muro_check"] = datetime.now().isoformat()
    save_state(state)


# --- Module 2: Agenda ---
FIELD_EMOJI = {
    "Desayuno": "🍽️", "Comida": "🍽️", "Merienda": "🍽️", "Cena": "🍽️",
    "Obs. Desayuno": "🍽️", "Obs. Comida": "🍽️",
    "Obs. Merienda": "🍽️", "Obs. Cena": "🍽️",
    "Deposiciones Mañana": "🧼", "Deposiciones Tarde": "🧼", "Descanso": "🧼",
    "Observaciones": "📝", "Observaciones Familias": "📝",
    "Petición de los padres": "🏥", "Petición de las familias": "🏥",
    "Petición de consultas internas": "🏥", "Hospital": "🏥",
    "Piscina": "🏊",
}
# Orden de campos para el mensaje diario
AGENDA_SECTIONS = [
    ("🍽️ <b>Comidas</b>", [
        "Desayuno", "Obs. Desayuno",
        "Comida", "Obs. Comida",
        "Merienda", "Obs. Merienda",
        "Cena", "Obs. Cena",
    ]),
    ("🧼 <b>Higiene y Descanso</b>", [
        "Deposiciones Mañana", "Deposiciones Tarde", "Descanso",
    ]),
    ("📝 <b>Observaciones</b>", [
        "Observaciones", "Observaciones Familias",
    ]),
    ("🏥 <b>Enfermería</b>", [
        "Petición de los padres", "Petición de las familias",
        "Petición de consultas internas", "Hospital",
    ]),
    ("🏊 <b>Actividades</b>", [
        "Piscina",
    ]),
]
SKIP_LABELS = {"Observaciones Padres", "Observaciones audio", "Horario"}
SIN_DATOS_PATTERNS = ["sin datos disponibles", "no hay datos"]
# Etiquetas que sabemos formatear. Cualquier otra que aparezca en la web es un
# campo nuevo que NO se estaría enviando: por eso se avisa (ver report_agenda_changes).
KNOWN_AGENDA_LABELS = set(FIELD_EMOJI) | SKIP_LABELS


def is_empty_value(val):
    """True si el valor está vacío o es un placeholder sin datos."""
    if not val:
        return True
    v = val.strip().lower()
    return not v or any(p in v for p in SIN_DATOS_PATTERNS)


def build_agenda_message(snapshot):
    """Construye el mensaje completo de agenda del dia."""
    today_str = datetime.now().strftime("%d/%m/%Y")
    lines = [f"📋 <b>Agenda del día</b> ({today_str})\n"]

    for section_title, fields in AGENDA_SECTIONS:
        section_lines = []
        for field in fields:
            val = snapshot.get(field, "")
            if is_empty_value(val):
                continue
            # Escapar el valor (parse_mode html): un &, < o > rompería el mensaje
            safe_val = html.escape(val)
            # Para observaciones de comida, indentar como sub-campo
            if field.startswith("Obs. "):
                section_lines.append(f"    <i>↳ {safe_val}</i>")
            else:
                section_lines.append(f"  • <b>{field}</b>: {safe_val}")

        if section_lines:
            lines.append(section_title)
            lines.extend(section_lines)
            lines.append("")

    if len(lines) <= 1:
        return None  # No enviar si todo está vacío

    # Hora de ultima actualizacion
    lines.append(f"<i>Actualizado: {datetime.now().strftime('%H:%M')}</i>")

    return "\n".join(lines)


def parse_agenda(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    data = {}
    for item in soup.find_all("div", class_="info-item"):
        titulo_div = item.find("div", class_="info-titulo")
        if not titulo_div:
            continue
        span = titulo_div.find("span")
        if not span:
            continue
        label = span.get_text(strip=True)
        if label in SKIP_LABELS:
            continue
        info_textos = item.find_all("div", class_="info-texto", recursive=False)
        if not info_textos:
            continue
        first = info_textos[0]
        inner = first.find("div", recursive=False)
        if inner and not inner.get("class"):
            value = inner.get_text(strip=True)
        else:
            value = first.get_text(strip=True)
        data[label] = value
        obs = item.find("div", class_="info-observaciones")
        if obs:
            data[f"Obs. {label}"] = obs.get_text(strip=True)
    return data


# --- Horario de la agenda (24-sep-2026): segunda fuente para el fichaje ---
# La agenda trae un apartado «Horario»: «Entrada: No disponible / Salida: No disponible» si no se
# ha fichado, o la hora si si. NO se envia a Telegram (sigue en SKIP_LABELS); solo se lee para que
# fichaje.py confirme si hay entrada. Nunca se registran nombres ni la URL con la sesion.
_RE_H_ENTRADA = re.compile(r"Entrada:\s*(\d{1,2}:\d{2})")
_RE_H_SALIDA = re.compile(r"Salida:\s*(\d{1,2}:\d{2})")
AGENDA_HORARIO_MAX_MIN = 35          # reutilizar la lectura de la agenda si es de hoy y mas reciente
_horario_lock = threading.Lock()
_horario_cache = {}                  # {"fecha","entrada","salida","ok","leido": datetime}


def _horario_de_texto(texto):
    me, ms = _RE_H_ENTRADA.search(texto), _RE_H_SALIDA.search(texto)
    return {"entrada": me.group(1) if me else None, "salida": ms.group(1) if ms else None,
            "ok": "Entrada" in texto}


def parse_horario(page_html):
    """Del HTML de la agenda saca {"entrada","salida","ok"}. «No disponible» (o sin hora) -> None;
    ok=False si la pagina no trae el apartado Horario.

    Estructura real (medida el 24-sep-2026): una pestaña div.tabs-alumno > div.tab.cHorario
    («Horario», se ignora) y, en div.contenido-info, un div.info-titulo.cHorario > span «Horario»
    seguido de uno o varios div.info-texto(.corto) HERMANOS («Entrada: …», «Salida: …») hasta el
    siguiente div.info-titulo. Sin div.info-item alrededor (tambien se acepta si lo hay).
    Respaldo: el texto plano de div.contenido-info entre «Horario» y la siguiente etiqueta conocida."""
    soup = BeautifulSoup(page_html, "html.parser")
    for tit in soup.find_all("div", class_="info-titulo"):
        span = tit.find("span")
        etiqueta = (span or tit).get_text(strip=True)
        if etiqueta != "Horario":
            continue
        textos = []
        for sib in tit.find_next_siblings():
            clases = sib.get("class") or []
            if "info-titulo" in clases:
                break                                   # empieza el apartado siguiente
            if "info-texto" in clases:
                textos.append(sib.get_text(" ", strip=True))
        if textos:
            return _horario_de_texto(" ".join(textos))
    cont = soup.find("div", class_="contenido-info")
    if cont:
        plano = cont.get_text(" ", strip=True)
        m = re.search(r"\bHorario\b", plano)
        if m:
            resto = plano[m.end():]
            fin = len(resto)
            for lab in KNOWN_AGENDA_LABELS - {"Horario"}:
                k = re.search(r"\b" + re.escape(lab) + r"\b", resto)
                if k:
                    fin = min(fin, k.start())
            return _horario_de_texto(resto[:fin])
    return {"entrada": None, "salida": None, "ok": False}


def _guardar_horario(h, cuando=None):
    cuando = cuando or datetime.now()
    with _horario_lock:
        _horario_cache.clear()
        _horario_cache.update(h, fecha=cuando.strftime("%Y-%m-%d"), leido=cuando)


def agenda_horario(forzar=False, max_min=AGENDA_HORARIO_MAX_MIN):
    """Horario de hoy segun la agenda: {"entrada": "HH:MM"|None, "salida": "HH:MM"|None,
    "fecha": "YYYY-MM-DD", "ok": bool}. Reutiliza la ultima lectura (la de check_agenda o la
    anterior) si es de hoy y tiene menos de max_min minutos; si no, o con forzar, descarga la
    agenda una vez. Nunca lanza: ante cualquier fallo devuelve ok=False."""
    ahora = datetime.now()
    hoy = ahora.strftime("%Y-%m-%d")
    with _horario_lock:
        c = dict(_horario_cache)
    if (not forzar and c.get("fecha") == hoy and c.get("leido")
            and ahora - c["leido"] < timedelta(minutes=max_min)):
        return {k: c.get(k) for k in ("entrada", "salida", "fecha", "ok")}
    try:
        agenda_url = load_state().get("agenda_url")
        if not agenda_url:
            return {"entrada": None, "salida": None, "fecha": hoy, "ok": False}
        resp = requests.get(agenda_url, timeout=30)
        resp.raise_for_status()
        h = parse_horario(resp.content.decode("iso-8859-1"))
    except Exception as e:
        log.warning(f"Agenda (horario): no pude leerla: {err_txt(e)}")
        return {"entrada": None, "salida": None, "fecha": hoy, "ok": False}
    _guardar_horario(h, ahora)
    log.info(f"Agenda (horario): entrada={h['entrada'] or 'no disponible'} ok={h['ok']}")
    return {"entrada": h["entrada"], "salida": h["salida"], "fecha": hoy, "ok": h["ok"]}


def report_agenda_changes(state, current, silent=False):
    """Avisa si la web añade campos que el monitor no sabe formatear. Sin esto,
    un renombrado en el portal (p.ej. "Petición de los padres" -> "de las
    familias") se traga el campo en silencio."""
    unknown = sorted(set(current) - KNOWN_AGENDA_LABELS)
    already = set(state.get("agenda_unknown_labels") or [])
    nuevos = [lab for lab in unknown if lab not in already]
    state["agenda_unknown_labels"] = unknown
    if not nuevos or silent:
        return
    notify_ha("status", message=(
        "🆕 <b>Campos nuevos en la agenda</b>\n"
        + "\n".join(f"  • {html.escape(lab)}" for lab in nuevos)
        + "\n\n<i>No se están enviando todavía: hay que añadirlos a "
          "FIELD_EMOJI y AGENDA_SECTIONS en monitor.py.</i>"))


def alert_if_agenda_empty(state, current):
    """Avisa una vez al día si, en día lectivo y pasada la hora tope, la agenda
    sigue entera sin datos. La agenda dejó de llegar sin que nada lo dijera:
    el mensaje no se envía cuando todo está vacío, así que el silencio parecía
    normalidad."""
    if not AGENDA_EMPTY_ALERT_HOUR or not current:
        return
    if not is_working_time() or datetime.now().hour < AGENDA_EMPTY_ALERT_HOUR:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("agenda_empty_alert_date") == today:
        return
    if any(not is_empty_value(v) for v in current.values()):
        return
    state["agenda_empty_alert_date"] = today
    notify_ha("alert", message=(
        f"⚠️ <b>Agenda vacía</b>\nHoy no hay ni un dato en la agenda "
        f"({len(current)} campos leídos, todos «sin datos»). Si en la app sí los "
        f"ves, algo ha cambiado en la web."))


def check_agenda(state, first_run=False):
    agenda_url = state.get("agenda_url")
    if not agenda_url:
        log.warning("No agenda URL available — skipping agenda check")
        return

    log.info(f"Checking agenda: {enmascara(agenda_url)[:80]}")

    try:
        resp = requests.get(agenda_url, timeout=30)
        resp.raise_for_status()
        page_html = resp.content.decode("iso-8859-1")
    except Exception as e:
        log.error(f"Agenda fetch error: {err_txt(e)}")
        return

    current = parse_agenda(page_html)
    previous = state.get("agenda_snapshot", {})
    try:
        _guardar_horario(parse_horario(page_html))      # para agenda_horario(): sin otra descarga
    except Exception as e:
        log.warning(f"Agenda (horario): no pude interpretarlo: {err_txt(e)}")
    log.info(f"Agenda fields: {list(current.keys())}")

    if not current:
        log.error("Agenda: la página no devuelve ningún campo reconocible")
        alert_once("agenda-parse",
                   "⚠️ No consigo leer ningún campo de la agenda. ¿Ha cambiado la web?",
                   cooldown_min=720)
    else:
        report_agenda_changes(state, current, silent=first_run)
        if not first_run:
            alert_if_agenda_empty(state, current)

    if first_run:
        state["agenda_snapshot"] = current
        # Sin esto, el primer daily_reset_if_needed veía last_agenda_date=None y
        # borraba el baseline minutos después → agenda espuria el primer día.
        state["last_agenda_date"] = datetime.now().strftime("%Y-%m-%d")
        log.info("Agenda baseline saved")
    else:
        # Comprobar si hay cambios reales
        has_changes = False
        for field in FIELD_EMOJI:
            new_val = current.get(field, "")
            old_val = previous.get(field, "")
            if not is_empty_value(new_val) and old_val != new_val:
                has_changes = True
                break

        sent_ok = True
        if has_changes:
            msg = build_agenda_message(current)
            if msg is None:
                log.info("Agenda: changes detected but all fields still empty, skipping")
            else:
                # Enviar PRIMERO y borrar los antiguos después: si el envío falla,
                # el mensaje anterior sigue en el grupo (antes se borraba antes de
                # enviar y un fallo dejaba la agenda del día desaparecida).
                new_ids = tg_send_agenda_to_all(msg)
                if any(new_ids):
                    old_msg_ids = get_agenda_message_ids(state)
                    tg_delete_agenda_in_all(old_msg_ids)
                    state["agenda_message_ids"] = new_ids
                    state.pop("agenda_message_id", None)
                    log.info(f"Agenda message sent/updated to {len(AGENDA_TARGETS)} target(s)")
                else:
                    # Snapshot NO se actualiza: el próximo ciclo verá los mismos
                    # cambios y reintentará el envío.
                    sent_ok = False
                    log.error("Agenda: envío falló en todos los destinos; se reintentará en el próximo ciclo")

        if sent_ok:
            state["agenda_snapshot"] = current

    state["last_agenda_check"] = datetime.now().isoformat()
    save_state(state)


# --- Self-test (SELF_TEST=1): prueba la cadena completa sin entrar en el bucle ---
def run_self_test():
    log.info("=== SELF-TEST ===")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    tg_send_message("🧪 <b>[TEST]</b> Monitor guardería standalone — probando envío directo a Telegram…", TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)
    session = get_session()
    if not session:
        tg_send_message("❌ <b>[TEST]</b> Login en Workandlife FALLÓ. Revisa WL_USER/WL_PASS.", TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)
        return
    try:
        aulas, portal_soup = discover_aulas()
    except Exception as e:
        tg_send_message(f"❌ <b>[TEST]</b> Login OK pero no pude listar las aulas: {html.escape(err_txt(e))}",
                        TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)
        return
    nombres = ", ".join(html.escape(a["name"]) for a in aulas) or "(ninguna)"
    agenda_url = extract_agenda_url(portal_soup)
    tg_send_message(
        f"✅ <b>[TEST]</b> Login OK en {html.escape(PORTAL_ORIGIN)}\n"
        f"🏫 Aulas descubiertas: {nombres}\n"
        f"📋 Agenda: {'✅ enlace encontrado' if agenda_url else '❌ no encontrada'}",
        TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)

    target = None
    for aula in aulas:
        resp = fetch_aula(aula)
        if resp is None:
            continue
        soup = BeautifulSoup(resp.content, "html.parser")
        posts = soup.find_all("div", class_="user-post")
        log.info(f"self-test: aula '{aula['name']}', {len(posts)} publicaciones")
        for post in posts:
            dl = post.find("a", href=lambda h: h and "descargar_publicacion" in h)
            if dl:
                target = (post, dl["href"].split("pub=")[-1])
                break
        if target:
            break
    if not target:
        tg_send_message("⚠️ <b>[TEST]</b> Login OK, pero ningún aula tiene publicaciones con descarga (¿muros vacíos?).", TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)
        return
    post, pub_id = target
    for media in post.find_all(["video", "audio", "source", "iframe"]):
        media.decompose()
    for br in post.find_all("br"):
        br.replace_with("\n")
    parts = []
    for p in post.find_all("p"):
        t = "\n".join(ln.strip() for ln in p.get_text().split("\n")).strip()
        while "\n\n\n" in t:
            t = t.replace("\n\n\n", "\n\n")
        if len(t) > 20:
            parts.append(t)
    txt = "\n\n".join(parts).strip()
    if txt:
        tg_send_message(f"📋 <b>[TEST] Última publicación</b>\n\n{html.escape(txt)}", TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)
    # Ejercita el MISMO camino que producción: extracción + envío en álbumes
    try:
        media_list, _ = _extract_pub_media(session, pub_id)
    except Exception as e:
        log.error(f"self-test ZIP error: {err_txt(e)}")
        media_list = None
    n_media = failed = 0
    if media_list:
        n_media = len(media_list)
        if media_list:
            media_list[0]["caption"] = "🧪 [TEST] álbum"
        # Enviar al hilo de sistema, no al muro
        failed = send_media_batch(media_list, TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)
    tg_send_message(
        f"🧪 <b>[TEST] Resultado:</b> texto={'✅' if txt else '—'} "
        f"· medios={n_media - failed}/{n_media} enviados (en álbumes)\n\n"
        f"<i>Envío self-contained de TODOS los medios de la última publicación, SIN Home Assistant.</i>",
        TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)
    log.info("=== SELF-TEST done ===")


# --- Main loop ---
import fichaje  # 23-sep-2026: fichaje de entrada con bot propio (ver fichaje.py)
fichaje.agenda_horario = agenda_horario   # 24-sep-2026: 2.ª fuente (Horario de la agenda); sin import circular


def main():
    log.info("=== Guarderia Monitor starting ===")
    if os.getenv("SELF_TEST") == "1":
        run_self_test()
        return
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    state = load_state()
    first_run = not state.get("baseline_done", False)

    if first_run:
        log.info("First run — baseline (no notifications)")
        check_muro(state, first_run=True)
        state = load_state()
        check_agenda(state, first_run=True)
        notify_ha("status", message="✅ Monitor guardería iniciado.")
    else:
        log.info("Resuming from saved state")
        check_muro(state, first_run=False)
        state = load_state()
        notify_ha("status", message="🔄 Monitor guardería reiniciado.")

    # Primer check con jitter inicial corto
    next_muro = datetime.now() + random_wait((1, 3))
    next_agenda = datetime.now() + random_wait((1, 3))
    next_evening = next_evening_sweep() if EVENING_MURO_HOUR else None
    next_prune = datetime.now() + timedelta(minutes=5)

    log.info(f"Fichaje guarderia: {'ACTIVO a las ' + fichaje.HORA if fichaje.ENABLED else 'desactivado (faltan secretos)'}")
    log.info(
        f"Scheduler: muro ~{MURO_INTERVAL[0]}-{MURO_INTERVAL[1]}min, "
        f"agenda ~{AGENDA_INTERVAL[0]}-{AGENDA_INTERVAL[1]}min, {WORK_HOUR_START:02d}:00-{WORK_HOUR_END:02d}:00"
    )

    while True:
        # Red de seguridad global: sin ella, cualquier excepción no prevista
        # (red, disco, HTML inesperado) mataba el contenedor en bucle.
        try:
            now = datetime.now()

            if is_working_time():
                if now >= next_muro:
                    state = load_state()
                    check_muro(state)
                    wait = random_wait(MURO_INTERVAL)
                    next_muro = now + wait
                    log.info(f"Next muro in {int(wait.total_seconds() / 60)}min")

                if now >= next_agenda:
                    state = load_state()
                    daily_reset_if_needed(state)
                    state = load_state()
                    check_agenda(state)
                    wait = random_wait(AGENDA_INTERVAL)
                    next_agenda = now + wait
                    log.info(f"Next agenda in {int(wait.total_seconds() / 60)}min")
            else:
                if now.hour >= WORK_HOUR_END and next_muro < now:
                    tomorrow_7 = (now + timedelta(days=1)).replace(hour=WORK_HOUR_START, minute=0, second=0)
                    next_muro = tomorrow_7 + random_wait((1, 10))
                    next_agenda = tomorrow_7 + random_wait((1, 5))
                    log.info(f"Outside hours. Next checks at ~{WORK_HOUR_START:02d}:0x tomorrow")

            # Pasada nocturna del muro (cualquier día) para tardes/fines de semana
            if next_evening and now >= next_evening:
                log.info("Pasada nocturna del muro")
                state = load_state()
                check_muro(state)
                next_evening = next_evening_sweep()
                log.info(f"Próxima pasada nocturna: {next_evening:%Y-%m-%d %H:%M}")

            # Fichaje de la guarderia (23-sep-2026): a FICHAJE_HORA en dia lectivo
            # pregunta por Telegram (bot propio) y ficha solo si se responde que si.
            # Va fuera de is_working_time() a proposito: escucha los botones siempre.
            fichaje.tick(now, lambda: now.weekday() < 5 and not is_spanish_holiday(now))

            # Limpieza diaria de la caché de media
            if now >= next_prune:
                prune_media()
                next_prune = now + timedelta(days=1)

        except Exception as e:
            # sin traceback por defecto: el mensaje de la excepcion (que sale en el traceback) puede
            # llevar la URL de Telegram con el token; con DEBUG=1 o FICHAJE_DEBUG=1 se muestra entero
            log.error(f"Error no controlado en el bucle principal: {err_txt(e)}")
            if "1" in (os.getenv("DEBUG", ""), os.getenv("FICHAJE_DEBUG", "")):
                log.exception("traceback (DEBUG)")
            alert_once("main-loop", f"⚠️ Monitor guardería: error no controlado ({fichaje._err(e)}). Sigo en marcha.")  # _err: nunca str(e), puede llevar URLs con sesion
            # No reintentar inmediatamente en bucle si el fallo es persistente
            floor = datetime.now() + timedelta(minutes=5)
            next_muro = max(next_muro, floor)
            next_agenda = max(next_agenda, floor)

        time.sleep(30)


if __name__ == "__main__":
    main()
