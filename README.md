# 🍼 Guardería Monitor

Vigila el **muro** y la **agenda** del portal de familias **Workandlife** y te lo
reenvía a **Telegram**: texto, fotos y vídeos de cada publicación nueva (las fotos
llegan agrupadas en álbumes) y la agenda diaria del peque (comidas, siestas,
deposiciones, observaciones…). **Autocontenido: no necesita Home Assistant ni nada más.**

> Pensado para que cualquier madre/padre lo ponga en marcha **sin saber programar**,
> siguiendo esta guía paso a paso. Cada familia corre su propia copia con sus
> credenciales: **tus datos no salen de tu máquina**.

**Solo necesita tu usuario y contraseña.** No hay que copiar URLs ni ids de aula:
al entrar descubre solo el centro, **todas** las aulas que te muestra el portal y
el enlace de la agenda. Si tu peque cambia de aula o empieza curso nuevo, se
entera él solo y te avisa del cambio.

## ¿Qué recibirás en Telegram?

- 📋 **Muro**: cada publicación nueva → el texto + todas sus fotos/vídeos (en álbumes de hasta 10),
  con el nombre del aula de la que viene.
- 🗓️ **Agenda diaria**: un único mensaje al día que se va actualizando solo (borra el anterior y manda el nuevo).
- ⚠️ **Avisos**, sin spamear:
  - cambian las aulas del portal (alta, baja o renombrado),
  - un aula deja de existir y el portal empieza a devolver otra cosa,
  - la web añade o renombra campos de la agenda que el monitor todavía no sabe mostrar,
  - la agenda del día sigue vacía a media tarde en día lectivo,
  - el login falla o algo se rompe.

Comprueba el muro cada ~1h y la agenda cada ~30min, solo en horario lectivo
(L-V 07:00–17:00, ignora festivos nacionales), con intervalos aleatorios para no
martillear el portal. Además hace **una pasada extra cada noche (~22:00)** para pillar
publicaciones de tardes y fines de semana.

---

# 🚀 Puesta en marcha desde cero

Necesitas 3 cosas: **Docker** instalado, tu **cuenta de Workandlife** y un
**bot de Telegram** (gratis, 2 minutos). Vamos paso a paso.

## Paso 0 — Instalar Docker

Docker es el programa que ejecuta el monitor. Debe correr en un equipo que esté
**encendido durante el día** (un mini-PC, un NAS, un portátil viejo, una Raspberry…).

**Windows 10/11:**
1. Descarga **Docker Desktop**: https://www.docker.com/products/docker-desktop/
2. Instálalo (siguiente → siguiente; si te pregunta por **WSL 2**, di que sí).
3. Reinicia si te lo pide y abre Docker Desktop. Cuando el icono de la ballena esté quieto, listo.

