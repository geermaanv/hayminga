/**
 * hayminga.org — Carga manual de eventos (mail + formulario) y directorio
 * de personas con contacto por doble opt-in.
 *
 * 1) Por mail: revisarBandeja() busca en Gmail mails con el asunto
 *    etiquetado (SUBJECT_TAG) y un flyer adjunto, guarda la imagen en
 *    Drive, y anota una fila en "Cola_Manual" del mismo Google Sheet que
 *    usa el pipeline de Python (main.py -> src/email_intake.py la procesa
 *    después, con extracción por IA — el organizador escribe en texto
 *    libre).
 *
 * 2) Por formulario de evento: doPost() con accion="evento" (default,
 *    compatibilidad con el modal viejo que no manda accion) recibe
 *    campos ya estructurados y escribe la fila directo en "Eventos" —
 *    se publica de inmediato, sin esperar la corrida diaria de Python.
 *
 * 3) Directorio de personas: doPost() con accion="directorio_alta" suma
 *    una persona a la hoja "Directorio" (público en el sitio, pero SIN
 *    el email). accion="directorio_contacto" registra un pedido de
 *    contacto y le manda un mail a la persona pedida con un link de
 *    aceptación; doGet() atiende ese link — si acepta, les manda un mail
 *    de presentación a los dos. El email nunca se expone directo en el
 *    sitio, solo se comparte si la persona da el OK.
 *
 * IMPORTANTE sobre la casilla monitoreada / remitente: Apps Script
 * siempre usa la cuenta de Google dueña de este proyecto de script (para
 * leer Gmail Y para mandar mail con MailApp). Hoy corre bajo
 * germanv@gmail.com. Para cambiar a otra dirección (ej.
 * eventos@hayminga.org) más adelante, hay que crear/copiar este mismo
 * proyecto de Apps Script logueado con esa otra cuenta — no alcanza con
 * cambiar una constante acá.
 */

/**
 * Corré esta función UNA VEZ manualmente desde el editor (▶ Ejecutar,
 * eligiéndola del desplegable) para que aparezca el cartel de
 * autorización del permiso de envío de mail (MailApp). doGet/doPost no
 * sirven para esto: solo piden el permiso nuevo cuando el código
 * realmente llega a ejecutar una línea de MailApp, y con un token vacío
 * nunca llegan a esa línea.
 */
function autorizarEnvioDeMail() {
  MailApp.sendEmail(Session.getActiveUser().getEmail(), 'hayminga — autorización de mail OK', 'Si ves este mail, el permiso ya está concedido.');
}


// ---- Configuración (esto sí es lo fácil de cambiar) ----
// Mismo ID que GOOGLE_SPREADSHEET_ID en los secrets de GitHub. No es
// secreto (ya está público en index.html como SHEET_ID), así que va
// hardcodeado acá a propósito: si en algún momento hay que volver a pegar
// Code.gs entero en script.google.com, no hace falta acordarse de
// completar este valor de nuevo.
var SPREADSHEET_ID = '1-kOXgyySgIu2GFQLHuDZvjeDJVpMFbd8MMTsK3gkeXI';
// Cambio TEMPORAL: mientras esté en true, el formulario web tampoco publica
// solo — todo evento nuevo queda 'pendiente_confirmacion' hasta que se
// confirme desde ?pendientes en el sitio. Ver mismo flag en processor.py.
var REVISION_MANUAL = true;
var MAIL_REVISION = 'germanv@gmail.com';
// OJO: Gmail no busca "[Evento]" como texto literal con corchetes — los
// corchetes se ignoran y termina buscando la palabra "evento" en CUALQUIER
// lado del asunto, incluido años de mail viejo sin relación (así se coló
// mail de 2007-2018 la primera vez que se probó esto). Por eso el tag es
// una sola palabra rara, sin espacios ni símbolos.
var SUBJECT_TAG     = 'HME';     // el organizador debe poner esto en el asunto
var QUEUE_SHEET_NAME = 'Cola_Manual';
var DRIVE_FOLDER_NAME = 'hayminga - flyers manuales';
var GMAIL_LABEL_PROCESADO = 'hayminga-procesado';
var DIAS_ATRAS_MAX = 3; // red de seguridad extra: nunca mirar mail más viejo que esto

