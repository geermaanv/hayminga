/**
 * hayminga.org — Carga manual de eventos: por mail y por formulario web.
 *
 * 1) Por mail: revisarBandeja() busca en Gmail mails con el asunto
 *    etiquetado (SUBJECT_TAG) y un flyer adjunto, guarda la imagen en
 *    Drive, y anota una fila en "Cola_Manual" del mismo Google Sheet que
 *    usa el pipeline de Python (main.py -> src/email_intake.py la procesa
 *    después, con extracción por IA — el organizador escribe en texto
 *    libre).
 *
 * 2) Por formulario: doPost() recibe el submit del modal de hayminga.org
 *    (campos ya estructurados, sin necesidad de IA) y escribe la fila
 *    directo en "Eventos" — se publica de inmediato, sin esperar la
 *    corrida diaria del pipeline de Python.
 *
 * IMPORTANTE sobre la casilla monitoreada: Apps Script siempre lee el
 * Gmail de la cuenta de Google dueña de este proyecto de script. Hoy
 * corre bajo germanv@gmail.com. Para cambiar a otra dirección (ej.
 * eventos@hayminga.org) más adelante, hay que crear/copiar este mismo
 * proyecto de Apps Script logueado con esa otra cuenta — no alcanza con
 * cambiar una constante acá.
 */

// ---- Configuración (esto sí es lo fácil de cambiar) ----
var SPREADSHEET_ID = 'PEGAR_AQUI_EL_MISMO_ID_QUE_GOOGLE_SPREADSHEET_ID_EN_GITHUB';
// OJO: Gmail no busca "[Evento]" como texto literal con corchetes — los
// corchetes se ignoran y termina buscando la palabra "evento" en CUALQUIER
// lado del asunto, incluido años de mail viejo sin relación (así se coló
// mail de 2007-2018 la primera vez que se probó esto). Por eso el tag es
// una sola palabra rara, sin espacios ni símbolos.
var SUBJECT_TAG     = 'HAYMINGAEVENTO';     // el organizador debe poner esto en el asunto
var QUEUE_SHEET_NAME = 'Cola_Manual';
var DRIVE_FOLDER_NAME = 'hayminga - flyers manuales';
var GMAIL_LABEL_PROCESADO = 'hayminga-procesado';
var DIAS_ATRAS_MAX = 3; // red de seguridad extra: nunca mirar mail más viejo que esto

var QUEUE_HEADERS = ['Timestamp', 'Remitente', 'Asunto', 'CodigoReferencia', 'CuerpoTexto', 'ImagenDriveUrl', 'Procesado'];
var EVENTOS_SHEET_NAME = 'Eventos';
var MAX_IMAGEN_BYTES = 8 * 1024 * 1024; // 8MB


// ---- Formulario web (POST desde hayminga.org) ----

function doPost(e) {
  var respuesta;
  try {
    var data = JSON.parse(e.postData.contents);

    // honeypot anti-spam: campo oculto que un humano nunca completa
    if (data.web) {
      respuesta = { success: true, id: null };
    } else {
      var id = crearEventoManual_(data);
      respuesta = { success: true, id: id };
    }
  } catch (err) {
    respuesta = { success: false, error: String(err) };
  }
  return ContentService.createTextOutput(JSON.stringify(respuesta))
    .setMimeType(ContentService.MimeType.JSON);
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
  var driveUrl = 'https://drive.google.com/uc?export=view&id=' + file.getId();

  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(EVENTOS_SHEET_NAME) || ss.getSheets()[0];

  var fechaInicioIso = normalizarFecha_(data.fecha_inicio);
  var fechaFinIso    = data.fecha_fin ? normalizarFecha_(data.fecha_fin) : '';
  var periodo        = fechaInicioIso ? fechaInicioIso.split('/').reverse().slice(0, 2).join('-') : '';
  var nombre         = String(data.nombre).trim();
  var id             = Utilities.getUuid().replace(/-/g, '').substring(0, 10);

  // mismo orden que COLUMNS en import/src/sheets.py — si se agrega una
  // columna ahí, hay que agregarla acá también en la misma posición
  sheet.appendRow([
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
    driveUrl,
    nombre.toLowerCase(),
    id,
    data.contacto || '',
    'confirmado',
  ]);

  return id;
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
  var query = 'subject:' + SUBJECT_TAG + ' has:attachment newer_than:' + DIAS_ATRAS_MAX + 'd -label:' + GMAIL_LABEL_PROCESADO;
  var threads = GmailApp.search(query, 0, 20);

  if (threads.length === 0) {
    Logger.log('Sin mails nuevos de eventos.');
    return;
  }

  var folder = getOrCreateFolder_(DRIVE_FOLDER_NAME);
  var sheet  = getOrCreateQueueSheet_();

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

  if (!imagen) {
    Logger.log('Mail "' + msg.getSubject() + '" sin imagen adjunta, se ignora.');
    return;
  }

  var file = folder.createFile(imagen);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  var driveUrl = 'https://drive.google.com/uc?export=view&id=' + file.getId();

  var remitente = msg.getFrom().replace(/.*<(.+)>.*/, '$1'); // "Nombre <mail>" -> "mail"
  var asunto    = msg.getSubject();
  var cuerpo    = msg.getPlainBody().substring(0, 2000);
  var codigo    = extraerCodigo_(asunto + ' ' + cuerpo);

  sheet.appendRow([
    new Date(),
    remitente,
    asunto,
    codigo,
    cuerpo,
    driveUrl,
    '', // Procesado — lo completa el pipeline de Python
  ]);

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


function getOrCreateQueueSheet_() {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(QUEUE_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(QUEUE_SHEET_NAME);
    sheet.appendRow(QUEUE_HEADERS);
  }
  return sheet;
}
