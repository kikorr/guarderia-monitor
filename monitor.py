import os
import io
import json
import time
import random
import logging
import zipfile
import html
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# --- Config ---
MURO_URL = os.getenv("MURO_URL", "https://TUCENTRO.workandlife.com/aulas/aula.php?sid=XXXX")
WL_USER = os.getenv("WL_USER", "")
WL_PASS = os.getenv("WL_PASS", "")
WL_LOGIN_URL = "https://comunidaddefamilias.com"
# Telegram (envío directo, sin Home Assistant)
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
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

# Origen del dominio del muro
_parts = MURO_URL.split("/")
MURO_ORIGIN = f"{_parts[0]}//{_parts[2]}"

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

# Asegura que /data existe antes de configurar el log en fichero
Path("/data").mkdir(parents=True, exist_ok=True)

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("guarderia")


# --- State ---
def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "pub_ids": [],
        "agenda_url": None,
        "agenda_snapshot": {},
        "agenda_message_ids": [],
        "last_agenda_date": None,
        "last_muro_check": None,
        "last_agenda_check": None,
    }


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    tmp.replace(STATE_FILE)


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
    elif event_type in ("alert", "status"):
        tg_send_message(payload.get("message", ""), TG_THREAD_SISTEMA, chat_id=SISTEMA_CHAT_ID)
    else:
        log.warning(f"Evento desconocido: {event_type}")


