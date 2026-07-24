# Carga manual de eventos — setup (una sola vez)

Dos formas de cargar un evento a mano, mismo script:

1. **Por mail** (`revisarBandeja`): lee la casilla de Gmail de la cuenta
   que despliega el script (hoy `germanv@gmail.com`), busca mails con
   `HAYMINGAEVENTO` en el asunto y un flyer adjunto, y anota una fila en
   `Cola_Manual`. `main.py` (paso 4/4) la procesa en la corrida diaria,
   extrayendo los datos con IA (Gemini/Claude) — pensado para texto libre.

2. **Por formulario** (`doPost`): el modal "+ Nuevo Evento" de
   hayminga.org manda los campos ya estructurados (el organizador los
   tipeó) más el flyer en base64. El script sube la imagen a Drive y
   escribe la fila **directo en "Eventos"** — sin pasar por IA ni esperar
   la corrida diaria, se publica al instante.

## ⚠️ Si ya desplegaste una versión anterior de este script

La primera versión usaba `[Evento]` como tag y buscaba `subject:"[Evento]"`.
**Gmail no busca corchetes como texto literal** — los ignora y termina
buscando la palabra "evento" en cualquier parte del asunto, sin límite de
fecha. Esto hizo que escaneara mail viejo sin relación (invitaciones a
eventos corporativos de años atrás) y hasta llegó a insertar 2 entradas
falsas en la Sheet de producción (ya se corrigieron a mano).

**Si ya tenés el script viejo corriendo: reemplazá `Code.gs` por la versión
actual y volvé a autorizarlo.** El tag nuevo es una sola palabra sin
símbolos (`HAYMINGAEVENTO`) y la búsqueda ahora tiene un límite de
`newer_than:3d` como red de seguridad extra, aunque el tag vuelva a fallar
por algún motivo.

## Pasos

