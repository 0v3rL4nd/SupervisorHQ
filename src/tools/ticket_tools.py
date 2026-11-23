import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "supervisorhq.db"


def _connetti_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inizializza_tabella_ticket():
    """Crea la tabella ticket in supervisorhq.db se non esiste già."""
    conn = _connetti_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codice_ticket TEXT UNIQUE NOT NULL,
                email_cliente TEXT NOT NULL,
                problema TEXT NOT NULL,
                priorita TEXT NOT NULL DEFAULT 'MEDIA',
                stato TEXT NOT NULL DEFAULT 'APERTO',
                data_creazione TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def apri_ticket(email_cliente: str, problema: str, priorita: str = "MEDIA") -> dict:
    """Crea un nuovo ticket di assistenza con codice progressivo TK-ANNO-NNN."""
    inizializza_tabella_ticket()
    anno = datetime.now().year
    data_ora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    priorita_norm = priorita.upper() if priorita.upper() in ("BASSA", "MEDIA", "ALTA", "CRITICA") else "MEDIA"

    conn = _connetti_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM ticket").fetchone()[0]
        codice = f"TK-{anno}-{count + 1:03d}"
        conn.execute(
            """
            INSERT INTO ticket (codice_ticket, email_cliente, problema, priorita, stato, data_creazione)
            VALUES (?, ?, ?, ?, 'APERTO', ?)
            """,
            (codice, email_cliente, problema.strip(), priorita_norm, data_ora)
        )
        conn.commit()
        return {
            "codice_ticket": codice,
            "priorita": priorita_norm,
            "stato": "APERTO",
            "data_creazione": data_ora
        }
    finally:
        conn.close()


def cerca_ticket(codice_ticket: str) -> dict | None:
    """Cerca un ticket per codice (es. TK-2026-001)."""
    inizializza_tabella_ticket()
    conn = _connetti_db()
    try:
        row = conn.execute(
            "SELECT codice_ticket, email_cliente, problema, priorita, stato, data_creazione "
            "FROM ticket WHERE UPPER(codice_ticket) = UPPER(?)",
            (codice_ticket.strip(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def lista_ticket_cliente(email_cliente: str) -> list[dict]:
    """Restituisce tutti i ticket associati a una specifica email cliente."""
    inizializza_tabella_ticket()
    conn = _connetti_db()
    try:
        rows = conn.execute(
            "SELECT codice_ticket, problema, priorita, stato, data_creazione "
            "FROM ticket WHERE LOWER(email_cliente) = LOWER(?) ORDER BY id DESC",
            (email_cliente.strip(),)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def lista_tutti_ticket() -> list[dict]:
    """Restituisce tutti i ticket presenti nel database, dal più recente al più vecchio."""
    inizializza_tabella_ticket()
    conn = _connetti_db()
    try:
        rows = conn.execute(
            "SELECT codice_ticket, email_cliente, problema, priorita, stato, data_creazione "
            "FROM ticket ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def aggiorna_stato_ticket(codice_ticket: str, nuovo_stato: str) -> bool:
    """Aggiorna lo stato di un ticket (APERTO, IN_LAVORAZIONE, CHIUSO)."""
    inizializza_tabella_ticket()
    stati_validi = ("APERTO", "IN_LAVORAZIONE", "CHIUSO")
    stato_norm = nuovo_stato.strip().upper()
    if stato_norm not in stati_validi:
        raise ValueError(f"Stato non valido. Usa uno tra: {', '.join(stati_validi)}")

    conn = _connetti_db()
    try:
        cur = conn.execute(
            "UPDATE ticket SET stato = ? WHERE UPPER(codice_ticket) = UPPER(?)",
            (stato_norm, codice_ticket.strip())
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def aggiorna_ticket(
    codice_ticket: str,
    problema: str | None = None,
    priorita: str | None = None,
    stato: str | None = None
) -> bool:
    """Aggiorna uno o più campi di un ticket esistente."""
    campi = []
    valori = []

    if problema is not None and problema.strip():
        campi.append("problema = ?")
        valori.append(problema.strip())

    if priorita is not None:
        prio_norm = priorita.strip().upper()
        if prio_norm not in {"BASSA", "MEDIA", "ALTA", "CRITICA"}:
            raise ValueError("Priorità non valida. Usa BASSA, MEDIA, ALTA o CRITICA.")
        campi.append("priorita = ?")
        valori.append(prio_norm)

    if stato is not None:
        stato_norm = stato.strip().upper()
        if stato_norm not in {"APERTO", "IN_LAVORAZIONE", "CHIUSO"}:
            raise ValueError("Stato non valido. Usa APERTO, IN_LAVORAZIONE o CHIUSO.")
        campi.append("stato = ?")
        valori.append(stato_norm)

    if not campi:
        return False

    valori.append(codice_ticket.strip())
    conn = _connetti_db()
    try:
        cur = conn.execute(
            f"UPDATE ticket SET {', '.join(campi)} WHERE LOWER(codice_ticket) = LOWER(?)",
            valori
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def elimina_ticket(codice_ticket: str) -> bool:
    """Elimina un ticket da SQLite."""
    conn = _connetti_db()
    try:
        cur = conn.execute(
            "DELETE FROM ticket WHERE LOWER(codice_ticket) = LOWER(?)",
            (codice_ticket.strip(),)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()