// Secreto compartido para la acción "subir_imagen" (usada por el pipeline
// de Python, no por el formulario público) — sin esto, cualquiera con la
// URL del Web App podría subir archivos arbitrarios usando el cupo de
// Drive de la cuenta. NO se hardcodea acá (el repo es público) — se lee
// de las Propiedades del Script. Configurarlo UNA VEZ desde el editor:
// Configuración del proyecto (⚙️) → Propiedades del script → Agregar
// propiedad → SUBIR_IMAGEN_SECRETO = (un valor random largo, el mismo
// que se carga como secret de GitHub Actions APPS_SCRIPT_SHARED_SECRET).

var QUEUE_HEADERS = ['Timestamp', 'Remitente', 'Asunto', 'CodigoReferencia', 'CuerpoTexto', 'ImagenDriveUrl', 'Procesado'];
var EVENTOS_SHEET_NAME = 'Eventos';
var MAX_IMAGEN_BYTES = 8 * 1024 * 1024; // 8MB

var DIRECTORIO_SHEET_NAME = 'Directorio';
// El formulario dejo de pedir Tecnicas y AnioDesde (se simplifico a un
// campo de texto libre), pero las columnas se conservan: vacias no molestan
// y evitan una migracion si algun dia se vuelven a pedir.
// Tecnicas y AnioDesde se agregaron al final a proposito (misma regla que
// la hoja Eventos): las posiciones existentes son load-bearing para el
// frontend, que lee por GViz.
//
// Tecnicas guarda pares "tecnica:relacion/relacion" separados por ";" —
// ej: "quincha:hago/enseno; revoques:hago; adobe:estudio/propia".
// Relaciones posibles: hago (para terceros), enseno, estudio, propia
// (lo hizo en obra propia). Formato de texto plano a proposito: se lee a
// ojo desde la Sheet y no necesita escaping como seria con JSON.
// RecibeNovedades se guarda como texto "true"/"false" y no como booleano
// nativo: Apps Script escribiendo booleanos rompe el parseo de GViz del
// frontend (ver PATRONES.md).
var DIRECTORIO_HEADERS = ['Id', 'Nombre', 'Provincia', 'Intereses', 'Descripcion', 'Email', 'Whatsapp', 'Tecnicas', 'AnioDesde', 'RecibeNovedades', 'OfreceServicios'];
var SOLICITUDES_SHEET_NAME = 'SolicitudesContacto';
var SOLICITUDES_HEADERS = ['Id', 'DirectorioId', 'SolicitanteNombre', 'SolicitanteEmail', 'Mensaje', 'Token', 'Estado', 'Timestamp'];


// ---- Formulario web (POST desde hayminga.org) ----

function doPost(e) {
  var respuesta;
  try {
    var data = JSON.parse(e.postData.contents);

    // honeypot anti-spam: campo oculto que un humano nunca completa
    if (data.web) {
      respuesta = { success: true, id: null };
    } else if (data.accion === 'directorio_alta') {
      respuesta = { success: true, id: crearPersonaDirectorio_(data) };
    } else if (data.accion === 'directorio_contacto') {
      respuesta = { success: true, id: solicitarContacto_(data) };
    } else if (data.accion === 'confirmar_evento') {
      respuesta = { success: true, id: confirmarEvento_(data) };
    } else if (data.accion === 'descartar_evento') {
      respuesta = { success: true, id: descartarEvento_(data) };
    } else if (data.accion === 'subir_imagen') {
      respuesta = { success: true, url: subirImagenADrive_(data) };
    } else {
      // accion === 'evento' o sin especificar (compatibilidad con el form viejo)
      respuesta = { success: true, id: crearEventoManual_(data) };
    }
  } catch (err) {
    respuesta = { success: false, error: String(err) };
  }
  return ContentService.createTextOutput(JSON.stringify(respuesta))
    .setMimeType(ContentService.MimeType.JSON);
}


