import json
from typing import Literal, Optional

import ollama
from pydantic import BaseModel, Field, ValidationError

from src.core.state import PraticaUfficioState
from src.tools.sales_tools import (
    ottieni_catalogo_soluzioni,
    calcola_preventivo,
    genera_codici_licenza,
)

MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}


class AzioneCommerciale(BaseModel):
    azione: Literal["CATALOGO", "PREVENTIVO", "ORDINE", "CHIARIMENTO"] = Field(
        description="Tipo di richiesta commerciale del cliente."
    )
    soluzione_richiesta: Optional[str] = Field(
        default=None,
        description="Titolo esatto della soluzione dal catalogo aziendale, se identificabile."
    )
    quantita: int = Field(
        default=1,
        description="Numero di licenze o unità richieste (default 1)."
    )
    nota_chiarimento: Optional[str] = Field(
        default=None,
        description="Se azione='CHIARIMENTO', spiega cosa manca per formulare il preventivo."
    )


def nodo_commerciale(state: PraticaUfficioState) -> PraticaUfficioState:
    """Reparto Commerciale: gestisce catalogo, preventivi (con sconti/IVA) e conferma ordini."""
    print(f"\n💼 [REPARTO COMMERCIALE] Elaborazione richiesta per {state.get('mittente', 'Sconosciuto')}...")

    catalogo = ottieni_catalogo_soluzioni()
    catalogo_txt = "\n".join(
        f"- {s['titolo']} | Prezzo: {s['prezzo']} | {s['descrizione']}"
        for s in catalogo
    ) or "Nessuna soluzione attualmente a catalogo."

    schema = AzioneCommerciale.model_json_schema()

    prompt = (
        "Sei l'addetto all'Ufficio Commerciale di SupervisorHQ.\n\n"
        f"CATALOGO SOLUZIONI ATTUALE:\n{catalogo_txt}\n\n"
        f"EMAIL DEL CLIENTE:\n{state['email_in_ingresso']}\n\n"
        "REGOLE:\n"
        "- Usa 'CATALOGO' se il cliente chiede informazioni generali sui prodotti o sui prezzi.\n"
        "- Usa 'PREVENTIVO' se chiede un preventivo o il costo per una soluzione specifica.\n"
        "- Usa 'ORDINE' se il cliente conferma esplicitamente di voler acquistare/attivare una soluzione.\n"
        "- Usa 'CHIARIMENTO' se il prodotto richiesto non è chiaro o non esiste a catalogo.\n"
        "- Nel campo 'soluzione_richiesta' copia il titolo esatto dal catalogo sopra.\n\n"
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
        cmd = AzioneCommerciale.model_validate_json(risp["message"]["content"].strip())
    except ValidationError as e:
        print(f"   -> [⚠️ ERRORE PYDANTIC COMMERCIALE] {e}")
        return {
            "esito_reparto": "Richiesta commerciale non chiara. Chiedere al cliente quale soluzione del catalogo desidera.",
            "prossimo_reparto": "SEGRETERIA_RISPONDE"
        }

    print(f"   -> Azione: {cmd.azione} | Soluzione: {cmd.soluzione_richiesta} | Quantità: {cmd.quantita}")

    if cmd.azione == "CATALOGO":
        esito = f"CATALOGO DISPONIBILE:\n{catalogo_txt}\n(Sconti automatici: 10% da 5+ licenze, 15% da 10+ licenze. Prezzi IVA 22% esclusa.)"

    elif cmd.azione == "CHIARIMENTO" or not cmd.soluzione_richiesta:
        esito = (
            f"CHIARIMENTO NECESSARIO: {cmd.nota_chiarimento or 'Specificare la soluzione desiderata.'}\n"
            f"Soluzioni disponibili: {', '.join(s['titolo'] for s in catalogo)}."
        )

    elif cmd.azione in ("PREVENTIVO", "ORDINE"):
        calc = calcola_preventivo(cmd.soluzione_richiesta, cmd.quantita)

        if not calc["trovata"]:
            esito = f"PRODOTTO NON TROVATO: {calc['errore']} Soluzioni disponibili: {', '.join(s['titolo'] for s in catalogo)}."
        elif calc.get("su_misura"):
            esito = f"QUOTAZIONE SU MISURA: {calc['messaggio']}"
        else:
            riepilogo = (
                f"Soluzione: {calc['soluzione']}\n"
                f"Quantità: {calc['quantita']} x € {calc['prezzo_unitario']:.2f}\n"
                f"Sconto volume ({calc['sconto_perc']}%): -€ {calc['importo_sconto']:.2f}\n"
                f"Imponibile: € {calc['imponibile']:.2f}\n"
                f"IVA (22%): € {calc['iva']:.2f}\n"
                f"TOTALE: € {calc['totale']:.2f}"
            )
            if cmd.azione == "PREVENTIVO":
                esito = f"PREVENTIVO CALCOLATO:\n{riepilogo}\nChiedere al cliente se desidera confermare l'ordine."
            else:
                codici = genera_codici_licenza(calc["quantita"])
                esito = (
                    f"ORDINE CONFERMATO:\n{riepilogo}\n"
                    f"Codici di attivazione generati: {', '.join(codici)}\n"
                    "Informare il cliente che la pratica è stata presa in carico per l'emissione della fattura."
                )

    print(f"   -> Esito Commerciale: {esito}")
    return {
        "esito_reparto": esito,
        "prossimo_reparto": "SEGRETERIA_RISPONDE"
    }