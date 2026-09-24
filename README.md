# 🍼 Guardería Monitor

Un programa que vigila la web de la guardería (portal de familias **Work and Life**) y te
lo cuenta por **Telegram**:

- 📋 **Muro**: cada publicación nueva, con su texto y todas sus fotos y vídeos.
- 🗓️ **Agenda del día**: comidas, siestas, pañales y observaciones, en un solo mensaje que se va actualizando.
- 🚪 **Fichaje de entrada** (opcional): si a las 9:00 nadie ha fichado la entrada, te pregunta
  «¿Ficho yo la entrada de hoy?» con dos botones. Solo ficha si pulsas **Sí**.
- ⚠️ **Avisos** si algo falla (contraseña cambiada, la web cambia…), sin repetirse.

Lo que verás en Telegram, por ejemplo:

```
📋 Aula de Bebés — «Hoy hemos pintado con las manos» + 8 fotos
🗓️ Agenda de hoy — Comida: todo · Siesta: 12:30–14:10 · Pañales: 3
🚪 Guardería: hoy no hay entrada fichada
   1 niño sin entrada.
   ¿Ficho yo la entrada de hoy? Si no han ido, pulsa No.
   [ ✅ Sí, ficha ]  [ ❌ No, hoy no ]
```

Cada familia pone en marcha **su propia copia**, en su casa: tus datos no salen de tu equipo.

---

# 🧰 Qué necesitas