// ---- Directorio: alta, solicitud de contacto y aceptación ----

function crearPersonaDirectorio_(data) {
  if (!data.nombre || !data.email || !data.whatsapp) {
    throw new Error('Faltan campos requeridos (nombre, email, whatsapp)');
  }
  var sheet = getOrCreateSheetWithHeaders_(DIRECTORIO_SHEET_NAME, DIRECTORIO_HEADERS);
  var id = Utilities.getUuid().replace(/-/g, '').substring(0, 10);
  // Separador ";" y no ",": los valores de interes tienen comas adentro
  // ("Organizar mingas, talleres o eventos") y con coma el front los
  // partia al medio al renderizar los chips.
  var intereses = Array.isArray(data.intereses) ? data.intereses.join('; ') : (data.intereses || '');
  // El anio llega como texto libre desde el form; se guarda solo si es un
  // anio plausible, asi un "hace 10 años" mal tipeado no ensucia la columna.
  var anio = String(data.anioDesde || '').trim();
  if (!/^(19|20)\d{2}$/.test(anio)) anio = '';
  appendRowComoTexto_(sheet, [
    id,
    String(data.nombre).trim(),
    data.provincia || '',
    intereses,
    data.descripcion || '',
    String(data.email).trim(),
    data.whatsapp || '',
    String(data.tecnicas || '').trim(),
    anio,
    // Default true si el campo no viene: contempla altas del formulario
    // viejo o de cualquier cliente que todavia no mande el campo. Solo un
    // "false" explicito da de baja.
    data.recibeNovedades === false ? 'false' : 'true',
    data.ofreceServicios === true ? 'true' : 'false',
  ]);

  return id;
}


function solicitarContacto_(data) {
  if (!data.directorioId || !data.solicitanteNombre || !data.solicitanteEmail) {
    throw new Error('Faltan campos requeridos (directorioId, solicitanteNombre, solicitanteEmail)');
  }

  var persona = buscarPersonaDirectorio_(data.directorioId);
  if (!persona) throw new Error('No se encontró esa persona en el directorio');

  var sheet = getOrCreateSheetWithHeaders_(SOLICITUDES_SHEET_NAME, SOLICITUDES_HEADERS);
  var id = Utilities.getUuid().replace(/-/g, '').substring(0, 10);
  var token = Utilities.getUuid().replace(/-/g, '');

  appendRowComoTexto_(sheet, [
    id, data.directorioId, String(data.solicitanteNombre).trim(),
    String(data.solicitanteEmail).trim(), data.mensaje || '', token, 'pendiente', new Date(),
  ], [8]); // columna 8 = Timestamp, es un Date de verdad

  var scriptUrl = ScriptApp.getService().getUrl();
  var linkAceptar = scriptUrl + '?token=' + token;

  MailApp.sendEmail({
    to: persona.email,
    subject: 'Alguien quiere contactarte a través de HayMinga',
    body:
      'Hola ' + persona.nombre + '!\n\n' +
      data.solicitanteNombre + ' (' + data.solicitanteEmail + ') te vio en el directorio ' +
      'de hayminga.org y quiere contactarte' + (data.mensaje ? ':\n\n"' + data.mensaje + '"\n\n' : '.\n\n') +
      'Si querés que los pongamos en contacto, hacé clic acá:\n' + linkAceptar + '\n\n' +
      'Si no te interesa, no hace falta que hagas nada — no se comparte tu email a menos que aceptes.\n\n' +
      '— hayminga.org',
  });

  return id;
}


function doGet(e) {
  var token = e.parameter.token;
  if (!token) {
    return HtmlService.createHtmlOutput('<p>Falta el token.</p>');
  }

  var resultado = aceptarSolicitudContacto_(token);
  var mensaje = resultado
    ? '<h2>¡Listo!</h2><p>Les mandamos un mail a los dos presentándolos. Ya te podés cerrar esta pestaña 🌿</p>'
    : '<h2>Este link ya no es válido</h2><p>O ya fue usado, o la solicitud no existe.</p>';
  return HtmlService.createHtmlOutput(
    '<body style="font-family:sans-serif;max-width:480px;margin:4rem auto;text-align:center;color:#2A1A0A;">' + mensaje + '</body>'
  );
}


