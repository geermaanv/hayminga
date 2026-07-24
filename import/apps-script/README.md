# Cola de carga manual por mail — setup (una sola vez)

Este script lee la casilla de Gmail de la cuenta que lo despliegue (hoy
`germanv@gmail.com`), busca mails con `HAYMINGAEVENTO` en el asunto y un
flyer adjunto, y anota una fila en la hoja `Cola_Manual` del mismo Google
Sheet que ya usa el pipeline de Python. `main.py` (paso 4/4) la procesa
automáticamente en cada corrida diaria — no hace falta correr nada más.

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
   contenido de [`Code.gs`](Code.gs), reemplazando todo lo anterior.
3. Arriba del archivo, reemplazá:
   ```
   var SPREADSHEET_ID = 'PEGAR_AQUI_EL_MISMO_ID_QUE_GOOGLE_SPREADSHEET_ID_EN_GITHUB';
   ```
   por el mismo ID que ya tenés cargado como secret `GOOGLE_SPREADSHEET_ID`
   en GitHub (está en la URL de la Sheet: `spreadsheets/d/ESTE_ID/edit`).
4. Guardá el proyecto (podés nombrarlo "hayminga - cola manual").
5. **Ejecutar → revisarBandeja** una vez manualmente desde el editor. Te va
   a pedir autorizar permisos (Gmail, Drive, Sheets) — es normal, es tu
   propia cuenta autorizando a tu propio script.
6. **Triggers (el ícono de reloj, a la izquierda)** → revisá que exista un
   trigger de `revisarBandeja` (Time-driven, cada 15-30 min). Si ya lo
   habías creado con la versión vieja, no hace falta recrearlo — el código
   nuevo lo va a usar automáticamente.

Listo — de ahí en más corre solo.

## Cómo lo usa un organizador

Le pedís que mande un mail a `germanv@gmail.com` con:
- Asunto: que contenga `HAYMINGAEVENTO` (ej. `HAYMINGAEVENTO Taller de adobe`)
- El flyer adjunto (como imagen, en la resolución que tenga)
- En el cuerpo: fecha, lugar, y cualquier dato de contacto — se lo pasamos
  tal cual a la IA como contexto extra, igual que el caption de Instagram

El botón "+ Nuevo Evento" del sitio ya arma este formato automáticamente.

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
