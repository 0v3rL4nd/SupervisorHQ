import operator
from typing import TypedDict, Dict, Any, Optional, Annotated


class PraticaUfficioState(TypedDict):
    # --- 1. DATI IN INGRESSO ---
    email_in_ingresso: str  # L'email ricevuta dal cliente
    mittente: str  # Indirizzo email del cliente

    # --- 2. DELEGA DEL SUPERVISORE ---
    prossimo_reparto: str  # "AMMINISTRAZIONE", "COMMERCIALE", "ASSISTENZA", "SEGRETERIA_RISPONDE"
    motivo_assegnazione: str  # Spiegazione del task per il collega (es. "Fai preventivo per 10 PC")
    dati_estratti: Dict[str, Any]  # Dati strutturati (es. {"quantita": 10, "data_scadenza": "2026-12-01"})

    # --- 3. LAVORAZIONE DEL REPARTO ---
    esito_reparto: Optional[str]  # Il report del collega al termine del suo lavoro
    status_pratica: str  # "DA_SMISTARE", "IN_LAVORAZIONE", "COMPLETATA", "ERRORE"

    # --- 4. OUTPUT FINALE ---
    risposta_coordinata: Optional[str]  # L'email finale creata dalla Segreteria per il cliente

    #Annotated + operator.add impedisce la sovrascrittura, accumulando i messaggi.
    storico_conversazione: Annotated[list[str], operator.add]

    #Flag per inibire le email doppie
    invia_email_finale: bool

    dati_acquisto: dict