function aceptarSolicitudContacto_(token) {
  var sheet = getOrCreateSheetWithHeaders_(SOLICITUDES_SHEET_NAME, SOLICITUDES_HEADERS);
  var datos = sheet.getDataRange().getValues();

  for (var i = 1; i < datos.length; i++) {
    var fila = datos[i];
    if (fila[5] !== token) continue; // columna Token
    if (fila[6] === 'aceptado') return false; // ya usado

    var persona = buscarPersonaDirectorio_(fila[1]);
    if (!persona) return false;

    var solicitanteNombre = fila[2];
    var solicitanteEmail  = fila[3];
    var mensaje           = fila[4];

    sheet.getRange(i + 1, 7).setValue('aceptado'); // columna Estado

    var cuerpoComun =
      'Se conocieron a través del directorio de hayminga.org' +
      (mensaje ? '.\n\nMensaje original: "' + mensaje + '"' : '.') +
      '\n\nDe acá en más, escribanse directo — nosotros ya hicimos la presentación 🌿\n\n— hayminga.org';

    MailApp.sendEmail({
      to: solicitanteEmail,
      cc: persona.email,
      subject: 'Te presentamos a ' + persona.nombre + ' — hayminga.org',
      body: 'Hola ' + solicitanteNombre + ', te presentamos a ' + persona.nombre +
        ' (' + persona.email + ').\n\n' + cuerpoComun,
    });

    return true;
  }
  return false;
}


function buscarPersonaDirectorio_(id) {
  var sheet = getOrCreateSheetWithHeaders_(DIRECTORIO_SHEET_NAME, DIRECTORIO_HEADERS);
  var datos = sheet.getDataRange().getValues();
  for (var i = 1; i < datos.length; i++) {
    if (datos[i][0] === id) {
      return {
        id: datos[i][0], nombre: datos[i][1], provincia: datos[i][2],
        intereses: datos[i][3], descripcion: datos[i][4],
        email: datos[i][5], whatsapp: datos[i][6],
      };
    }
  }
  return null;
}


/**
 * appendRow()/setValues() coacciona valores según el mismo parser que la
 * UI de Sheets: "true"/"false" se vuelven booleanos, y cualquier texto
 * que empiece con "+", "=" o "-" (ej. un WhatsApp "+54 9...") se
 * interpreta como el inicio de una fórmula y puede terminar en #ERROR!.
 * Forzamos formato de texto plano en toda la fila ANTES de escribir,
 * igual que valueInputOption=RAW del lado de Python — así no hay que ir
 * descubriendo columna por columna cuáles rompen (ya pasó dos veces).
 * `columnasExcluir` (1-indexado) es para las pocas columnas que sí llevan
 * un objeto Date de verdad (ej. Timestamp), que si se fuerzan a texto se
 * ven como un número de serie en vez de una fecha legible.
 */
function appendRowComoTexto_(sheet, valores, columnasExcluir) {
  var fila = sheet.getLastRow() + 1;
  var excluir = columnasExcluir || [];
  for (var col = 1; col <= valores.length; col++) {
    if (excluir.indexOf(col) === -1) sheet.getRange(fila, col).setNumberFormat('@');
  }
  sheet.getRange(fila, 1, 1, valores.length).setValues([valores]);
  return fila;
}


function getOrCreateSheetWithHeaders_(nombre, headers) {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(nombre);
  if (!sheet) {
    sheet = ss.insertSheet(nombre);
    sheet.appendRow(headers);
    return sheet;
  }

  // La hoja ya existe: puede tener MENOS columnas que headers si se sumaron
  // columnas nuevas al final despues de crearla (paso al agregar Tecnicas y
  // AnioDesde al Directorio). Sin esto los datos se escriben igual pero sin
  // encabezado, y GViz no puede nombrar la columna — el frontend lee
  // undefined y falla en silencio. Mismo manejo que get_or_create_sheet_with_headers
  // en src/sheets.py, que ya resolvia esto del lado de Python.
  var ancho = sheet.getLastColumn();
  var actuales = ancho ? sheet.getRange(1, 1, 1, ancho).getValues()[0] : [];
  if (actuales.length < headers.length) {
    var faltantes = headers.slice(actuales.length);
    sheet.getRange(1, actuales.length + 1, 1, faltantes.length).setValues([faltantes]);
  }
  return sheet;
}


