import json
import ollama
from pydantic import BaseModel, Field, ValidationError
from typing import Literal

from src.core.state import PraticaUfficioState
from src.tools.rag_tools import cerca_soluzione

MODELLO_LLM = "qwen2.5:14b"


class EsitoAssistenza(BaseModel):
    dettaglio_esito: str = Field(description="La risposta tecnica da inviare al cliente, basata SOLO sul manuale.")
    status_pratica: Literal["COMPLETATA", "ERRORE"]


def nodo_assistenza(state: PraticaUfficioState) -> PraticaUfficioState:
    print("\n🛠️ [REPARTO ASSISTENZA] Ricerca soluzione nel database vettoriale...")

    problema_cliente = state.get("motivo_assegnazione", state.get("email_in_ingresso", ""))

    # 1. Ricerca Semantica in ChromaDB
    contesto_tecnico = cerca_soluzione(problema_cliente)
    print("   -> 🔎 Trovati estratti rilevanti nei manuali aziendali.")

    # 2. Generazione della risposta vincolata (RAG)
    schema_richiesto = EsitoAssistenza.model_json_schema()

    prompt = (
        "Sei un Tecnico del Supporto di SupervisorHQ. Devi rispondere al problema del cliente.\n\n"
        f"PROBLEMA DEL CLIENTE: {problema_cliente}\n\n"
        f"ESTRATTO DEI MANUALI TECNICI (La tua unica fonte di verità):\n{contesto_tecnico}\n\n"
        "REGOLE RIGOROSE:\n"
        "1. Usa ESCLUSIVAMENTE le informazioni presenti nell'estratto dei manuali.\n"
        "2. Se l'estratto non contiene la soluzione, non inventarla. Scrivi che la problematica richiede l'intervento di un tecnico di 2° livello.\n"
        "3. Sii professionale, empatico e chiaro nelle istruzioni.\n\n"
        "Devi rispondere ESCLUSIVAMENTE con un oggetto JSON valido che rispetti questo schema:\n"
        f"{json.dumps(schema_richiesto, indent=2)}"
    )

    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        format='json',
        options={"num_ctx": 8192, "temperature": 0.1}
    )

    try:
        esito = EsitoAssistenza.model_validate_json(risp['message']['content'].strip())
        print(f"   -> Status: {esito.status_pratica}")

        return {
            "esito_reparto": esito.dettaglio_esito,
            "status_pratica": esito.status_pratica,
            "invia_email_finale": True
        }
    except ValidationError as e:
        return {
            "esito_reparto": "Errore nella formulazione della risposta tecnica.",
            "status_pratica": "ERRORE",
            "invia_email_finale": True
        }