1. Entrá a [script.google.com](https://script.google.com) logueado con
   `germanv@gmail.com` (la cuenta que va a "ser" la casilla monitoreada).
2. **Proyecto nuevo** (o el existente, si estás actualizando) → pegá el
   contenido de [`Code.gs`](Code.gs) tal cual, reemplazando todo lo
   anterior. El `SPREADSHEET_ID` ya viene hardcodeado en el archivo (no es
   secreto, es el mismo que `SHEET_ID` en `index.html`) — no hace falta
   editar nada antes de guardar.
3. Guardá el proyecto (podés nombrarlo "hayminga - cola manual").
4. **Ejecutar → revisarBandeja** una vez manualmente desde el editor. Te va
   a pedir autorizar permisos (Gmail, Drive, Sheets) — es normal, es tu
   propia cuenta autorizando a tu propio script.
5. **Triggers (el ícono de reloj, a la izquierda)** → revisá que exista un
   trigger de `revisarBandeja` (Time-driven, cada 15-30 min). Si ya lo
   habías creado con la versión vieja, no hace falta recrearlo — el código
   nuevo lo va a usar automáticamente.

Listo — de ahí en más el mail corre solo.

## Desplegar el formulario web (doPost)

Esto es aparte del trigger de mail — es lo que le da vida al modal
"+ Nuevo Evento" del sitio.

1. En el mismo proyecto de Apps Script → **Implementar** (arriba a la
   derecha) → **Nueva implementación**.
2. Tipo: **Aplicación web**.
3. Configuración:
   - Ejecutar como: **Yo** (tu cuenta)
   - Quién tiene acceso: **Cualquier usuario** (tiene que ser público para
     que el sitio le pueda mandar el POST desde el navegador de cualquiera)
4. **Implementar** → copiá la URL que te da (termina en `/exec`).
5. En `index.html`, buscá esta línea (cerca del principio del `<script>`):
   ```js
   var APPS_SCRIPT_URL = 'PEGAR_AQUI_LA_URL_DEL_WEB_APP_DESPLEGADO';
   ```
   y pegá la URL copiada. Commiteá y pusheá — GitHub Pages lo publica solo.

**Si después modificás `Code.gs`**: los cambios no se reflejan en la URL
ya desplegada automáticamente. Hay que ir de nuevo a Implementar →
Administrar implementaciones → ✏️ (editar) → Nueva versión → Implementar.
La URL no cambia, así que no hace falta tocar `index.html` de nuevo.

## Directorio de personas (contacto por doble opt-in)

Mismo Web App (`doPost`/`doGet`), dos acciones más:

- **Alta** (`accion: "directorio_alta"`, modal "+ Sumarme"): escribe una
  fila en la hoja `Directorio` (`Id, Nombre, Provincia, Intereses,
  Descripcion, Email, Whatsapp`). El sitio la lee pública, pero `Email` y
  `Whatsapp` nunca se mandan al navegador — solo viven en la Sheet.
  `Provincia` sale de una lista fija de las 24 provincias argentinas
  (definida en `index.html` como `PROVINCIAS_ARGENTINA`, no texto libre,
  para no ensuciar el dato). `Intereses` son checkboxes de una lista fija
  también (`INTERESES_CATEGORIAS` en `index.html`), guardados como texto
  separado por comas.
- **Solicitar contacto** (`accion: "directorio_contacto"`, botón "Quiero
  contactar" en cada tarjeta): guarda el pedido en `SolicitudesContacto`
  y le manda un mail a la persona pedida con un link de aceptación
  (`doGet` con un token). Si acepta, `MailApp` les manda un mail a los
  dos presentándolos — recién ahí se cruzan los emails.

El sitio también deja filtrar el directorio por provincia (mismo select
fijo) arriba de la grilla.

Ambas hojas (`Directorio`, `SolicitudesContacto`) se crean solas la
primera vez que se usan, con `getOrCreateSheetWithHeaders_`. No hace
falta crearlas a mano.

Deliberadamente mínimo por ahora: sin roles, sin moderación, sin
categorías — solo nombre + descripción libre + provincia + contacto. Se
puede complicar después si hace falta.

## Cómo lo usa un organizador

**Formulario (recomendado):** clic en "+ Nuevo Evento" en el sitio, completa
los campos y sube el flyer — se publica al toque, sin esperar nada.

**Por mail (alternativa):** mandar un mail a `germanv@gmail.com` con:
- Asunto: que contenga `HAYMINGAEVENTO` (ej. `HAYMINGAEVENTO Taller de adobe`)
- El flyer adjunto (como imagen, en la resolución que tenga)
- En el cuerpo: fecha, lugar, y cualquier dato de contacto — se lo pasamos
  tal cual a la IA como contexto extra, igual que el caption de Instagram

El modal del formulario tiene un link a este mail como alternativa, por si
alguien prefiere mandarlo así en vez de completar los campos.

## Cuando se quiera pasar a una casilla del dominio (eventos@hayminga.org)

Apps Script siempre lee el Gmail de la cuenta que es dueña del proyecto.
No alcanza con cambiar una variable: hay que crear este mismo script de
nuevo logueado con la cuenta `eventos@hayminga.org` (o dar permisos de
"Gmail delegado" desde Google Workspace si en algún momento hay uno), y
apagar el trigger del proyecto viejo para no procesar el mismo mail dos
veces.

## Notas

- `revisarBandeja` es idempotente: cada hilo procesado se marca con la
  etiqueta Gmail `hayminga-procesado`, así no se vuelve a encolar aunque
  el trigger corra de nuevo.
- Si un mail no tiene ninguna imagen adjunta, se ignora (se loguea pero
  no se encola).
- La imagen se guarda en una carpeta de Drive llamada
  `hayminga - flyers manuales`, compartida como "cualquiera con el link
  puede ver" (necesario para que el pipeline de Python la pueda descargar).
- `email_intake.py`, del lado de Python, marca como `error` cualquier fila
  de `Cola_Manual` que no pudo procesar (imagen no descargable, o el
  extractor no la reconoció como evento) — quedan visibles en esa hoja
  para revisar a mano, no se pierden ni se reintentan solas.
- El formulario web rechaza imágenes de más de 8MB y tiene un campo
  honeypot (`web`) para filtrar spam automático básico — no es protección
  fuerte, pero corta bots genéricos sin agregar un captcha.
- `doPost` no valida quién manda el POST (tiene que ser público para que
  el sitio le llegue) — cualquiera que descubra la URL del Web App podría
  mandar datos directo. Es el mismo nivel de exposición que un Google Form
  público; si se vuelve un problema, la solución es agregar moderación
  (Estado=pendiente en vez de confirmado) en vez de autenticación.