// Usado por hiker_pipeline.py: la imagen de HikerAPI/Instagram viene de
// un link firmado y temporal (vence) — se sube acá para tener un link
// propio y estable, mismo mecanismo que ya usa crearEventoManual_.
function subirImagenADrive_(data) {
  var secreto = PropertiesService.getScriptProperties().getProperty('SUBIR_IMAGEN_SECRETO');
  if (!secreto || data.secreto !== secreto) {
    throw new Error('No autorizado');
  }
  if (!data.imagen_base64) {
    throw new Error('Falta imagen_base64');
  }
  var bytes = Utilities.base64Decode(data.imagen_base64);
  if (bytes.length > MAX_IMAGEN_BYTES) {
    throw new Error('Imagen demasiado grande (máx 8MB)');
  }
  var folder = getOrCreateFolder_('hayminga - imagenes de eventos');
  var blob = Utilities.newBlob(bytes, data.imagen_mime || 'image/jpeg', data.imagen_nombre || 'evento.jpg');
  var file = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return 'https://drive.google.com/thumbnail?id=' + file.getId() + '&sz=w1000';
}


function crearEventoManual_(data) {
  if (!data.nombre || !data.fecha_inicio || !data.imagen_base64) {
    throw new Error('Faltan campos requeridos (nombre, fecha_inicio, imagen)');
  }

  var bytes = Utilities.base64Decode(data.imagen_base64);
  if (bytes.length > MAX_IMAGEN_BYTES) {
    throw new Error('Imagen demasiado grande (máx 8MB)');
  }

  var folder = getOrCreateFolder_(DRIVE_FOLDER_NAME);
  var blob = Utilities.newBlob(bytes, data.imagen_mime || 'image/jpeg', data.imagen_nombre || 'flyer.jpg');
  var file = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  var driveUrl = 'https://drive.google.com/thumbnail?id=' + file.getId() + '&sz=w1000';

  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(EVENTOS_SHEET_NAME) || ss.getSheets()[0];

  var fechaInicioIso = normalizarFecha_(data.fecha_inicio);
  var fechaFinIso    = data.fecha_fin ? normalizarFecha_(data.fecha_fin) : '';
  var periodo        = fechaInicioIso ? fechaInicioIso.split('/').reverse().slice(0, 2).join('-') : '';
  var nombre         = String(data.nombre).trim();
  var id             = Utilities.getUuid().replace(/-/g, '').substring(0, 10);

  // mismo orden que COLUMNS en import/src/sheets.py — si se agrega una
  // columna ahí, hay que agregarla acá también en la misma posición
  var valores = [
    REVISION_MANUAL ? 'false' : 'true',
    nombre,
    data.direccion || '',
    periodo,
    fechaInicioIso,
    fechaFinIso,
    data.es_virtual ? 'true' : 'false',
    data.provincia || '',
    data.descripcion || '',
    data.organizador || '',
    data.link_promocional || '',
    data.tipo_evento || '',
    driveUrl,
    nombre.toLowerCase(),
    id,
    data.contacto || '',
    REVISION_MANUAL ? 'pendiente_confirmacion' : 'confirmado',
    'Argentina', // el form web es para eventos locales; no se pregunta país
    'alta',
    'formulario_web',
    new Date().toISOString(),
    data.latitud || '',
    data.longitud || '',
  ];

  appendRowComoTexto_(sheet, valores);

  return id;
}


// ---- Revisión manual (cambio temporal) ----

