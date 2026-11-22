import json
import ollama
import random
import string
from pydantic import BaseModel, Field, ValidationError
from typing import Literal

from src.core.state import PraticaUfficioState
from src.tools.billing_tools import crea_nuova_fattura

MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}


# --- NUOVA FUNZIONE: Generatore di Product Key ---
def genera_codici_attivazione(quantita: int) -> list[str]:
    """Genera N codici di attivazione univoci nel formato XXXX-XXXX-XXXX-XXXX."""
    codici = []
    # Limitiamo a 100 per sicurezza contro richieste malevole esagerate
    quantita_reale = min(quantita, 100)
    for _ in range(quantita_reale):
        codice = '-'.join(''.join(random.choices(string.ascii_uppercase + string.digits, k=4)) for _ in range(4))
        codici.append(codice)
    return codici


# --- NUOVO SCHEMA: Estrazione della quantità ---
class EsitoCommerciale(BaseModel):
    intenzione: Literal["PREVENTIVO", "ACQUISTO"]
    quantita_licenze: int = Field(
        description="Il numero esatto di licenze richieste. Usa 1 se non specificato altrimenti."
    )
    importo_totale: float = Field(description="Il costo totale matematico calcolato.")
    dettaglio_esito: str = Field(description="Resoconto discorsivo per il cliente.")
    status_pratica: Literal["COMPLETATA", "ERRORE"]


def nodo_commerciale(state: PraticaUfficioState) -> PraticaUfficioState:
    print("\n💼 [UFFICIO COMMERCIALE] Presa in carico della pratica...")

    schema_richiesto = EsitoCommerciale.model_json_schema()
    email_originale = state.get("email_in_ingresso", "")

    prompt = (
        "Sei il Responsabile Commerciale dell'azienda. Il Direttore ti ha assegnato un task.\n\n"
        f"EMAIL ORIGINALE DEL CLIENTE: {email_originale}\n"
        f"MOTIVO ASSEGNAZIONE: {state.get('motivo_assegnazione', 'Nessun motivo')}\n"
        f"DATI ESTRATTI: {json.dumps(state.get('dati_estratti', {}))}\n\n"
        "REGOLE DI VENDITA AZIENDALI:\n"
        "- Licenza Standard: 500€ l'una.\n"
        "- Licenza Enterprise: 1000€ l'una.\n\n"
        "COMPITO:\n"
        "1. Identifica la 'quantita_licenze' desiderata.\n"
        "2. Decidi se l'email indica un PREVENTIVO o un ACQUISTO confermato.\n"
        "3. Calcola l'importo_totale.\n"
        "4. Redigi il dettaglio_esito spiegando l'operazione.\n"
        "Devi rispondere ESCLUSIVAMENTE con un JSON valido secondo questo schema:\n"
        f"{json.dumps(schema_richiesto, indent=2)}"
    )

    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        format='json',
        options=OPZIONI_LLM
    )

    try:
        esito = EsitoCommerciale.model_validate_json(risp['message']['content'].strip())

        # Logica di Esecuzione (Il "Braccio Armato" del codice)
        # Logica di Esecuzione (Il "Braccio Armato" del codice)
        if esito.intenzione == "ACQUISTO" and esito.status_pratica == "COMPLETATA":
            print(f"   -> 🛒 ACQUISTO: Richieste {esito.quantita_licenze} licenze per €{esito.importo_totale}")

            try:
                num_fattura = crea_nuova_fattura(esito.importo_totale)
                codici = genera_codici_attivazione(esito.quantita_licenze)
                codici_formattati = "\n".join([f"   🔑 {c}" for c in codici])

                dettaglio_finale = (
                    f"{esito.dettaglio_esito}\n\n"
                    f"--- RIEPILOGO ORDINE ---\n"
                    f"📄 Fattura Generata: {num_fattura}\n"
                    f"📦 Codici di Attivazione ({esito.quantita_licenze} licenze):\n{codici_formattati}\n\n"
                    f"Informa il cliente che i codici sono allegati in formato PDF."
                )

                # 🔴 NOVITÀ: Salviamo i dati strutturati nel "fascicolo" per la Segreteria
                pacchetto_acquisto = {
                    "numero_fattura": num_fattura,
                    "importo": esito.importo_totale,
                    "codici": codici
                }

                return {
                    "esito_reparto": dettaglio_finale,
                    "status_pratica": esito.status_pratica,
                    "invia_email_finale": True,
                    "dati_acquisto": pacchetto_acquisto  # <--- Passaggio dei dati!
                }
            except Exception as e:
                return {
                    "esito_reparto": f"Errore nel sistema di provisioning: {e}",
                    "status_pratica": "ERRORE",
                    "invia_email_finale": True
                }
        else:
            print("   -> ℹ️ Rilevata semplice richiesta di PREVENTIVO.")
            dettaglio_finale = esito.dettaglio_esito

        print(f"   -> Status: {esito.status_pratica}")

        return {
            "esito_reparto": dettaglio_finale,
            "status_pratica": esito.status_pratica,
            "invia_email_finale": True
        }

    except ValidationError as e:
        print(f"   -> [⚠️ ERRORE] JSON non conforme: {e}")
        return {
            "esito_reparto": "Errore durante l'elaborazione commerciale.",
            "status_pratica": "ERRORE",
            "invia_email_finale": True
        }