# 🍼 Guardería Monitor (standalone)

Vigila el **muro** y la **agenda** del portal de familias **Workandlife** y te lo
reenvía a **Telegram** (fotos, vídeos, texto y agenda diaria). **Autocontenido: no
necesita Home Assistant ni nada más.**

## ¿Qué hace?
- 📋 **Muro**: cada publicación nueva → te llega el texto + sus fotos y vídeos.
- 🗓️ **Agenda diaria**: comidas, siestas, deposiciones, observaciones… (se actualiza
  editando el mismo mensaje del día).
- ⏰ Solo en horario lectivo (L-V, 07:00–17:00), con intervalos aleatorios para no
  martillear el portal. Ignora festivos nacionales.

## Requisitos
- Docker.
- Una cuenta del portal **Workandlife** de tu guardería.
- Un **bot de Telegram** (gratis, se crea en 1 minuto).

## Puesta en marcha
1. **Crea tu bot de Telegram**: habla con [@BotFather](https://t.me/BotFather) →
   `/newbot` → copia el **token**.
2. **Saca tu chat id**: manda cualquier mensaje a tu bot y abre
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` → el `chat.id`.
   *(En grupos el id es negativo, p.ej. `-1001234567890`. Si usas grupo, añade el bot al grupo.)*
3. **Encuentra la URL de tu aula**: entra a la web de Workandlife, abre el muro de tu
   peque y copia la URL del navegador (`.../aulas/aula.php?sid=XXXX`).
4. Copia `.env.example` a `.env` y rellena tus datos:
   ```bash
   cp .env.example .env
   nano .env
   ```
5. **Prueba** que todo funciona (login + envío de texto/foto/vídeo, sin arrancar el bucle):
   ```bash
   SELF_TEST=1 docker compose run --rm guarderia-monitor
   ```
   Deberías recibir en Telegram un mensaje `[TEST]` con una foto y un vídeo de la última
   publicación. Si llega → ¡listo!
6. **Arráncalo** en marcha continua:
   ```bash
   docker compose up -d
   ```

## Telegram con "Temas" (opcional)
Si usas un **grupo con Temas/Topics** y quieres separar muro/agenda/avisos en temas
distintos, rellena `TG_THREAD_MURO`, `TG_THREAD_AGENDA` y `TG_THREAD_SISTEMA` con el id
de cada tema. Para un chat normal, **déjalos vacíos**.

## Avisos
- Funciona solo con guarderías sobre la plataforma **Workandlife**.
- Si Workandlife cambia su web (o añade captcha), el scraping puede dejar de funcionar.
- Cada familia corre **su propia instancia** con sus credenciales: tus datos no salen
  de tu contenedor.