function confirmarEvento_(data) {
  if (!data.id) throw new Error('Falta el id del evento a confirmar');

  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(EVENTOS_SHEET_NAME);
  var ultimaFila = sheet.getLastRow();
  var ids = sheet.getRange(2, 15, ultimaFila - 1, 1).getValues(); // columna O = Id
  var filaEncontrada = -1;
  for (var i = 0; i < ids.length; i++) {
    if (String(ids[i][0]) === String(data.id)) { filaEncontrada = i + 2; break; }
  }
  if (filaEncontrada === -1) throw new Error('No se encontró el evento ' + data.id);

  var fechaInicioIso = data.fecha_inicio ? normalizarFecha_(data.fecha_inicio) : '';
  var fechaFinIso    = data.fecha_fin ? normalizarFecha_(data.fecha_fin) : '';
  var periodo        = fechaInicioIso ? fechaInicioIso.split('/').reverse().slice(0, 2).join('-') : '';
  var nombre         = String(data.nombre || '').trim();

  var valores = [[
    'true',
    nombre,
    data.direccion || '',
    periodo,
    fechaInicioIso,
    fechaFinIso,
    data.es_virtual ? 'true' : 'false',
    data.provincia || '',
    data.descripcion || '',
    data.organizador || '',
    data.link_promocional || '',
    data.tipo_evento || '',
    data.img || '',
    nombre.toLowerCase(),
    data.id,
    data.contacto || '',
    'confirmado',
    data.pais || 'Argentina',
    data.confianza || '',
    data.fuente || '',
    data.fecha_descubrimiento || '',
    data.latitud || '',
    data.longitud || '',
  ]];
  var rango = sheet.getRange(filaEncontrada, 1, 1, valores[0].length);
  rango.setNumberFormat('@'); // texto plano, evita que Sheets convierta a booleano/fecha
  rango.setValues(valores);
  return data.id;
}


// Descarta un evento pendiente sin borrar la fila (columna 1 = Activo,
// columna 17 = Estado) — queda en la planilla por si hace falta revisarlo
// o revertirlo a mano, pero nunca se publica.
function descartarEvento_(data) {
  if (!data.id) throw new Error('Falta el id del evento a descartar');

  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(EVENTOS_SHEET_NAME);
  var ultimaFila = sheet.getLastRow();
  var ids = sheet.getRange(2, 15, ultimaFila - 1, 1).getValues(); // columna O = Id
  var filaEncontrada = -1;
  for (var i = 0; i < ids.length; i++) {
    if (String(ids[i][0]) === String(data.id)) { filaEncontrada = i + 2; break; }
  }
  if (filaEncontrada === -1) throw new Error('No se encontró el evento ' + data.id);

  sheet.getRange(filaEncontrada, 1).setNumberFormat('@').setValue('false');
  sheet.getRange(filaEncontrada, 17).setNumberFormat('@').setValue('descartado');
  return data.id;
}


/**
 * Corré esta función UNA VEZ desde el editor para instalar el trigger
 * periódico que manda el mail de "eventos pendientes de revisión". Se
 * puede volver a correr sin problema (borra el trigger viejo primero).
 */
function configurarTriggerNotificaciones() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'notificarPendientes') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('notificarPendientes').timeBased().everyMinutes(30).create();
}

function notificarPendientes() {
  if (!REVISION_MANUAL) return;
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(EVENTOS_SHEET_NAME);
  var props = PropertiesService.getScriptProperties();
  var desde = Number(props.getProperty('ultima_fila_notificada_pendientes') || 1) + 1;
  var ultimaFila = sheet.getLastRow();
  if (desde > ultimaFila) return;

  var filas = sheet.getRange(desde, 1, ultimaFila - desde + 1, 17).getValues(); // hasta columna Q = Estado
  var pendientes = [];
  filas.forEach(function(row) {
    if (row[16] === 'pendiente_confirmacion') pendientes.push(row[1]); // columna B = Nombre
  });
  props.setProperty('ultima_fila_notificada_pendientes', String(ultimaFila));
  if (pendientes.length === 0) return;

  var lista = pendientes.map(function(n) { return '• ' + (n || '(sin nombre)'); }).join('\n');
  MailApp.sendEmail({
    to: MAIL_REVISION,
    subject: 'hayminga — ' + pendientes.length + ' evento(s) para revisar',
    body: 'Nuevos eventos pendientes de confirmación:\n\n' + lista +
      '\n\nRevisalos acá: https://hayminga.org/?pendientes'
  });
}


