import sqlite3
import os
import re
import random
from datetime import datetime

# Definiamo la posizione del DB nella cartella principale del progetto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, 'fatture.db')


def setup_database():
    """Crea il DB e popola alcune fatture di test se non esiste."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS fatture
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       numero_fattura
                       TEXT
                       UNIQUE,
                       importo
                       REAL,
                       stato
                       TEXT
                   )
                   ''')

    # Inseriamo i dati che Qwen si aspetta di trovare nel nostro test
    cursor.execute(
        "INSERT OR IGNORE INTO fatture (numero_fattura, importo, stato) VALUES ('F-2026/04', 2450.00, 'DA_PAGARE')")
    cursor.execute(
        "INSERT OR IGNORE INTO fatture (numero_fattura, importo, stato) VALUES ('F-2026/05', 1000.00, 'DA_PAGARE')")

    conn.commit()
    conn.close()


def gestisci_pagamento(numero_fattura: str, importo_pagato_str: str) -> str:
    """Interroga SQLite per verificare e saldare la fattura."""
    setup_database()

    # Pulizia dell'importo (es. trasforma "2450€" o "2.450,00" nel float 2450.0)
    numeri_trovati = re.findall(r'\d+(?:\.\d+)?', importo_pagato_str.replace(',', '.'))
    importo_pagato = float(numeri_trovati[0]) if numeri_trovati else 0.0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT importo, stato FROM fatture WHERE numero_fattura = ?", (numero_fattura,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return f"ERRORE SISTEMA: La fattura {numero_fattura} non esiste nei registri contabili."

    importo_atteso, stato = row

    if stato == 'PAGATA':
        conn.close()
        return f"AVVISO: La fattura {numero_fattura} risulta già pagata in precedenza."

    # Se il cliente ha pagato abbastanza, aggiorniamo il DB
    if importo_pagato >= importo_atteso:
        cursor.execute("UPDATE fatture SET stato = 'PAGATA' WHERE numero_fattura = ?", (numero_fattura,))
        conn.commit()
        conn.close()
        return f"SUCCESSO: Fattura {numero_fattura} saldata correttamente. Registro aggiornato."
    else:
        conn.close()
        return f"ERRORE IMPORTI: Importo insufficiente. Atteso: {importo_atteso}€, Ricevuto: {importo_pagato}€"


def ottieni_tutte_le_fatture() -> list[dict]:
    """Recupera l'intero registro contabile dal database SQLite."""
    setup_database()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT numero_fattura, importo, stato FROM fatture")
    righe = cursor.fetchall()
    conn.close()

    return [dict(riga) for riga in righe]


def crea_nuova_fattura(importo_totale: float) -> str:
    """Registra un nuovo acquisto generando una fattura DA_PAGARE."""
    setup_database()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Generiamo un numero fattura realistico formattato come i tuoi mock
    anno = datetime.now().year
    id_seriale = random.randint(1000, 9999)
    numero_fattura = f"F-{anno}/{id_seriale}"

    cursor.execute('''
                   INSERT INTO fatture (numero_fattura, importo, stato)
                   VALUES (?, ?, 'DA_PAGARE')
                   ''', (numero_fattura, importo_totale))

    conn.commit()
    conn.close()

    return numero_fattura