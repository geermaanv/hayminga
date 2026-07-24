/**
 * hayminga.org — Cola de carga manual de eventos por mail.
 *
 * Revisa una casilla de Gmail buscando mails con el asunto etiquetado
 * (SUBJECT_TAG) y un flyer adjunto, guarda la imagen en Drive, y anota
 * una fila en la hoja "Cola_Manual" del mismo Google Sheet que usa el
 * pipeline de Python (main.py -> src/email_intake.py la procesa después).
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
