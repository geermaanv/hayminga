"""
candidates.py — ARCHIVADO, no corre en producción (ver ROADMAP.md).

Cola de reintentos persistente (hoja `Candidatos`) del pipeline viejo
de Google Images — hiker_pipeline.py no tiene cola de reintentos a
propósito ("no pasa nada si falla un día", ver su docstring). Se
guarda como referencia histórica; el import de scraper de abajo ya no
resuelve (esas funciones viven en scraper_google_images.py, en esta
misma carpeta) — no lo ejecutes tal cual.
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from legacy.scraper_google_images import HEADERS, IMAGES_DIR, is_valid_image, passes_quality_filter
from src.sheets import SPREADSHEET_ID, get_service


SHEET_NAME = "Candidatos"
MAX_ATTEMPTS = 3
COLUMNS = [
    "Id",
    "Descubierto",
    "Fuente",
    "Consulta",
    "URL_Publicacion",
    "URL_Imagen",
    "Hash",
    "Estado",
    "Intentos",
    "Confianza",
    "Motivo",
    "Ultimo_Error",
    "Nombre_Extraido",
    "Fecha_Extraida",
    "Provincia_Extraida",
    "Evento_Id",
    "Caption",
]
TERMINAL_STATES = {"publicado", "descartado", "duplicado"}
RETRY_STATES = {"nuevo", "procesando", "extraido", "reintentar"}


def candidate_key(metadata: dict) -> str:
    link = str(metadata.get("link") or "").strip().rstrip("/")
    if link:
        return f"link:{link}"
    return f"hash:{str(metadata.get('hash') or '').strip()}"


def _candidate_from_row(row: list, sheet_row: int) -> dict:
    row = (row + [""] * len(COLUMNS))[:len(COLUMNS)]
    return {
        "id": row[0],
        "discovered_at": row[1],
        "source": row[2],
        "query": row[3],
        "link": row[4],
        "thumbnail": row[5],
        "hash": row[6],
        "status": str(row[7] or "").lower(),
        "attempts": int(row[8] or 0),
        "confidence": row[9],
        "reason": row[10],
        "last_error": row[11],
        "name": row[12],
        "start_date": row[13],
        "province": row[14],
        "event_id": row[15],
        "caption": row[16],
        "_candidate_row": sheet_row,
    }


def _candidate_metadata(candidate: dict) -> dict:
    return {
        "link": candidate["link"],
        "thumbnail": candidate["thumbnail"],
        "hash": candidate["hash"],
        "source": candidate["source"] or "google_images",
        "query": candidate["query"],
        "discovered_at": candidate["discovered_at"],
        "caption": candidate.get("caption", ""),
        "_candidate_id": candidate["id"],
        "_candidate_row": candidate["_candidate_row"],
        "_candidate_attempts": candidate["attempts"],
    }


class CandidateStore:
    def __init__(self, service=None):
        self.service = service or get_service()
        self._ensure_sheet()

    def _ensure_sheet(self):
        spreadsheet = self.service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID,
            fields="sheets.properties.title",
        ).execute()
        titles = {
            sheet["properties"]["title"]
            for sheet in spreadsheet.get("sheets", [])
        }
        if SHEET_NAME not in titles:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests": [{"addSheet": {"properties": {"title": SHEET_NAME}}}]},
            ).execute()

        result = self.service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!1:1",
        ).execute()
        current = result.get("values", [[]])
        current = current[0] if current else []
        if current != COLUMNS:
            if current and current != COLUMNS[:len(current)]:
                raise RuntimeError(
                    f"Header incompatible en {SHEET_NAME}: {current}"
                )
            self.service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A1",
                valueInputOption="RAW",
                body={"values": [COLUMNS]},
            ).execute()

    def load_all(self) -> list[dict]:
        result = self.service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A2:Q",
        ).execute()
        return [
            _candidate_from_row(row, index + 2)
            for index, row in enumerate(result.get("values", []))
            if row and row[0]
        ]

    def register(self, items: list[tuple[Path, dict]]) -> list[tuple[Path, dict]]:
        """Registra candidatos nuevos y devuelve solo los que deben procesarse."""
        existing = {candidate_key(candidate): candidate for candidate in self.load_all()}
        ready = []
        new_rows = []
        new_items = []

        for path, metadata in items:
            found = existing.get(candidate_key(metadata))
            if found:
                # Los estados reintentables ya se cargaron al comienzo de la
                # corrida con load_retries(); no duplicarlos si Google vuelve
                # a devolver el mismo post en esta búsqueda.
                continue

            candidate_id = uuid.uuid4().hex[:12]
            discovered_at = metadata.get("discovered_at") or datetime.now(timezone.utc).isoformat()
            row = [
                candidate_id,
                discovered_at,
                metadata.get("source") or "google_images",
                metadata.get("query") or "",
                metadata.get("link") or "",
                metadata.get("thumbnail") or "",
                metadata.get("hash") or "",
                "nuevo",
                0,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                metadata.get("caption") or "",
            ]
            new_rows.append(row)
            new_items.append((path, metadata, candidate_id, discovered_at))

        if new_rows:
            response = self.service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": new_rows},
            ).execute()
            updated_range = response.get("updates", {}).get("updatedRange", "")
            match = re.search(r"!A(\d+):", updated_range)
            if not match:
                raise RuntimeError(f"No se pudo determinar las filas insertadas: {updated_range}")
            first_row = int(match.group(1))
            for offset, (path, metadata, candidate_id, discovered_at) in enumerate(new_items):
                enriched = dict(metadata)
                enriched.update({
                    "_candidate_id": candidate_id,
                    "_candidate_row": first_row + offset,
                    "_candidate_attempts": 0,
                    "discovered_at": discovered_at,
                })
                ready.append((path, enriched))

        print(f"[candidates] {len(new_rows)} nuevo(s), {len(ready)} listo(s) para procesar")
        return ready

    def load_retries(self) -> list[tuple[Path, dict]]:
        ready = []
        for candidate in self.load_all():
            if candidate["status"] not in RETRY_STATES or candidate["attempts"] >= MAX_ATTEMPTS:
                continue
            metadata = _candidate_metadata(candidate)
            try:
                path = self._download_retry(candidate)
                ready.append((path, metadata))
            except Exception as error:
                self.update(
                    metadata,
                    status="reintentar",
                    attempts=candidate["attempts"] + 1,
                    reason="descarga_fallida",
                    last_error=str(error)[:500],
                )
        if ready:
            print(f"[candidates] {len(ready)} candidato(s) recuperado(s) para reintentar")
        return ready

    def _download_retry(self, candidate: dict) -> Path:
        url = candidate["thumbnail"]
        if not url:
            raise RuntimeError("candidato sin URL de imagen")
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        valid, extension = is_valid_image(response.content)
        if not valid or not passes_quality_filter(response.content):
            raise RuntimeError("la imagen ya no es válida o legible")
        IMAGES_DIR.mkdir(exist_ok=True)
        path = IMAGES_DIR / f"retry_{candidate['id']}.{extension}"
        path.write_bytes(response.content)
        return path

    def update(
        self,
        metadata: dict,
        *,
        status: str,
        attempts: int | None = None,
        confidence: str = "",
        reason: str = "",
        last_error: str = "",
        event: dict | None = None,
        event_id: str = "",
    ):
        row = metadata.get("_candidate_row")
        if not row:
            return
        event = event or {}
        attempts = metadata.get("_candidate_attempts", 0) if attempts is None else attempts
        values = [[
            status,
            attempts,
            confidence or event.get("confianza") or "",
            reason,
            last_error,
            event.get("nombre") or "",
            event.get("fecha_inicio_iso") or "",
            event.get("provincia") or "",
            event_id or event.get("id") or "",
        ]]
        self.service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!H{row}:P{row}",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