# --- Telegram directo (solo agenda editable - necesita delete/edit) ---
def tg_send_message(text, thread_id, chat_id=None):
    """Envia mensaje a Telegram y devuelve message_id. Usa TG_CHAT_ID si chat_id es None."""
    target_chat = chat_id if chat_id is not None else TG_CHAT_ID
    try:
        body = {"chat_id": target_chat, "text": text, "parse_mode": "HTML"}
        if thread_id:
            body["message_thread_id"] = int(thread_id)
        r = requests.post(
            f"{TG_API}/sendMessage",
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        msg_id = r.json().get("result", {}).get("message_id")
        log.info(f"TG sent message_id={msg_id} chat={target_chat} thread={thread_id}")
        return msg_id
    except Exception as e:
        log.error(f"TG send error chat={target_chat} thread={thread_id}: {e}")
        return None


def tg_delete_message(message_id, chat_id=None):
    """Borra un mensaje de Telegram. Usa TG_CHAT_ID si chat_id es None."""
    target_chat = chat_id if chat_id is not None else TG_CHAT_ID
    try:
        r = requests.post(
            f"{TG_API}/deleteMessage",
            json={"chat_id": target_chat, "message_id": message_id},
            timeout=10,
        )
        log.info(f"TG deleted message_id={message_id} chat={target_chat} (ok={r.json().get('ok')})")
    except Exception as e:
        log.warning(f"TG delete error chat={target_chat} mid={message_id}: {e}")


def tg_send_file(method, field, file_path, caption, thread_id):
    """Sube una foto/vídeo directamente a Telegram (multipart). method=sendPhoto|sendVideo."""
    try:
        body = {"chat_id": TG_CHAT_ID}
        if caption:
            body["caption"] = caption
            body["parse_mode"] = "HTML"
        if thread_id:
            body["message_thread_id"] = int(thread_id)
        with open(file_path, "rb") as fh:
            r = requests.post(f"{TG_API}/{method}", data=body,
                              files={field: fh}, timeout=180)
        r.raise_for_status()
        log.info(f"TG {method} ok ({Path(file_path).name})")
        return True
    except Exception as e:
        log.error(f"TG {method} error ({file_path}): {e}")
        return False


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


def is_working_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    if is_spanish_holiday(now):
        return False
    return 7 <= now.hour < 17


def random_wait(interval):
    return timedelta(minutes=random.randint(*interval))


def next_evening_sweep():
    """Próxima pasada nocturna del muro (~EVENING_MURO_HOUR, jitter 0-25min)."""
    now = datetime.now()
    target = now.replace(hour=int(EVENING_MURO_HOUR), minute=random.randint(0, 25),
                         second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


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
            log.info(f"Agenda URL found: {href}")
            return href
        link_text = a_tag.get_text(strip=True).lower()
        if "agenda" in link_text and "workandlife" in href:
            log.info(f"Agenda URL found (by text): {href}")
            return href
    for iframe in soup.find_all("iframe", src=True):
        if "agenda2.workandlife.com" in iframe["src"]:
            log.info(f"Agenda URL found (iframe): {iframe['src']}")
            return iframe["src"]
    return None


# --- Login / Session ---
import re

_session = None


def get_session():
    """Devuelve una sesion autenticada, haciendo login si es necesario."""
    global _session
    if _session:
        return _session
    return do_login()


def do_login():
    """Login en comunidaddefamilias.com y devuelve sesion autenticada."""
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
            notify_ha("alert", message="⚠️ Login Workandlife fallido. Revisa usuario/contraseña.")
            return None

        log.info("Login OK")
        _session = s
        return s
    except Exception as e:
        log.error(f"Login error: {e}")
        return None


# --- Module 1: Muro del Aula ---
def check_muro(state, first_run=False):
    global _session
    log.info("Checking muro...")
    session = get_session()
    if not session:
        notify_ha("alert", message="⚠️ No hay sesion activa. Error de login.")
        return

    try:
        resp = session.get(MURO_URL, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        log.error(f"Muro fetch error: {e}")
        notify_ha("alert", message="⚠️ Error accediendo al muro del aula.")
        return

    # Si la sesion expiro, relogin
    if "login" in resp.url.lower() or len(resp.text) < 500 or "user-post" not in resp.text:
        log.warning("Session expired, re-login...")
        _session = None
        session = do_login()
        if not session:
            notify_ha("session_expired", message="⚠️ Sesión expirada y re-login fallido.")
            return
        resp = session.get(MURO_URL, timeout=30)
        if len(resp.text) < 500:
            log.error("Re-login did not restore access")
            tg_send_message("⚠️ Re-login no restauró el acceso al muro.", TG_THREAD_ALERTAS)
            return

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extraer URL de la agenda
    agenda_url = extract_agenda_url(soup)
    if agenda_url:
        old_url = state.get("agenda_url")
        if old_url != agenda_url:
            log.info(f"Agenda URL updated: {agenda_url}")
            if old_url and not first_run:
                notify_ha("status", message="🔄 URL de agenda actualizada automáticamente.")
        state["agenda_url"] = agenda_url
    elif not state.get("agenda_url"):
        log.warning("No agenda URL found on muro page and none saved in state")

    # Recoger publicaciones con su link de descarga ZIP
    all_pub_ids = set()
    new_pubs = []
    for post in soup.find_all("div", class_="user-post"):
        dl_link = post.find("a", href=lambda h: h and "descargar_publicacion" in h)
        if not dl_link:
            continue
        pub_param = dl_link["href"].split("pub=")[-1]
        all_pub_ids.add(pub_param)
        if pub_param not in state.get("pub_ids", []):
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
            post_text = "\n\n".join(parts).strip()
            # Telegram admite 4096 chars; recortar solo si excede (margen para el encabezado)
            if len(post_text) > 3900:
                post_text = post_text[:3900].rsplit("\n", 1)[0] + "\n\n[…texto recortado]"
            new_pubs.append({"pub": pub_param, "text": post_text})

    log.info(f"Muro: {len(all_pub_ids)} publicaciones, {len(new_pubs)} nuevas")

    if first_run:
        state["pub_ids"] = list(all_pub_ids)
        log.info("Muro baseline saved")
    else:
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

        for pub in new_pubs:
            pub_id = pub["pub"]
            zip_url = f"{MURO_ORIGIN}/descargar_publicacion.php?pub={pub_id}"
            try:
                zip_resp = session.get(zip_url, timeout=120)
                zip_resp.raise_for_status()

                if "zip" not in zip_resp.headers.get("Content-Type", ""):
                    log.warning(f"pub={pub_id}: not a ZIP response, skipping")
                    state.setdefault("pub_ids", []).append(pub_id)
                    continue

                with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
                    files = zf.namelist()
                    log.info(f"pub={pub_id}: ZIP with {len(files)} files")

                    # Primero enviar el texto de la publicacion
                    if pub["text"]:
                        notify_ha("muro_text",
                                  message=f"📋 <b>Nueva publicación</b> ({now_str})\n\n{html.escape(pub['text'])}")
                        time.sleep(1)

                    # Luego las fotos/videos
                    for fname in files:
                        data = zf.read(fname)
                        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                        safe_name = f"muro_{pub_id[:8]}_{fname}"
                        (MEDIA_DIR / safe_name).write_bytes(data)

                        if ext in ("jpg", "jpeg", "png", "webp", "avif"):
                            notify_ha("muro_photo", file=safe_name, caption="")
                        elif ext in ("mp4", "mov", "avi", "webm"):
                            notify_ha("muro_video", file=safe_name, caption="")
                        else:
                            log.info(f"Skipping unknown file type: {fname}")

                        time.sleep(1)

            except Exception as e:
                log.error(f"Error downloading pub={pub_id}: {e}")

            state.setdefault("pub_ids", []).append(pub_id)

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


def parse_agenda(html):
    soup = BeautifulSoup(html, "html.parser")
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


def check_agenda(state, first_run=False):
    agenda_url = state.get("agenda_url")
    if not agenda_url:
        log.warning("No agenda URL available — skipping agenda check")
        return

    log.info(f"Checking agenda: {agenda_url[:80]}...")

    try:
        resp = requests.get(agenda_url, timeout=30)
        resp.raise_for_status()
        html = resp.content.decode("iso-8859-1")
    except Exception as e:
        log.error(f"Agenda fetch error: {e}")
        return

    current = parse_agenda(html)
    previous = state.get("agenda_snapshot", {})
    log.info(f"Agenda fields: {list(current.keys())}")

    if first_run:
        state["agenda_snapshot"] = current
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

        if has_changes:
            msg = build_agenda_message(current)
            if msg is None:
                log.info("Agenda: changes detected but all fields still empty, skipping")
            else:
                # Borrar mensajes anteriores (en cada destino) y enviar nuevo a todos
                old_msg_ids = get_agenda_message_ids(state)
                tg_delete_agenda_in_all(old_msg_ids)

                new_ids = tg_send_agenda_to_all(msg)
                state["agenda_message_ids"] = new_ids
                state.pop("agenda_message_id", None)

                log.info(f"Agenda message sent/updated to {len(AGENDA_TARGETS)} target(s)")

        state["agenda_snapshot"] = current

    state["last_agenda_check"] = datetime.now().isoformat()
    save_state(state)


# --- Self-test (SELF_TEST=1): prueba la cadena completa sin entrar en el bucle ---
def run_self_test():
    log.info("=== SELF-TEST ===")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    tg_send_message("🧪 <b>[TEST]</b> Monitor guardería standalone — probando envío directo a Telegram…", TG_THREAD_SISTEMA)
    session = get_session()
    if not session:
        tg_send_message("❌ <b>[TEST]</b> Login en Workandlife FALLÓ. Revisa WL_USER/WL_PASS.", TG_THREAD_SISTEMA)
        return
    tg_send_message("✅ <b>[TEST]</b> Login OK. Buscando la última publicación del muro…", TG_THREAD_SISTEMA)
    resp = session.get(MURO_URL, timeout=30)
    soup = BeautifulSoup(resp.content, "html.parser")
    posts = soup.find_all("div", class_="user-post")
    log.info(f"self-test: {len(posts)} publicaciones")
    target = None
    for post in posts:
        dl = post.find("a", href=lambda h: h and "descargar_publicacion" in h)
        if dl:
            target = (post, dl["href"].split("pub=")[-1])
            break
    if not target:
        tg_send_message("⚠️ <b>[TEST]</b> Texto OK, pero no hay publicaciones con descarga (¿muro vacío?).", TG_THREAD_SISTEMA)
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
        tg_send_message(f"📋 <b>[TEST] Última publicación</b>\n\n{html.escape(txt)}", TG_THREAD_SISTEMA)
    zip_url = f"{MURO_ORIGIN}/descargar_publicacion.php?pub={pub_id}"
    zr = session.get(zip_url, timeout=120)
    n_photo = n_video = 0
    try:
        with zipfile.ZipFile(io.BytesIO(zr.content)) as zf:
            for fname in zf.namelist():
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                p = MEDIA_DIR / f"selftest_{fname}"
                p.write_bytes(zf.read(fname))
                if ext in ("jpg", "jpeg", "png", "webp", "avif"):
                    if tg_send_file("sendPhoto", "photo", p, f"🧪 [TEST] foto {n_photo + 1}", TG_THREAD_SISTEMA):
                        n_photo += 1
                elif ext in ("mp4", "mov", "avi", "webm"):
                    if tg_send_file("sendVideo", "video", p, f"🧪 [TEST] vídeo {n_video + 1}", TG_THREAD_SISTEMA):
                        n_video += 1
                time.sleep(1)  # 1s entre envíos (anti-flood), como el flujo real
    except Exception as e:
        log.error(f"self-test ZIP error: {e}")
    tg_send_message(
        f"🧪 <b>[TEST] Resultado:</b> texto={'✅' if txt else '—'} "
        f"· fotos={n_photo} · vídeos={n_video}\n\n"
        f"<i>Envío self-contained de TODOS los medios de la última publicación, SIN Home Assistant.</i>",
        TG_THREAD_SISTEMA)
    log.info("=== SELF-TEST done ===")


# --- Main loop ---
def main():
    log.info("=== Guarderia Monitor starting ===")
    if os.getenv("SELF_TEST") == "1":
        run_self_test()
        return
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    state = load_state()
    first_run = not state.get("pub_ids") and not state.get("agenda_snapshot")

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

    log.info(
        f"Scheduler: muro ~{MURO_INTERVAL[0]}-{MURO_INTERVAL[1]}min, "
        f"agenda ~{AGENDA_INTERVAL[0]}-{AGENDA_INTERVAL[1]}min, 07:00-17:00"
    )

    while True:
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
            if now.hour >= 17 and next_muro < now:
                tomorrow_7 = (now + timedelta(days=1)).replace(hour=7, minute=0, second=0)
                next_muro = tomorrow_7 + random_wait((1, 10))
                next_agenda = tomorrow_7 + random_wait((1, 5))
                log.info("Outside hours. Next checks at ~07:0x tomorrow")

        # Pasada nocturna del muro (cualquier día) para tardes/fines de semana
        if next_evening and now >= next_evening:
            log.info("Pasada nocturna del muro")
            state = load_state()
            check_muro(state)
            next_evening = next_evening_sweep()
            log.info(f"Próxima pasada nocturna: {next_evening:%Y-%m-%d %H:%M}")

        time.sleep(30)


if __name__ == "__main__":
    main()