1. **Un ordenador o miniservidor encendido durante el día** con **Docker** (el programa que
   ejecuta el monitor). Vale un mini-PC, un NAS, un portátil viejo o una Raspberry Pi.
   - Windows o Mac: [Docker Desktop](https://www.docker.com/products/docker-desktop/).
   - Linux: [Docker Engine](https://docs.docker.com/engine/install/) (o `curl -fsSL https://get.docker.com | sh`).
2. **Una cuenta de Telegram** (la del móvil sirve).
3. **Tu usuario y contraseña de Work and Life** (los de la web o app de la guardería).
4. **Solo si quieres el fichaje de entrada:**
   - **El enlace del QR de fichajes** del centro. El QR de la puerta es un enlace que ya lleva
     dentro la sesión del padre o la madre. Escanéalo con el móvil, **copia el enlace tal cual**
     (tiene esta forma: `https://agenda2.workandlife.com/fichajes_padres/?p=XXXX`) y guárdalo.
     Trátalo como una contraseña: quien lo tenga puede fichar por ti.
   - **El DNI** del padre o madre con el que se ficha (el mismo que pones en la web al fichar).

---

# 🚀 Puesta en marcha, paso a paso

Todos los comandos se escriben en una **terminal**: en Windows, *PowerShell*; en Mac y Linux,
*Terminal*. Copia cada comando tal cual.

## Paso 0 — Comprobar que Docker funciona

```bash
docker --version
docker compose version
```
✅ Deben responder con un número de versión. En Windows y Mac, Docker Desktop tiene que estar abierto.

## Paso 1 — Crear el bot de Telegram

1. En Telegram, abre **[@BotFather](https://t.me/BotFather)** y escríbele `/newbot`.
2. Te pide un **nombre** (el que quieras, p. ej. `Guardería de casa`) y un **usuario** que
   acabe en `bot` (p. ej. `guarde_de_casa_bot`).
3. Te responde con el **token**, algo así: `123456789:AAExxxxxxxxxxxxxxxxxxxxxxx`.
   Cópialo: lo usarás en el paso 5. **No lo compartas.**

> ⚠️ Usa un bot **nuevo, solo para esto**. No puede ser un bot que ya use otro programa
> (por ejemplo, el de Home Assistant): Telegram solo deja que **un programa** escuche los
> botones de un bot, y si hay dos se pisan (verás el error `409 Conflict`).

## Paso 2 — Preparar el grupo de Telegram

1. Crea un grupo (p. ej. «Guardería 👶») o usa uno que ya tengáis.
2. **Añade tu bot** al grupo como miembro (Añadir miembros → busca el usuario del bot).
3. ¿Quieres separar muro, agenda y avisos? Activa **Temas** en el grupo
   (Editar grupo → Temas) y crea, por ejemplo, «Muro», «Agenda» y «Sistema».
   Si no, no hace falta: todo llegará al grupo.
4. Si quieres los avisos técnicos en **otro grupo** (p. ej. uno solo tuyo), añade el bot
   también a ese grupo.

## Paso 3 — Averiguar el id del grupo y de los temas

No hace falta programar:

1. Abre **[Telegram Web](https://web.telegram.org/a/)** en el navegador del ordenador y entra en el grupo.
2. Mira la barra de direcciones: termina en algo como `#-1001234567890`.
   Ese número, **con el signo menos**, es el **id del grupo**.
3. Para cada **tema**: haz clic derecho en un mensaje de ese tema → **Copiar enlace**.
   El enlace es del tipo `https://t.me/c/1234567890/452/99`: el número **del medio** (`452`)
   es el **id del tema**. (El primer número, con `-100` delante, vuelve a ser el id del grupo:
   `-1001234567890`.)

Apunta los números. Otra forma: añade al grupo un momento un bot de ids como
[@getidsbot](https://t.me/getidsbot); te dice el id del grupo. Después sácalo del grupo.

## Paso 4 — Descargar el proyecto

**Sin git:** en la página del proyecto en GitHub pulsa **Code → Download ZIP** y
descomprímelo (p. ej. en `Documentos/guarderia-monitor`). Abre la terminal **dentro** de esa carpeta.

**Con git:**
```bash
git clone https://github.com/kikorr/guarderia-monitor.git
cd guarderia-monitor
```

> 💡 Windows: para abrir PowerShell en la carpeta, entra en ella con el Explorador, escribe
> `powershell` en la barra de direcciones y pulsa Enter.

## Paso 5 — Guardar tus datos privados (los «secretos»)

Un **secreto** es un fichero de texto dentro de la carpeta `secrets/` que contiene **solo el
valor**: sin comillas, sin espacios y sin salto de línea al final. Así tus contraseñas no
quedan escritas en ningún otro sitio.

**Mac / Linux** (cambia lo que va entre comillas simples por tu dato):
```bash
printf '%s' 'tu_usuario'        > secrets/wl_user
printf '%s' 'tu_contraseña'     > secrets/wl_pass
printf '%s' '123456789:AAExxxx' > secrets/tg_bot_token
# Solo si quieres el fichaje:
printf '%s' 'https://agenda2.workandlife.com/fichajes_padres/?p=XXXX' > secrets/fichaje_url
printf '%s' '12345678Z'         > secrets/fichaje_dni
chmod 600 secrets/*
```

**Windows (PowerShell):**
```powershell
Set-Content -NoNewline -Encoding utf8 -Path secrets\wl_user      -Value 'tu_usuario'
Set-Content -NoNewline -Encoding utf8 -Path secrets\wl_pass      -Value 'tu_contraseña'
Set-Content -NoNewline -Encoding utf8 -Path secrets\tg_bot_token -Value '123456789:AAExxxx'
# Solo si quieres el fichaje:
Set-Content -NoNewline -Encoding utf8 -Path secrets\fichaje_url  -Value 'https://agenda2.workandlife.com/fichajes_padres/?p=XXXX'
Set-Content -NoNewline -Encoding utf8 -Path secrets\fichaje_dni  -Value '12345678Z'
```

| Fichero | Qué es | ¿Obligatorio? |
|---|---|---|
| `secrets/wl_user` | Usuario de Work and Life | Sí |
| `secrets/wl_pass` | Contraseña de Work and Life | Sí |
| `secrets/tg_bot_token` | Token del bot (paso 1) | Sí |
| `secrets/fichaje_url` | Enlace del QR de fichajes | Solo para el fichaje |
| `secrets/fichaje_dni` | DNI con el que se ficha | Solo para el fichaje |

> 💡 Si tu contraseña lleva una comilla simple (`'`), crea el fichero con el Bloc de notas
> y guárdalo con ese nombre exacto, sin extensión `.txt`.

## Paso 6 — Configurar el grupo y la hora (`.env`)

Copia el fichero de ejemplo y ábrelo:

```bash
cp .env.example .env        # Windows: copy .env.example .env
nano .env                   # Windows: notepad .env
```

Rellena **solo** estas líneas (el resto déjalo como está):

| Variable | Qué es | Ejemplo |
|---|---|---|
| `TG_CHAT_ID` | Id del grupo (paso 3) | `-1001234567890` |
| `TG_THREAD_MURO` | Id del tema del muro (vacío si no usas temas) | `452` |
| `TG_THREAD_AGENDA` | Id del tema de la agenda; ahí llega también la pregunta del fichaje | `453` |
| `TG_THREAD_SISTEMA` | Id del tema de avisos técnicos | `454` |
| `FICHAJE_HORA` | Hora a la que pregunta si hay que fichar | `09:00` |

Guarda y cierra.

## Paso 7 — Arrancarlo

```bash
docker compose up -d --build
```

La primera vez tarda unos minutos (prepara la imagen). Después, mira el registro (log):

```bash
docker compose logs -f
```

✅ Va bien si ves estas líneas (sale del log con Ctrl+C; el monitor sigue funcionando):

```
[INFO] Login OK (centro: https://...)
[INFO] Fichaje guarderia: ACTIVO a las 09:00
[INFO] fichaje: escucha de botones en marcha
```

- Si no quieres el fichaje, en vez de la 2.ª línea verás
  `Fichaje guarderia: desactivado (faltan secretos)` y no saldrá la 3.ª. Es normal.
- La **primera vez** hace una «foto» del muro y **no reenvía lo antiguo**; solo lo nuevo a
  partir de ahora. Recibirás «✅ Monitor guardería iniciado».
- Arranca solo cada vez que se enciende el equipo (mientras Docker esté activo).

## Paso 8 — Probar

**Prueba de los botones** (no ficha nada):
```bash
docker compose exec guarderia-monitor python fichaje.py test-bot
```
✅ En el grupo llega «🧪 Prueba del bot de fichaje» con dos botones. Al pulsar uno, el mensaje
se edita: desaparecen los botones y aparece «→ prueba recibida: Sí (Tu nombre) · 10:15».

**Qué ve el monitor en la web de fichajes** (no ficha nada):
```bash
docker compose exec guarderia-monitor python fichaje.py estado
```
Responde algo así:

| Campo | Qué significa |
|---|---|
| `hecho` | `true` si todos los niños (no ausentes) ya tienen la entrada de hoy |
| `tipo_web` | Qué registro propone la web: `1` = entrada |
| `padre` | `true` si ha encontrado tu ficha de padre/madre |
| `alumnos` | Cada niño: su id, si está ausente, si su casilla está desactivada y las horas de entrada y salida de hoy |
| `pendientes` | Ids de los niños a los que falta fichar la entrada |
| `error` | Vacío si todo va bien; si no, qué pasa (ver «Problemas frecuentes») |

**Prueba completa del muro** (opcional; manda mensajes `🧪 [TEST]` con la última publicación):
```bash
docker compose run --rm -e SELF_TEST=1 guarderia-monitor
```

## Paso 9 — Día a día

- **Muro y agenda** llegan solos, de lunes a viernes entre las 7:00 y las 17:00 (y una pasada
  cada noche a las ~22:00 para lo publicado por la tarde).
- **Fichaje**: a `FICHAJE_HORA`, en días de cole, si nadie ha fichado la entrada llega la
  pregunta con los botones.
  - **Sí** → el mensaje pone «→ Sí (nombre) · hora», luego «⏳ fichando…» y al final
    «✅ Entrada fichada». Si algo falla, lo dice y lo reintenta; si no lo consigue, te pide
    que lo hagas en la puerta.
  - **No** (el niño no va, está malito, vacaciones…) → «→ No, hoy no». No se ficha nada.
  - **Sin respuesta** → te lo recuerda una vez a los 30 minutos. A las 3 horas la pregunta
    caduca y ya no ficha.
  - Si alguien ya fichó en la puerta, no pregunta.
- **Cambiar la hora del fichaje u otro ajuste**: edita `.env` y ejecuta
  `docker compose up -d` (no hace falta `--build`).

| Quiero… | Comando (en la carpeta del proyecto) |
|---|---|
| Ver qué está haciendo | `docker compose logs -f` |
| Pararlo | `docker compose down` |
| Arrancarlo de nuevo | `docker compose up -d` |
| Actualizar a la última versión | `git pull` (o bajar el ZIP otra vez) y `docker compose up -d --build` |
| Empezar de cero | `docker compose down`, borrar la carpeta `data/` y `docker compose up -d` |

---

# 🔧 Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| En el log: `chat not found` o `400 Bad Request` al enviar | El bot no está en el grupo, o el id está mal (¿falta el `-100`?), o el id de tema no existe | Añade el bot al grupo (paso 2) y revisa los ids en `.env` (paso 3). Luego `docker compose up -d`. |
| En el log: `409 Conflict` | Otro programa escucha el mismo bot (Home Assistant, otra copia del monitor, o el comando `fichaje.py poll`) | Usa un bot solo para el monitor (paso 1). Si era `poll`, es inofensivo. |
| `Fichaje guarderia: desactivado (faltan secretos)` | Falta `secrets/fichaje_url` o `secrets/fichaje_dni`, o están vacíos | Créalos (paso 5) y `docker compose up -d`. Compruébalo con `ls -l secrets`. |
| Aviso «la web sigue pidiendo el DNI» | DNI mal escrito, enlace del QR caducado, o falta aceptar las cookies de la web | Revisa el DNI y vuelve a copiar el enlace del QR. Si sigue, mira el recuadro de abajo. |
| Aviso «la web propone un registro de tipo X, no una entrada» | La web espera otra cosa: normalmente ya hay entrada y toca la salida | No ficha nada. Mira la web de fichajes; si falta la entrada, hazla en la puerta. |
| Botón contesta «No puedo guardar el estado» | El disco está lleno o la carpeta `data/` no se puede escribir | Libera espacio (`df -h`) y comprueba que existe la carpeta `data/` junto a `docker-compose.yml`. Mientras tanto no ficha (a propósito). |
| `[TEST] Login en Workandlife FALLÓ` | Usuario o contraseña mal | Entra en la web a mano con esos datos; corrige `secrets/wl_user` o `secrets/wl_pass`. |
| El test dice `Aulas descubiertas: (ninguna)` | Tu cuenta no tiene aulas en el portal | Compruébalo entrando en la web a mano. |
| Aviso `El aula X ya no existe en el portal` | Cambio de curso | Nada: el monitor sigue con las aulas nuevas. |
| Un vídeo no llega | Telegram no deja a los bots enviar más de 50 MB por fichero | Nada: te avisa y sigue. |
| `docker: command not found` | Docker no está instalado o no está abierto | Paso 0. |

**Cómo sacar la cookie de consentimiento** (si la web sigue pidiendo el DNI):
1. En el ordenador, abre el enlace del QR en Chrome o Edge y pulsa **Aceptar todas** en el aviso de cookies.
2. Pulsa **F12** → pestaña **Aplicación** (Application) → **Cookies** → la dirección de la web de
   fichajes. Busca la cookie que acaba de aparecer al aceptar y apunta su **nombre** y su **valor**.
3. En `.env`, quita la `#` de `FICHAJE_COOKIES_EXTRA` y pon `FICHAJE_COOKIES_EXTRA=nombre=valor`.
   Luego `docker compose up -d`.

---

# 📚 Referencia técnica

## Todas las variables

Van en `.env`, salvo los secretos, que van en `secrets/` (el `docker-compose.yml` ya los enlaza
con variables `*_FILE`). Si existe el fichero `*_FILE`, manda sobre la variable normal; si el
fichero no existe, se usa la variable (si la hay).

| Variable | Por defecto | Para qué |
|---|---|---|
| `WL_USER`, `WL_PASS` (`_FILE`) | — | Cuenta de Work and Life |
| `TG_BOT_TOKEN` (`_FILE`) | — | Token del bot (muro, agenda, avisos y fichaje) |
| `TG_CHAT_ID` | — | Grupo o chat de destino |
| `TG_THREAD_MURO` / `_AGENDA` / `_SISTEMA` | vacío | Temas del grupo |
| `SISTEMA_CHAT_ID` | `TG_CHAT_ID` | Otro chat para los avisos técnicos |
| `TG_CHAT_ID_2`, `TG_THREAD_AGENDA_2` | vacío | Enviar la agenda también a un segundo grupo |
| `TZ` | — | Zona horaria (`Europe/Madrid`) |
| `WORK_HOUR_START` / `WORK_HOUR_END` | `7` / `17` | Horario lectivo (horas enteras). Un valor raro o `START >= END` se ignora y se usa 7–17 |
| `EVENING_MURO_HOUR` | `22` | Pasada nocturna del muro (vacío = sin pasada) |
| `AGENDA_EMPTY_ALERT_HOUR` | `15` | Aviso si la agenda sigue vacía a esa hora (`0` = sin aviso). No se ajusta a `WORK_HOUR_END`: si END ≤ esa hora, el aviso no sale |
| `AULAS_INCLUDE` | vacío | Regex para seguir solo algunas aulas |
| `MEDIA_RETENTION_DAYS` | `30` | Días de caché de fotos y vídeos ya enviados |
| `WL_LOGIN_URL` | `https://comunidaddefamilias.com` | Entrada del portal |
| `FICHAJE_URL` (`_FILE`) | — | Enlace del QR de fichajes (lleva la sesión) |
| `FICHAJE_DNI` (`_FILE`) | — | DNI con el que se ficha |
| `FICHAJE_BOT_TOKEN` (`_FILE`) | `TG_BOT_TOKEN` | Bot aparte solo para el fichaje (opcional) |
| `FICHAJE_CHAT_ID` / `FICHAJE_THREAD` | `TG_CHAT_ID` / `TG_THREAD_AGENDA` | Dónde pregunta |
| `FICHAJE_HORA` | `09:00` | Hora de la pregunta (`HH:MM`; si está mal, 09:00) |
| `FICHAJE_RECORDATORIO_MIN` | `30` | Minutos hasta el recordatorio (`0` = sin recordatorio) |
| `FICHAJE_DIAS_CERRADO` | vacío | Días sin cole además de findes y festivos nacionales: `AAAA-MM-DD,AAAA-MM-DD` |
| `FICHAJE_COOKIES_EXTRA` | vacío | Cookies extra para la web: `nombre=valor;nombre2=valor2` |
| `FICHAJE_CENTRO` | se lee del QR | Id del centro en la web de fichajes (solo si la lectura falla) |
| `FICHAJE_STATE` | `/data/fichaje.json` | Fichero de estado del fichaje (una ruta relativa va dentro de `/data`) |
| `FICHAJE_HILO` | `1` | `0` = sin hilo de escucha; los botones se leen cada 30 s (modo de pruebas) |
| `FICHAJE_DEBUG` / `DEBUG` | vacío | `1` = guarda el último HTML de la ficha (`/data/fichaje_ultimo.html`, 0600, **contiene nombres**) y muestra trazas completas de errores en el log |

Si falta la URL, el DNI, el token o el chat, el fichaje queda desactivado y el resto del monitor
funciona igual. Un secreto ilegible no tumba el monitor: se registra el error y el fichaje se desactiva.

## Garantías del fichaje

- **Nunca ficha sin un «Sí» vigente**: el botón tiene que ser de la pregunta de hoy, sin respuesta
  previa y dentro de las 3 h siguientes a `FICHAJE_HORA`. Un botón viejo contesta «Pregunta caducada».
- **Cómo sabe si ya hay entrada**: tras el DNI, la web muestra un bloque por niño con
  `Entrada: HH:MM` y `Salida: HH:MM` cuando ya se han registrado. El día está **hecho** cuando todos
  los niños no ausentes tienen hora de entrada.
- **Qué ficha**: solo los niños pendientes (sin entrada, no ausentes, con la casilla activa). Envía lo
  mismo que el navegador: la casilla de cada niño (`chk_<id>`), el padre, el centro y `tipo=1`.
  La web decide el tipo de registro (`tipo_web`); si no es `1` (entrada), no ficha y avisa.
- **Segunda fuente, la agenda**: la agenda del día trae un apartado «Horario» («Entrada: No disponible»
  o la hora). No se envía a Telegram, pero el fichaje lo usa:
  - si la ficha de fichajes no se puede leer, la agenda decide: con hora de entrada, el día está hecho
    y no pregunta; sin hora, pregunta igual y avisa de que el «Sí» puede fallar;
  - si la ficha y la agenda no coinciden, manda la ficha y avisa una vez al día en Sistema;
  - la pregunta incluye la línea «Agenda: entrada …» y, tras fichar, el mensaje dice lo que marca la agenda.
  La agenda se lee como mucho una vez cada 35 minutos (reutiliza la comprobación periódica) y un fallo
  suyo nunca bloquea el fichaje.
- **Comprueba**: tras un «OK» de la web vuelve a leer la ficha. Si no sale la entrada, no repite el
  envío y avisa.
- **Reintentos con tope**: web caída o que sigue pidiendo el DNI → hasta 3 intentos con 10 min de
  pausa; solo al tercero avisa. Un «Sí» que no llega a fichar se reintenta con su propio tope de 3,
  y si cambia el día sin conseguirlo, lo dice.
- **Sin estado guardado no ficha**: si no puede escribir en `/data`, contesta al botón y espera.
- La pregunta sale como mucho 2 veces al día. Los avisos que no llegan se reintentan hasta 3 veces.
- **Privacidad**: la pregunta dice cuántos niños faltan, nunca nombres. Los errores se registran
  sin URLs ni tokens (se enmascaran `bot<token>`, `?p=` y la sesión de la agenda).
- **Un solo bot**: el mismo bot envía muro, agenda y avisos, y escucha los botones del fichaje en
  un hilo propio (así responden al momento).

## Comandos manuales

Dentro del contenedor (`docker compose exec guarderia-monitor python fichaje.py …`):

- `estado`: qué ve en la web (ids, horas y banderas, sin nombres).
- `test-bot`: manda una pregunta de prueba; sus botones no hacen nada real.
- `poll`: **solo lectura**; lista los botones pendientes sin procesarlos. Con el monitor en marcha
  puede responder `error: HTTPError HTTP 409` (dos programas escuchando el mismo bot): es inofensivo.
- `fichar`: **ficha ya, sin preguntar**. Es un «Sí» tuyo explícito; úsalo solo si de verdad quieres fichar.

Si un comando falla, solo imprime el tipo de error (`error: ConnectionError`, `error: HTTPError HTTP 400`…).

## Cómo funciona por dentro

- **Muro y agenda**: tras el login, averigua el centro por la redirección del portal, lee la lista de
  aulas y el enlace de la agenda (que es por familia, no por aula). Compara la lista de aulas con la
  anterior y avisa de los cambios. Por eso no hay que configurar el aula: el portal cambia su
  identificador cada curso y una URL de aula caducada no da error, solo devuelve la portada.
- Revisa el muro cada ~1 h y la agenda cada ~30 min, con esperas aleatorias, solo en horario lectivo.
- **Fichaje**: la web de fichajes (la del QR) pide el DNI y devuelve la ficha de la familia. La
  comprobación de distancia a la guardería la hace solo el navegador; el servidor no recibe
  coordenadas. El estado del fichaje (`/data/fichaje.json`, permisos 0600) guarda las cookies de la
  web y lo necesario para no preguntar ni fichar dos veces.
- Los datos (estado, log `monitor.log` y caché de fotos) viven en `data/`.

## Pruebas

En `tests/` hay pruebas automáticas que no usan la red ni datos reales: `tests/run.sh`.

## Preguntas

- **¿Es seguro?** Tus datos solo están en tu equipo (`secrets/` y `.env`, que no se suben a GitHub)
  y solo se usan contra la web de Work and Life y tu propio Telegram.
- **¿Molesta al portal?** No: consulta con la frecuencia de un padre que mira la web.
- **¿Y si cambia de aula o de curso?** Lo detecta solo y te avisa.
- **¿Funciona con cualquier guardería?** Con las que usan Work and Life (`comunidaddefamilias.com`).

---

*Proyecto casero, sin relación con Work and Life. Úsalo bajo tu responsabilidad.*
