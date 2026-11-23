import sqlite3
from datetime import datetime
from pathlib import Path

DB_FATTURE_PATH = Path(__file__).resolve().parents[2] / "fatture.db"

DATI_AZIENDALI = {
    "ragione_sociale": "SupervisorHQ S.r.l.",
    "partita_iva": "IT12345678901",
    "codice_sdi": "M5UXCR1",
    "banca": "Intesa Sanpaolo",
    "iban": "IT60X0542811101000000123456",
}


def _connetti_db():
    conn = sqlite3.connect(DB_FATTURE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ottieni_dati_bonifico(numero_fattura: str | None = None) -> str:
    """Restituisce le coordinate bancarie e fiscali ufficiali dell'azienda."""
    causale = f"Saldo fattura {numero_fattura}" if numero_fattura else "Saldo fattura [indicare numero fattura]"
    return (
        f"Intestatario: {DATI_AZIENDALI['ragione_sociale']}\n"
        f"P.IVA: {DATI_AZIENDALI['partita_iva']} | Codice SDI: {DATI_AZIENDALI['codice_sdi']}\n"
        f"Banca: {DATI_AZIENDALI['banca']}\n"
        f"IBAN: {DATI_AZIENDALI['iban']}\n"
        f"Causale consigliata: {causale}"
    )


def cerca_fattura(numero_fattura: str) -> dict | None:
    """Cerca una singola fattura per numero documento (case-insensitive)."""
    conn = _connetti_db()
    try:
        row = conn.execute(
            "SELECT numero_fattura, importo, stato FROM fatture WHERE LOWER(numero_fattura) = LOWER(?)",
            (numero_fattura.strip(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def lista_fatture_per_stato(stato: str | None = None) -> list[dict]:
    """Restituisce tutte le fatture o solo quelle con un determinato stato (PAGATA / DA_PAGARE)."""
    conn = _connetti_db()
    try:
        if stato:
            rows = conn.execute(
                "SELECT numero_fattura, importo, stato FROM fatture WHERE UPPER(stato) = UPPER(?) ORDER BY numero_fattura DESC",
                (stato.strip(),)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT numero_fattura, importo, stato FROM fatture ORDER BY numero_fattura DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def emetti_nuova_fattura(importo: float) -> dict:
    """Emette una nuova fattura con numerazione progressiva F-ANNO/NNN in stato DA_PAGARE."""
    importo = round(float(importo), 2)
    if importo <= 0:
        raise ValueError("L'importo della fattura deve essere maggiore di zero.")

    anno = datetime.now().year
    conn = _connetti_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM fatture").fetchone()[0]
        numero = f"F-{anno}/{count + 1:03d}"
        conn.execute(
            "INSERT INTO fatture (numero_fattura, importo, stato) VALUES (?, ?, ?)",
            (numero, importo, "DA_PAGARE")
        )
        conn.commit()
        return {"numero_fattura": numero, "importo": importo, "stato": "DA_PAGARE"}
    finally:
        conn.close()


def registra_pagamento_fattura(numero_fattura: str, importo_pagato: float) -> str:
    """Verifica l'importo e registra il saldo della fattura su SQLite."""
    fattura = cerca_fattura(numero_fattura)
    if not fattura:
        return f"NON_TROVATA: Nessuna fattura trovata con numero '{numero_fattura}'."

    if (fattura["stato"] or "").upper() == "PAGATA":
        return f"GIA_PAGATA: La fattura {fattura['numero_fattura']} risulta già saldata."

    importo_atteso = round(float(fattura["importo"]), 2)
    importo_versato = round(float(importo_pagato), 2)

    if importo_versato < importo_atteso:
        differenza = round(importo_atteso - importo_versato, 2)
        return (
            f"IMPORTO_INSUFFICIENTE: La fattura {fattura['numero_fattura']} ha un importo di € {importo_atteso:.2f}, "
            f"ma risultano versati € {importo_versato:.2f} (mancano € {differenza:.2f})."
        )

    conn = _connetti_db()
    try:
        conn.execute(
            "UPDATE fatture SET stato = 'PAGATA' WHERE LOWER(numero_fattura) = LOWER(?)",
            (fattura["numero_fattura"],)
        )
        conn.commit()
        return f"SALDATA: Pagamento di € {importo_versato:.2f} registrato. La fattura {fattura['numero_fattura']} è ora PAGATA."
    finally:
        conn.close()

# ==========================================
# COMPATIBILITÀ PER server.py (DASHBOARD)
# ==========================================
def ottieni_tutte_le_fatture() -> list[dict]:
    """Alias usato da server.py per la dashboard e la chat interna."""
    return lista_fatture_per_stato(None)


def crea_nuova_fattura(importo: float) -> str:
    """Wrapper usato da server.py: restituisce solo il numero fattura."""
    nuova = emetti_nuova_fattura(importo)
    return nuova["numero_fattura"]


def gestisci_pagamento(numero_fattura: str, importo_pagato: str | float) -> str:
    """Wrapper usato da server.py: converte l'importo da stringa (es. '500,00') a float."""
    valore_pulito = str(importo_pagato).replace("€", "").replace(" ", "").replace(",", ".")
    return registra_pagamento_fattura(numero_fattura, float(valore_pulito))

def aggiorna_fattura(numero_fattura: str, importo: float | None = None, stato: str | None = None) -> bool:
    """Aggiorna importo e/o stato (PAGATA / DA_PAGARE) di una fattura esistente."""
    campi = []
    valori = []

    if importo is not None:
        importo = round(float(importo), 2)
        if importo <= 0:
            raise ValueError("L'importo deve essere maggiore di zero.")
        campi.append("importo = ?")
        valori.append(importo)

    if stato is not None:
        stato_norm = stato.strip().upper()
        if stato_norm not in {"PAGATA", "DA_PAGARE"}:
            raise ValueError("Stato non valido. Usa 'PAGATA' o 'DA_PAGARE'.")
        campi.append("stato = ?")
        valori.append(stato_norm)

    if not campi:
        return False

    valori.append(numero_fattura.strip())
    conn = _connetti_db()
    try:
        cur = conn.execute(
            f"UPDATE fatture SET {', '.join(campi)} WHERE LOWER(numero_fattura) = LOWER(?)",
            valori
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def elimina_fattura(numero_fattura: str) -> bool:
    """Elimina una fattura da SQLite."""
    conn = _connetti_db()
    try:
        cur = conn.execute(
            "DELETE FROM fatture WHERE LOWER(numero_fattura) = LOWER(?)",
            (numero_fattura.strip(),)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()