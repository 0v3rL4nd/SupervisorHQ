from pydantic import BaseModel, Field
from typing import Dict, Any, Literal

class DecisioneSupervisore(BaseModel):
    ragionamento: str = Field(
        description="Spiega passo passo perché stai prendendo questa decisione."
    )
    # Aggiunto "SEGRETERIA_RISPONDE" nel Literal per permettere a Pydantic di validarlo
    prossimo_reparto: Literal["AMMINISTRAZIONE", "COMMERCIALE", "ASSISTENZA", "AGENDA", "SEGRETERIA_RISPONDE"] = Field(
        description=(
            "A quale reparto assegnare la pratica. "
            "Se è solo per fissare un appuntamento usa 'AGENDA'. "
            "Se è una richiesta di informazioni generiche usa 'SEGRETERIA_RISPONDE'."
        )
    )
    motivo_assegnazione: str = Field(
        description="Istruzioni chiare e dirette per il reparto scelto (Cosa devono fare?)."
    )
    dati_estratti: Dict[str, Any] = Field(
        description="Estrai i dati chiave in formato JSON (es. importo fattura, date richieste, articoli)."
    )

class EsitoReparto(BaseModel):
    status_pratica: Literal["COMPLETATA", "ERRORE"] = Field(
        description="Se il tool ha funzionato usa COMPLETATA, se ci sono stati imprevisti gravi usa ERRORE."
    )
    dettaglio_esito: str = Field(
        description="Resoconto di ciò che è stato fatto (es. 'Fattura salvata', oppure 'Errore di connessione al DB')."
    )

class ParametriEvento(BaseModel):
    titolo: str = Field(description="Il titolo dell'evento (es. 'Call Commerciale con Cliente')")
    data_inizio: str = Field(description="Data e ora di inizio nel formato ESATTO 'YYYY-MM-DD HH:MM'. Es: '2026-11-20 15:00'")
    ore_durata: int = Field(description="Durata prevista dell'evento in ore intere (es. 1, 2, 3)")
    descrizione: str = Field(description="Sintesi del motivo della riunione per le note di Calendar")