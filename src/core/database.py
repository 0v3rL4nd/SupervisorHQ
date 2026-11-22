import hashlib
import hmac
import os
import sqlite3
from typing import Optional

DB_PATH = os.getenv("SUPERVISOR_DB_PATH", "supervisorhq.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Genera un hash PBKDF2-HMAC-SHA256 con salt casuale."""
    if salt is None:
        salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${dk.hex()}"


def verifica_password(password: str, password_hash: str) -> bool:
    """Verifica la password in modo resistente a timing attack."""
    try:
        salt, _ = password_hash.split("$")
        return hmac.compare_digest(hash_password(password, salt), password_hash)
    except ValueError:
        return False


def inizializza_database():
    """Crea le tabelle dipendenti e soluzioni e popola i dati iniziali se vuote."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Schema 1: Dipendenti
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dipendenti (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                nome_completo TEXT NOT NULL,
                ruolo TEXT NOT NULL DEFAULT 'ROLE_ADMIN',
                reparto TEXT NOT NULL
            )
        """)

        # Schema 2: Soluzioni Aziendali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS soluzioni (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titolo TEXT NOT NULL,
                descrizione TEXT NOT NULL,
                prezzo TEXT NOT NULL,
                icona TEXT NOT NULL DEFAULT '🚀',
                prompt_precompilato TEXT NOT NULL
            )
        """)

        # Seed Dipendenti (solo se la tabella è vuota)
        cursor.execute("SELECT COUNT(*) FROM dipendenti")
        if cursor.fetchone()[0] == 0:
            dipendenti_iniziali = [
                ("admin", hash_password("Supervisor2026!"), "Amministratore Sistema", "ROLE_ADMIN", "Direzione"),
                ("mario.rossi", hash_password("Commerciale2026!"), "Mario Rossi", "ROLE_ADMIN", "Commerciale"),
                ("giulia.bianchi", hash_password("Supporto2026!"), "Giulia Bianchi", "ROLE_ADMIN", "Assistenza Tecnica"),
            ]
            cursor.executemany(
                "INSERT INTO dipendenti (username, password_hash, nome_completo, ruolo, reparto) VALUES (?, ?, ?, ?, ?)",
                dipendenti_iniziali
            )

        # Seed Soluzioni (solo se la tabella è vuota)
        cursor.execute("SELECT COUNT(*) FROM soluzioni")
        if cursor.fetchone()[0] == 0:
            soluzioni_iniziali = [
                (
                    "Licenze Enterprise Suite",
                    "Accesso completo alla piattaforma aziendale con attivazione immediata, fatturazione automatica e invio Product Key via PDF.",
                    "Preventivi su misura",
                    "🚀",
                    "Vorrei un preventivo per l'acquisto di 3 licenze Enterprise Suite."
                ),
                (
                    "Assistenza Tecnica RAG",
                    "Risoluzione rapida di errori, configurazioni e procedure consultando direttamente i manuali tecnici ufficiali.",
                    "Inclusa nel piano",
                    "🛠️",
                    "Ho un problema tecnico durante la configurazione del software, potete aiutarmi?"
                ),
                (
                    "Demo & Consulenza Live",
                    "Prenota una call con i nostri specialisti direttamente su Google Calendar con invito Meet automatico.",
                    "Prima call gratuita",
                    "📅",
                    "Vorrei fissare una riunione dimostrativa giovedì prossimo alle 15:00."
                ),
            ]
            cursor.executemany(
                "INSERT INTO soluzioni (titolo, descrizione, prezzo, icona, prompt_precompilato) VALUES (?, ?, ?, ?, ?)",
                soluzioni_iniziali
            )

        conn.commit()


# ==========================================
# QUERY DIPENDENTI (AUTH)
# ==========================================
def autentica_dipendente(username: str, password: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM dipendenti WHERE username = ?", (username,)
        ).fetchone()
        if row and verifica_password(password, row["password_hash"]):
            return dict(row)
        return None


# ==========================================
# CRUD SOLUZIONI AZIENDALI
# ==========================================
def ottieni_tutte_le_soluzioni() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM soluzioni ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


def crea_soluzione(titolo: str, descrizione: str, prezzo: str, icona: str, prompt_precompilato: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO soluzioni (titolo, descrizione, prezzo, icona, prompt_precompilato)
            VALUES (?, ?, ?, ?, ?)
            """,
            (titolo, descrizione, prezzo, icona, prompt_precompilato)
        )
        conn.commit()
        return cursor.lastrowid


def aggiorna_soluzione(soluzione_id: int, titolo: str, descrizione: str, prezzo: str, icona: str, prompt_precompilato: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE soluzioni
            SET titolo = ?, descrizione = ?, prezzo = ?, icona = ?, prompt_precompilato = ?
            WHERE id = ?
            """,
            (titolo, descrizione, prezzo, icona, prompt_precompilato, soluzione_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def elimina_soluzione(soluzione_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM soluzioni WHERE id = ?", (soluzione_id,))
        conn.commit()
        return cursor.rowcount > 0