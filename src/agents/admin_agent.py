import json
from typing import Literal, Optional

import ollama
from pydantic import BaseModel, Field, ValidationError

from src.core.state import PraticaUfficioState
from src.tools.billing_tools import (
    ottieni_dati_bonifico,
    cerca_fattura,
    lista_fatture_per_stato,
    emetti_nuova_fattura,
    registra_pagamento_fattura,
)

MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}


class AzioneAmministrazione(BaseModel):
    azione: Literal[
        "STATO_FATTURA",
        "ELENCO_DA_PAGARE",
        "EMETTI_FATTURA",
        "REGISTRA_PAGAMENTO",
        "DATI_BONIFICO",
        "CHIARIMENTO"
    ] = Field(description="Tipo di operazione amministrativa richiesta.")
    numero_fattura: Optional[str] = Field(
        default=None,
        description="Numero esatto della fattura (es. 'F-2026/001'), se presente nell'email."
    )
    importo: Optional[float] = Field(
        default=None,
        description="Importo numerico in euro, se presente (per emissione o pagamento)."
    )
    nota_chiarimento: Optional[str] = Field(
        default=None,
        description="Se azione='CHIARIMENTO', spiega quale dato manca (es. numero fattura o importo)."
    )


def nodo_amministrazione(state: PraticaUfficioState) -> PraticaUfficioState:
    """Reparto Amministrazione: verifica fatture, registra pagamenti, emette documenti e fornisce IBAN."""
    print(f"\n💰 [REPARTO AMMINISTRAZIONE] Elaborazione richiesta per {state.get('mittente', 'Sconosciuto')}...")

    schema = AzioneAmministrazione.model_json_schema()

    prompt = (
        "Sei l'addetto all'Ufficio Amministrazione e Contabilità di SupervisorHQ.\n\n"
        f"EMAIL DEL CLIENTE:\n{state['email_in_ingresso']}\n\n"
        "REGOLE:\n"
        "- Usa 'STATO_FATTURA' se il cliente chiede informazioni su una fattura specifica (serve numero_fattura).\n"
        "- Usa 'ELENCO_DA_PAGARE' se chiede quali fatture sono ancora aperte o da saldare.\n"
        "- Usa 'EMETTI_FATTURA' se chiede di emettere una nuova fattura per un importo specifico.\n"
        "- Usa 'REGISTRA_PAGAMENTO' se comunica di aver pagato una fattura indicando numero e importo.\n"
        "- Usa 'DATI_BONIFICO' se chiede IBAN, Partita IVA, Codice SDI o coordinate per pagare.\n"
        "- Usa 'CHIARIMENTO' se mancano dati essenziali (NON inventare mai numeri di fattura o importi).\n\n"
        "Rispondi ESCLUSIVAMENTE con un JSON valido che rispetti questo schema:\n"
        f"{json.dumps(schema, indent=2)}"
    )

    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options=OPZIONI_LLM
    )

    try:
        cmd = AzioneAmministrazione.model_validate_json(risp["message"]["content"].strip())
    except ValidationError as e:
        print(f"   -> [⚠️ ERRORE PYDANTIC AMMINISTRAZIONE] {e}")
        return {
            "esito_reparto": "Richiesta amministrativa non chiara. Chiedere al cliente di specificare il numero di fattura o l'operazione desiderata.",
            "prossimo_reparto": "SEGRETERIA_RISPONDE"
        }

    print(f"   -> Azione: {cmd.azione} | Fattura: {cmd.numero_fattura} | Importo: {cmd.importo}")

    try:
        if cmd.azione == "DATI_BONIFICO":
            esito = f"COORDINATE UFFICIALI:\n{ottieni_dati_bonifico(cmd.numero_fattura)}"

        elif cmd.azione == "STATO_FATTURA":
            if not cmd.numero_fattura:
                esito = "CHIARIMENTO NECESSARIO: Indicare il numero esatto della fattura (es. F-2026/001) per verificarne lo stato."
            else:
                f = cerca_fattura(cmd.numero_fattura)
                if not f:
                    esito = f"NON TROVATA: La fattura '{cmd.numero_fattura}' non è presente nel registro contabile."
                else:
                    esito = f"DETTAGLIO FATTURA: {f['numero_fattura']} | Importo: € {float(f['importo']):.2f} | Stato: {f['stato']}."

        elif cmd.azione == "ELENCO_DA_PAGARE":
            aperte = lista_fatture_per_stato("DA_PAGARE")
            if not aperte:
                esito = "TUTTO SALDATO: Non risultano fatture da pagare nel registro."
            else:
                righe = "\n".join(f"- {f['numero_fattura']}: € {float(f['importo']):.2f}" for f in aperte)
                tot = sum(float(f["importo"]) for f in aperte)
                esito = f"FATTURE DA PAGARE:\n{righe}\nTotale residuo: € {tot:.2f}"

        elif cmd.azione == "EMETTI_FATTURA":
            if not cmd.importo or cmd.importo <= 0:
                esito = "CHIARIMENTO NECESSARIO: Specificare l'importo esatto per emettere la fattura."
            else:
                nuova = emetti_nuova_fattura(cmd.importo)
                esito = (
                    f"FATTURA EMESSA: {nuova['numero_fattura']} per € {nuova['importo']:.2f} (Stato: {nuova['stato']}).\n"
                    f"Coordinate per il saldo:\n{ottieni_dati_bonifico(nuova['numero_fattura'])}"
                )

        elif cmd.azione == "REGISTRA_PAGAMENTO":
            if not cmd.numero_fattura or cmd.importo is None:
                esito = "CHIARIMENTO NECESSARIO: Per registrare il pagamento servono sia il numero di fattura sia l'importo versato."
            else:
                esito = registra_pagamento_fattura(cmd.numero_fattura, cmd.importo)

        else:
            esito = f"CHIARIMENTO NECESSARIO: {cmd.nota_chiarimento or 'Specificare il numero di fattura o la richiesta contabile.'}"

    except Exception as e:
        esito = f"ERRORE_CONTABILITA: Impossibile completare l'operazione sul database ({e})."

    print(f"   -> Esito Amministrazione: {esito}")
    return {
        "esito_reparto": esito,
        "prossimo_reparto": "SEGRETERIA_RISPONDE"
    }