/**
 * Corré esta función UNA VEZ desde el editor para instalar el trigger
 * semanal del resumen de eventos por mail al Directorio. Se puede
 * volver a correr sin problema (borra el trigger viejo primero).
 */
function configurarTriggerResumenSemanal() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'enviarResumenSemanalDirectorio') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('enviarResumenSemanalDirectorio')
    .timeBased().onWeekDay(ScriptApp.WeekDay.TUESDAY).atHour(9).create();
}

/**
 * Mismo resumen semanal que se manda por Telegram (ver
 * import/src/enviar_resumen_telegram.py), pero por mail a cada persona
 * del Directorio — todas dieron consentimiento explícito al anotarse
 * (checkbox "Autorizo a que me manden novedades y avisos de hayminga").
 */
function enviarResumenSemanalDirectorio() {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);

  var dirSheet = ss.getSheetByName(DIRECTORIO_SHEET_NAME);
  if (!dirSheet || dirSheet.getLastRow() < 2) return;
  // Columnas F..J = Email .. RecibeNovedades. Se respeta la baja: solo un
  // "false" explicito excluye, asi las filas viejas (anteriores a que la
  // columna existiera, con la celda vacia) siguen recibiendo como antes.
  var emails = dirSheet.getRange(2, 6, dirSheet.getLastRow() - 1, 5).getValues()
    .filter(function(r) { return String(r[4] || '').trim().toLowerCase() !== 'false'; })
    .map(function(r) { return String(r[0] || '').trim(); })
    .filter(function(e) { return e; });
  if (emails.length === 0) return;

  var eventos = proximosEventosActivos_();
  var cuerpo = armarCuerpoResumen_(eventos);
  var asunto = 'Nuevos cursos, talleres y eventos de bioconstrucción — hayminga.org';

  emails.forEach(function(email) {
    MailApp.sendEmail({ to: email, subject: asunto, body: cuerpo });
  });
}

var _CTA_RESUMEN = '¿Conocés un evento? Compartí la captura o el link por WhatsApp, ' +
  'mandalo por mail, o si publicás vos en Instagram taggeá #hayminga.';

function proximosEventosActivos_(diasHaciaAdelante, maxEventos) {
  diasHaciaAdelante = diasHaciaAdelante || 60;
  maxEventos = maxEventos || 15;

  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(EVENTOS_SHEET_NAME);
  var ultimaFila = sheet.getLastRow();
  if (ultimaFila < 2) return [];

  var filas = sheet.getRange(2, 1, ultimaFila - 1, 12).getValues(); // hasta columna L = Tipo_Evento
  var hoy = new Date(); hoy.setHours(0, 0, 0, 0);
  var limite = new Date(hoy.getTime() + diasHaciaAdelante * 24 * 60 * 60 * 1000);

  var eventos = [];
  filas.forEach(function(row) {
    if (row[0] !== 'true') return; // columna A = Activo
    var fecha = parsearFechaDDMMYYYY_(row[4]); // columna E = Fecha_Inicio
    if (!fecha || fecha < hoy || fecha > limite) return;
    eventos.push({
      nombre: row[1], fecha: fecha, provincia: row[7],
      esVirtual: row[6] === 'true', tipoEvento: row[11], link: row[10],
    });
  });

  eventos.sort(function(a, b) { return a.fecha - b.fecha; });
  return eventos.slice(0, maxEventos);
}

function parsearFechaDDMMYYYY_(valor) {
  var m = String(valor || '').match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!m) return null;
  return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
}

