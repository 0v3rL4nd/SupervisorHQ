import hashlib
import hmac
import json
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
    """Crea le tabelle dipendenti, soluzioni ed email_elaborate e applica le migrazioni multi-utente."""
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
                reparto TEXT NOT NULL,
                email_aziendale TEXT,
                google_token_path TEXT,
                google_collegato INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Migrazione sicura per DB già esistenti
        colonne_esistenti = {
            row[1] for row in cursor.execute("PRAGMA table_info(dipendenti)").fetchall()
        }
        if "email_aziendale" not in colonne_esistenti:
            cursor.execute("ALTER TABLE dipendenti ADD COLUMN email_aziendale TEXT")
        if "google_token_path" not in colonne_esistenti:
            cursor.execute("ALTER TABLE dipendenti ADD COLUMN google_token_path TEXT")
        if "google_collegato" not in colonne_esistenti:
            cursor.execute("ALTER TABLE dipendenti ADD COLUMN google_collegato INTEGER NOT NULL DEFAULT 0")

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

        # Schema 3: Email elaborate per singolo dipendente (isolamento multi-utente)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_elaborate (
                username TEXT NOT NULL,
                msg_id TEXT NOT NULL,
                stato_ai TEXT NOT NULL,
                reparto_ai TEXT,
                risposta_ai TEXT,
                data_elaborazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (username, msg_id)
            )
        """)

        # Schema 4: Verbali di Riunione
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS verbali (
                           id INTEGER PRIMARY KEY
                           AUTOINCREMENT, username_creatore TEXT NOT NULL,
                           titolo TEXT NOT NULL,
                           fonte TEXT NOT NULL DEFAULT
                           'TESTO', testo_originale TEXT NOT NULL,
                           riepilogo TEXT, data_creazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

        # Schema 5: Azioni estratte dai Verbali (Human-in-the-Loop)
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS verbali_azioni (
                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                           verbale_id INTEGER NOT NULL,
                           tipo TEXT NOT NULL,
                           descrizione TEXT NOT NULL,
                           payload_json TEXT NOT NULL,
                           stato TEXT NOT NULL DEFAULT 'DA_CONFERMARE',
                           esito TEXT,
                           data_creazione TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                           FOREIGN KEY (
                            verbale_id
                        ) REFERENCES verbali (
                           id
                       ) ON DELETE CASCADE
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
# QUERY DIPENDENTI (AUTH & MULTI-UTENTE GOOGLE)
# ==========================================
def autentica_dipendente(username: str, password: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM dipendenti WHERE username = ?", (username,)
        ).fetchone()
        if row and verifica_password(password, row["password_hash"]):
            return dict(row)
        return None


def ottieni_dipendente(username: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, username, nome_completo, ruolo, reparto,
                   email_aziendale, google_token_path, google_collegato
            FROM dipendenti
            WHERE username = ?
            """,
            (username,)
        ).fetchone()
        return dict(row) if row else None


def lista_dipendenti() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, username, nome_completo, ruolo, reparto,
                   email_aziendale, google_collegato
            FROM dipendenti
            ORDER BY nome_completo ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def aggiorna_google_dipendente(username: str, token_path: str, email_google: Optional[str] = None) -> bool:
    with get_connection() as conn:
        if email_google:
            cursor = conn.execute(
                """
                UPDATE dipendenti
                SET google_token_path = ?, google_collegato = 1, email_aziendale = ?
                WHERE username = ?
                """,
                (token_path, email_google, username)
            )
        else:
            cursor = conn.execute(
                """
                UPDATE dipendenti
                SET google_token_path = ?, google_collegato = 1
                WHERE username = ?
                """,
                (token_path, username)
            )
        conn.commit()
        return cursor.rowcount > 0


# ==========================================
# STATO EMAIL ELABORATE (PER UTENTE)
# ==========================================
def ottieni_email_elaborata(username: str, msg_id: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT stato_ai, reparto_ai, risposta_ai
            FROM email_elaborate
            WHERE username = ? AND msg_id = ?
            """,
            (username, msg_id)
        ).fetchone()
        return dict(row) if row else None


def salva_email_elaborata(username: str, msg_id: str, stato_ai: str, reparto_ai: str, risposta_ai: str):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO email_elaborate (username, msg_id, stato_ai, reparto_ai, risposta_ai)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username, msg_id) DO UPDATE SET
                stato_ai = excluded.stato_ai,
                reparto_ai = excluded.reparto_ai,
                risposta_ai = excluded.risposta_ai,
                data_elaborazione = CURRENT_TIMESTAMP
            """,
            (username, msg_id, stato_ai, reparto_ai, risposta_ai)
        )
        conn.commit()


def elimina_email_elaborata(username: str, msg_id: str):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM email_elaborate WHERE username = ? AND msg_id = ?",
            (username, msg_id)
        )
        conn.commit()


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

# ==========================================
# CRUD VERBALI DI RIUNIONE & AZIONI
# ==========================================
def salva_verbale_con_azioni(
    username: str,
    titolo: str,
    fonte: str,
    testo_originale: str,
    riepilogo: str,
    azioni: list[dict],
) -> int:
    """Salva un verbale e tutte le azioni estratte in stato DA_CONFERMARE."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO verbali (username_creatore, titolo, fonte, testo_originale, riepilogo)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, titolo, fonte, testo_originale, riepilogo),
        )
        verbale_id = cur.lastrowid

        for az in azioni:
            conn.execute(
                """
                INSERT INTO verbali_azioni (verbale_id, tipo, descrizione, payload_json, stato)
                VALUES (?, ?, ?, ?, 'DA_CONFERMARE')
                """,
                (
                    verbale_id,
                    az["tipo"],
                    az["descrizione"],
                    json.dumps(az.get("payload", {}), ensure_ascii=False),
                ),
            )
        conn.commit()
        return verbale_id


def lista_verbali() -> list[dict]:
    """Restituisce tutti i verbali con le relative azioni annidate."""
    with get_connection() as conn:
        verbali_rows = conn.execute(
            "SELECT * FROM verbali ORDER BY data_creazione DESC"
        ).fetchall()
        risultato = []
        for v in verbali_rows:
            v_dict = dict(v)
            azioni_rows = conn.execute(
                "SELECT * FROM verbali_azioni WHERE verbale_id = ? ORDER BY id ASC",
                (v_dict["id"],),
            ).fetchall()
            v_dict["azioni"] = [
                {**dict(a), "payload": json.loads(a["payload_json"])}
                for a in azioni_rows
            ]
            risultato.append(v_dict)
        return risultato


def ottieni_azione_verbale(azione_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM verbali_azioni WHERE id = ?", (azione_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload_json"])
        return d


def aggiorna_stato_azione_verbale(azione_id: int, stato: str, esito: str = "") -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE verbali_azioni SET stato = ?, esito = ? WHERE id = ?",
            (stato.upper(), esito, azione_id),
        )
        conn.commit()
        return cur.rowcount > 0