**Linux (Ubuntu/Debian/Raspberry Pi OS):**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # para no tener que escribir sudo cada vez
```
Cierra sesión y vuelve a entrar (o reinicia) para que aplique el grupo.

✅ **Comprobación** — abre una terminal (en Windows: PowerShell) y escribe:
```
docker --version
```
Si responde con una versión, Docker funciona.

## Paso 1 — Crear tu bot de Telegram

1. En Telegram, abre **[@BotFather](https://t.me/BotFather)** (el bot oficial de Telegram).
2. Escríbele `/newbot`.
3. Te pide un **nombre** (el que quieras, ej. `Guardería de Manuel`).
4. Te pide un **usuario** que debe acabar en `bot` (ej. `guarde_manuel_bot`).
5. BotFather te responde con el **token**: una cadena tipo
   `123456789:AAExxxxxxxxxxxxxxxxxxxxxx`. **Cópiala y guárdala** — es la llave de tu bot,
   no la compartas.

## Paso 2 — ¿Dónde quieres recibirlo? (chat id)

Puedes recibirlo en un **chat privado** con el bot o en un **grupo familiar**
(recomendado si sois varios).

**Opción A — Chat privado:**
1. Busca tu bot en Telegram (el usuario que creaste) y dale a **Iniciar** (o mándale un "hola").
2. Abre en el navegador (cambiando `<TOKEN>` por tu token):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Busca `"chat":{"id":123456789...` → ese número es tu **TG_CHAT_ID**.

**Opción B — Grupo familiar (recomendado):**
1. Crea un grupo en Telegram (ej. "Guardería 👶") y **añade a tu bot** como miembro.
2. Escribe en el grupo un mensaje **mencionando al bot**: `hola @guarde_manuel_bot`
3. Abre `https://api.telegram.org/bot<TOKEN>/getUpdates` en el navegador.
4. Busca `"chat":{"id":-100...` → los grupos tienen id **negativo**
   (ej. `-1001234567890`). Ese es tu **TG_CHAT_ID**.

> 💡 Si `getUpdates` sale vacío (`"result":[]`), manda otro mensaje y recarga la página.

## Paso 3 — Descargar este proyecto

**Sin git (más fácil):** en la página de GitHub del proyecto pulsa
**Code → Download ZIP**, descomprímelo donde quieras (ej. `Documentos\guarderia-monitor`).

**Con git:**
```bash
git clone https://github.com/kikorr/guarderia-monitor.git
cd guarderia-monitor
```

## Paso 4 — Configurar tus datos (.env)

En la carpeta del proyecto hay un fichero `.env.example`. Hay que copiarlo como `.env`
y rellenarlo.

**Windows (PowerShell, dentro de la carpeta del proyecto):**
```powershell
copy .env.example .env
notepad .env
```
> 💡 Para abrir PowerShell en la carpeta: entra en la carpeta con el Explorador,
> escribe `powershell` en la barra de direcciones y pulsa Enter.

**Linux:**
```bash
cp .env.example .env
nano .env
```

Rellena estas **4 líneas** con lo que has ido recopilando:
```ini
WL_USER=tu_usuario_de_workandlife
WL_PASS=tu_contraseña_de_workandlife
TG_BOT_TOKEN=123456789:AAExxxxxxxxxxxxxxxxxxxxxx
TG_CHAT_ID=-1001234567890
```
Y ya está: **el aula no se configura**, la encuentra él. El resto de opciones son
opcionales (explicadas más abajo). Guarda y cierra.

## Paso 5 — Probar que todo funciona (self-test)

Antes de dejarlo en marcha, prueba la cadena completa (login + descubrimiento de
aulas + lectura del muro + envío a Telegram). En la carpeta del proyecto
(mismo comando en Windows y Linux):

```bash
docker compose run --rm -e SELF_TEST=1 guarderia-monitor
```

La primera vez tardará unos minutos (descarga y construye la imagen). Después
deberías recibir en Telegram varios mensajes `🧪 [TEST]`, incluyendo **la lista de
aulas que ha encontrado** y **la última publicación real del muro con sus
fotos/vídeos en álbumes**. Si llega → ¡funciona! 🎉

> 👀 Mira la lista de aulas del mensaje de test: ahí debería salir la de tu peque.
> Si sale alguna de más que no te interesa, puedes filtrarlas con `AULAS_INCLUDE`
> (ver *Opciones avanzadas*).

Si algo falla, mira la sección **Solución de problemas** más abajo.

## Paso 6 — Arrancarlo definitivamente

```bash
docker compose up -d --build
```

Ya está. El monitor queda corriendo en segundo plano y **arranca solo** aunque
reinicies el equipo (mientras Docker esté activo).

> ℹ️ **Primer arranque**: el monitor hace una "foto inicial" del muro y **NO reenvía
> las publicaciones antiguas** (para no inundarte). Solo te llegará lo nuevo a partir
> de ese momento. Recibirás un "✅ Monitor guardería iniciado" como confirmación.

---

# 📖 Día a día

| Quiero… | Comando (en la carpeta del proyecto) |
|---|---|
| Ver qué está haciendo | `docker compose logs -f` (Ctrl+C para salir) |
| Pararlo | `docker compose down` |
| Arrancarlo de nuevo | `docker compose up -d` |
| Actualizar a la última versión | `git pull` (o re-descargar el ZIP) y `docker compose up -d --build` |
| Resetearlo de cero | `docker compose down`, borrar la carpeta `data/`, `docker compose up -d` |

Los datos (estado y caché de fotos ya enviadas) viven en la subcarpeta `data/` del
proyecto. La caché se limpia sola (se conservan 30 días).

---

# 🔎 Qué hace solo (y por qué)

Cada vez que entra, el monitor:

1. **Averigua tu centro** a partir de la redirección del login, en vez de tenerlo escrito.
2. **Lee la lista de aulas** de `aulas.php` y las recorre todas. Una misma publicación
   que aparezca en dos aulas se envía una sola vez.
3. **Saca el enlace de la agenda** del pie del portal. Ese enlace es **por familia**,
   no por aula, así que no depende de acertar con el aula.
4. **Compara la lista de aulas con la de la última vez** y te avisa si algo cambió.

Esto no es un capricho: el portal cambia el identificador del aula cada curso, y una
URL de aula caducada **no da error** — el portal te devuelve la portada como si tal
cosa. Con el aula escrita a mano en la configuración, el monitor se pasaba días
leyendo la portada creyendo que era el muro, sin que nadie se enterara. Ahora esa
situación se detecta y se avisa.

> ⬆️ **¿Vienes de una versión anterior?** Ya no hace falta `MURO_URL` en tu `.env`;
> si sigue ahí, se ignora. Puedes borrar esa línea.

---

# ⚙️ Opciones avanzadas (todas opcionales, en el .env)

### Grupo con "Temas" (Topics)
Si tu grupo tiene **Temas activados** y quieres separar muro / agenda / avisos en
temas distintos:
1. Abre el tema en Telegram, mantén pulsado un mensaje cualquiera → **Copiar enlace**.
2. El enlace es tipo `https://t.me/c/1234567890/452/99` → el número **del medio** (`452`)
   es el id del tema.
3. Rellena `TG_THREAD_MURO`, `TG_THREAD_AGENDA` y `TG_THREAD_SISTEMA` con los ids.
   Para un chat/grupo normal **déjalos vacíos**.

### Seguir solo algunas aulas
`AULAS_INCLUDE`: por defecto sigue **todas** las aulas que te muestra el portal. Si
solo quieres algunas, pon una expresión regular que case con su nombre, por ejemplo
`Cervatillo|Comunicados`. Vacío = todas (recomendado).

### Aviso de agenda vacía
`AGENDA_EMPTY_ALERT_HOUR=15`: hora a partir de la cual, en día lectivo, te avisa una
vez si la agenda del día sigue completamente vacía. Como el mensaje de agenda no se
envía cuando no hay ningún dato, sin este aviso un fallo se confunde con "hoy no han
escrito nada". `0` lo desactiva.

### Avisos del sistema a otro chat
`SISTEMA_CHAT_ID`: si quieres que los avisos técnicos (login caído, etc.) vayan a un
chat distinto del familiar (p.ej. solo a ti), pon aquí su chat id.

### Contraseñas en ficheros (Docker secrets)
Cualquier variable sensible admite el sufijo `_FILE` apuntando a un fichero, en vez de
ir en el `.env`: `WL_USER_FILE`, `WL_PASS_FILE`, `TG_BOT_TOKEN_FILE`. Útil si usas
Docker secrets y no quieres que las credenciales aparezcan en `docker inspect`.

### Otras
- `EVENING_MURO_HOUR=22` → hora de la pasada nocturna del muro (vacío = desactivarla).
- `MEDIA_RETENTION_DAYS=30` → días que se conserva la caché local de fotos/vídeos.
- `TG_CHAT_ID_2` + `TG_THREAD_AGENDA_2` → enviar la agenda además a un segundo grupo.
- `WL_LOGIN_URL` → punto de entrada del portal (por defecto `https://comunidaddefamilias.com`).
- `TZ=Europe/Madrid` → zona horaria.

---

# 🔧 Solución de problemas

| Síntoma | Causa probable y arreglo |
|---|---|
| `[TEST] Login en Workandlife FALLÓ` | Usuario/contraseña mal en el `.env`. Prueba a entrar en la web a mano con esos mismos datos. |
| `[TEST] Login OK pero no pude listar las aulas` | El portal respondió raro o cambió. Reintenta; si persiste, abre un issue. |
| El test dice `Aulas descubiertas: (ninguna)` | Tu cuenta no tiene aulas asignadas en el portal. Compruébalo entrando a la web a mano. |
| No sale el aula de mi peque en la lista | ¿Tienes `AULAS_INCLUDE` puesto? Déjalo vacío para seguirlas todas. |
| Aviso `El aula X ya no existe en el portal` | Normal en cambio de curso: el monitor la salta y sigue con las nuevas. No hay que tocar nada. |
| Aviso `Campos nuevos en la agenda` | La web renombró o añadió un campo. El monitor sigue funcionando pero no muestra ese campo; abre un issue con el nombre que te ha dicho. |
| Aviso `Agenda vacía` todos los días | Si en la web sí ves datos, la página ha cambiado: abre un issue. Si tampoco los ves ahí, es que la guardería no la rellena. |
| No llega nada a Telegram y en el log sale `400 Bad Request` | `TG_CHAT_ID` mal (¿olvidaste el `-100` de los grupos?), el bot **no está dentro del grupo**, o pusiste `TG_THREAD_*` de un tema que no existe en ese chat. |
| `getUpdates` sale vacío | Mándale un mensaje al bot (o menciónalo en el grupo) y recarga. |
| `chat not found` | El bot no ha sido iniciado (chat privado: dale a "Iniciar") o no está en el grupo. |
| Un vídeo no llega | Telegram limita a los bots a **50 MB por fichero**; los que pasan de ahí se omiten (te avisa). |
| `docker: command not found` | Docker no está instalado o (Windows) Docker Desktop no está abierto. |
| Cambia la web de Workandlife y deja de funcionar | El scraping depende de su web; abre un issue en GitHub o espera actualización. |
| Quiero verlo todo | `docker compose logs -f` — el log también queda en `data/monitor.log`. |

# ❓ FAQ

- **¿Es seguro?** Tus credenciales solo están en TU `.env`, en TU máquina, y solo se
  usan contra la web de Workandlife. Nada se sube a ningún sitio (salvo los envíos a
  tu propio Telegram).
- **¿Molesta al portal de la guardería?** No: consulta con la misma frecuencia que un
  padre mirando la web (cada ~1h, con horarios aleatorios y solo en horario lectivo).
- **¿Y si el bot se cae o se reinicia el equipo?** Se levanta solo (`restart: unless-stopped`)
  y retoma donde iba: no repite publicaciones ya enviadas, y las que no pudo descargar
  las reintenta hasta 3 veces.
- **¿Y cuando mi peque cambie de aula o de curso?** No tienes que hacer nada: lo detecta
  al siguiente ciclo y te manda un aviso contándote qué ha cambiado.
- **¿Sigue las aulas de mis dos hijos?** Sigue todas las aulas que tu cuenta ve en el
  portal, así que sí, siempre que ambos cuelguen de la misma cuenta de familia.
- **¿Funciona con cualquier guardería?** Solo con las que usan la plataforma
  **Workandlife** (portal `comunidaddefamilias.com` / `*.workandlife.com`).

---

*Proyecto casero, sin afiliación con Workandlife. Úsalo bajo tu responsabilidad.*
