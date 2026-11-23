import re
import secrets
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "supervisorhq.db"
ALIQUOTA_IVA = 0.22


def ottieni_catalogo_soluzioni() -> list[dict]:
    """Legge tutte le soluzioni attive dalla tabella 'soluzioni' di supervisorhq.db."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, titolo, descrizione, prezzo FROM soluzioni ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _estrai_prezzo_numerico(prezzo_str: str) -> float | None:
    """Estrae il valore numerico da stringhe come '€ 299 / mese' o '€ 1.200,00'."""
    if not prezzo_str:
        return None
    match = re.search(r"(\d[\d\.,]*)", prezzo_str)
    if not match:
        return None
    valore = match.group(1)
    # Gestisce formato italiano (es. 1.200,50 -> 1200.50)
    if "," in valore and "." in valore:
        valore = valore.replace(".", "").replace(",", ".")
    elif "," in valore:
        valore = valore.replace(",", ".")
    try:
        return float(valore)
    except ValueError:
        return None


def cerca_soluzione(nome_richiesto: str) -> dict | None:
    """Cerca una soluzione nel catalogo per corrispondenza (case-insensitive)."""
    catalogo = ottieni_catalogo_soluzioni()
    target = (nome_richiesto or "").strip().lower()
    for sol in catalogo:
        if target in sol["titolo"].lower() or sol["titolo"].lower() in target:
            return sol
    return None


def calcola_preventivo(nome_soluzione: str, quantita: int = 1) -> dict:
    """Calcola in modo deterministico imponibile, sconto volume, IVA 22% e totale."""
    sol = cerca_soluzione(nome_soluzione)
    if not sol:
        return {"trovata": False, "errore": f"Soluzione '{nome_soluzione}' non presente a catalogo."}

    prezzo_unitario = _estrai_prezzo_numerico(sol["prezzo"])
    if prezzo_unitario is None:
        return {
            "trovata": True,
            "su_misura": True,
            "soluzione": sol["titolo"],
            "etichetta_prezzo": sol["prezzo"],
            "messaggio": f"La soluzione '{sol['titolo']}' ({sol['prezzo']}) richiede una quotazione personalizzata con un consulente."
        }

    quantita = max(1, int(quantita))
    subtotale = prezzo_unitario * quantita

    # Politica sconti aziendale
    if quantita >= 10:
        sconto_perc = 0.15
    elif quantita >= 5:
        sconto_perc = 0.10
    else:
        sconto_perc = 0.0

    importo_sconto = round(subtotale * sconto_perc, 2)
    imponibile = round(subtotale - importo_sconto, 2)
    iva = round(imponibile * ALIQUOTA_IVA, 2)
    totale = round(imponibile + iva, 2)

    return {
        "trovata": True,
        "su_misura": False,
        "soluzione": sol["titolo"],
        "quantita": quantita,
        "prezzo_unitario": prezzo_unitario,
        "sconto_perc": int(sconto_perc * 100),
        "importo_sconto": importo_sconto,
        "imponibile": imponibile,
        "iva": iva,
        "totale": totale
    }


def genera_codici_licenza(quantita: int) -> list[str]:
    """Genera codici di attivazione univoci per l'ordine confermato."""
    codici = []
    for _ in range(max(1, int(quantita))):
        blocco1 = secrets.token_hex(2).upper()
        blocco2 = secrets.token_hex(2).upper()
        codici.append(f"SHQ-2026-{blocco1}-{blocco2}")
    return codici