function armarCuerpoResumen_(eventos) {
  if (eventos.length === 0) {
    return 'Esta semana no hay eventos nuevos confirmados para los próximos días.\n\n' + _CTA_RESUMEN;
  }
  var lineas = ['https://hayminga.org', '', _CTA_RESUMEN, ''];
  eventos.forEach(function(ev) {
    var fechaStr = Utilities.formatDate(ev.fecha, 'GMT-3', 'dd/MM');
    var lugar = ev.esVirtual ? 'Virtual' : (ev.provincia || '');
    var partes = [lugar, ev.tipoEvento].filter(function(p) { return p; });
    var encabezado = partes.join(' - ');
    var linea = fechaStr + (encabezado ? ' | ' + encabezado : '') + ' — ' + ev.nombre;
    lineas.push(linea);
    if (ev.link) lineas.push(ev.link);
    lineas.push('');
  });
  lineas.push(_CTA_RESUMEN);
  return lineas.join('\n');
}


function normalizarFecha_(fechaStr) {
  // el <input type="date"> del form manda YYYY-MM-DD; el resto del
  // pipeline (Python + frontend) usa DD/MM/YYYY para Fecha_Inicio/Fecha_Fin
  var m = String(fechaStr).match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return fechaStr;
  return m[3] + '/' + m[2] + '/' + m[1];
}


function revisarBandeja() {
  var label = getOrCreateLabel_(GMAIL_LABEL_PROCESADO);
  var query = 'subject:' + SUBJECT_TAG + ' newer_than:' + DIAS_ATRAS_MAX + 'd -label:' + GMAIL_LABEL_PROCESADO;
  var threads = GmailApp.search(query, 0, 20);

  if (threads.length === 0) {
    Logger.log('Sin mails nuevos de eventos.');
    return;
  }

  var folder = getOrCreateFolder_(DRIVE_FOLDER_NAME);
  var sheet  = getOrCreateSheetWithHeaders_(QUEUE_SHEET_NAME, QUEUE_HEADERS);

  threads.forEach(function (thread) {
    var messages = thread.getMessages();
    var msg = messages[messages.length - 1]; // el más reciente del hilo

    try {
      procesarMensaje_(msg, folder, sheet);
    } catch (e) {
      Logger.log('Error procesando mensaje "' + msg.getSubject() + '": ' + e);
    } finally {
      // se marca igual para no reintentar en loop si algo falla siempre
      thread.addLabel(label);
    }
  });
}


function procesarMensaje_(msg, folder, sheet) {
  var attachments = msg.getAttachments();
  var imagen = attachments.filter(function (a) {
    return a.getContentType().indexOf('image/') === 0;
  })[0];

  var remitente = msg.getFrom().replace(/.*<(.+)>.*/, '$1'); // "Nombre <mail>" -> "mail"
  var asunto    = msg.getSubject();
  var cuerpo    = msg.getPlainBody().substring(0, 2000);

  // Si no viene el flyer adjunto, alcanza con que el cuerpo tenga un link
  // (ej. alguien reenvía el post de Instagram): el pipeline de Python baja
  // la imagen del post automáticamente a partir de ese link.
  if (!imagen && !/https?:\/\/\S+/.test(cuerpo)) {
    Logger.log('Mail "' + asunto + '" sin imagen adjunta ni link, se ignora.');
    return;
  }

  var driveUrl = '';
  if (imagen) {
    var file = folder.createFile(imagen);
    file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    driveUrl = 'https://drive.google.com/thumbnail?id=' + file.getId() + '&sz=w1000';
  }

  var codigo = extraerCodigo_(asunto + ' ' + cuerpo);

  appendRowComoTexto_(sheet, [
    new Date(),
    remitente,
    asunto,
    codigo,
    cuerpo,
    driveUrl,
    '', // Procesado — lo completa el pipeline de Python
  ], [1]); // columna 1 = Timestamp, es un Date de verdad

  Logger.log('Encolado: ' + asunto + ' (' + remitente + ')');
}


function extraerCodigo_(texto) {
  var m = texto.match(/c[oó]digo[:\s]+([a-zA-Z0-9]+)/i);
  return m ? m[1] : '';
}


function getOrCreateFolder_(name) {
  var folders = DriveApp.getFoldersByName(name);
  return folders.hasNext() ? folders.next() : DriveApp.createFolder(name);
}


function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}
