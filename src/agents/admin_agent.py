import json
import ollama
from pydantic import ValidationError

from src.core.state import PraticaUfficioState
from src.core.schema import EsitoReparto
from src.tools.billing_tools import gestisci_pagamento

MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}


def nodo_amministrazione(state: PraticaUfficioState) -> PraticaUfficioState:
    print("\n💶 [REPARTO AMMINISTRAZIONE] Accesso al database contabile SQLite...")

    dati = state.get("dati_estratti", {})
    # Controllo flessibile in caso l'LLM usi "fattura" o "numero_fattura"
    numero_fattura = dati.get("fattura", dati.get("numero_fattura", ""))
    importo_pagato = str(dati.get("importo_pagato", "0"))

    # 1. Esecuzione Fisica SQL o Risposta Generica
    if numero_fattura:
        esito_db = gestisci_pagamento(numero_fattura, importo_pagato)
    else:
        # 🔴 CORREZIONE: Invece di un ERRORE, diamo all'impiegato le informazioni aziendali da riferire
        esito_db = (
            "INFO GENERICA: Il cliente non ha fornito un numero di fattura, quindi desidera "
            "solo informazioni sui pagamenti. Informalo che accettiamo: Bonifico Bancario "
            "(IT00000000000000000), Carta di Credito (tramite Stripe) e PayPal."
        )

    print(f"   -> DB/Sistema Risponde: {esito_db}")

    # 2. Resoconto via LLM
    schema_richiesto = EsitoReparto.model_json_schema()

    prompt = (
        "Sei l'Impiegato Contabile dell'azienda. Il Direttore ti ha assegnato una pratica.\n\n"
        f"MOTIVO ASSEGNAZIONE: {state.get('motivo_assegnazione', 'Nessun motivo')}\n"
        f"ESITO DEL SISTEMA/DATABASE: {esito_db}\n\n"
        "COMPITO: Redigi il resoconto dell'operazione basandoti ESCLUSIVAMENTE sull'esito del sistema appena fornito. "
        "Se l'esito fornisce informazioni generiche (es. metodi di pagamento), usale per creare il resoconto senza segnalare errori.\n"
        "Se c'è stato un vero 'ERRORE' nel database SQLite (es. fattura non trovata), usa lo status_pratica ERRORE.\n"
        "Devi rispondere ESCLUSIVAMENTE con un oggetto JSON valido che rispetti questo schema:\n"
        f"{json.dumps(schema_richiesto, indent=2)}"
    )

    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        format='json',
        options=OPZIONI_LLM
    )

    try:
        esito_validato = EsitoReparto.model_validate_json(risp['message']['content'].strip())
        print(f"   -> Status: {esito_validato.status_pratica}")

        return {
            "esito_reparto": esito_validato.dettaglio_esito,
            "status_pratica": esito_validato.status_pratica,
            "invia_email_finale": True
        }

    except ValidationError as e:
        return {
            "esito_reparto": "Errore interno nella generazione del report contabile.",
            "status_pratica": "ERRORE",
            "invia_email_finale": True
        }