import json
from typing import Literal, Optional

import ollama
from pydantic import BaseModel, Field, ValidationError

from src.core.state import PraticaUfficioState
from src.tools.rag_tools import cerca_soluzione
from src.tools.ticket_tools import apri_ticket, cerca_ticket, lista_ticket_cliente

MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}


class AzioneAssistenza(BaseModel):
    azione: Literal["RISOLVI_RAG", "APRI_TICKET", "STATO_TICKET", "CHIARIMENTO"] = Field(
        description="Tipo di operazione di supporto tecnico richiesta."
    )
    query_manuale: Optional[str] = Field(
        default=None,
        description="Domanda tecnica sintetica da cercare nel manuale aziendale (per RISOLVI_RAG)."
    )
    codice_ticket: Optional[str] = Field(
        default=None,
        description="Codice del ticket (es. 'TK-2026-001'), se il cliente chiede lo stato."
    )
    priorita: Literal["BASSA", "MEDIA", "ALTA", "CRITICA"] = Field(
        default="MEDIA",
        description="Urgenza del problema (CRITICA per sistemi bloccati/down, ALTA per errori gravi, MEDIA/BASSA per il resto)."
    )
    riepilogo_problema: Optional[str] = Field(
        default=None,
        description="Breve descrizione tecnica del problema segnalato dal cliente."
    )


def _rispondi_da_manuale(domanda: str, estratti_rag: str) -> tuple[bool, str]:
    """Chiede a Qwen di rispondere SOLO usando il manuale. Restituisce (trovato, testo)."""
    prompt = (
        "Sei un tecnico di supporto di SupervisorHQ.\n"
        "Rispondi alla domanda del cliente basandoti ESCLUSIVAMENTE sugli estratti del manuale forniti sotto.\n"
        "Se negli estratti NON c'è la soluzione al problema, rispondi ESATTAMENTE con la parola: NON_PRESENTE\n\n"
        f"ESTRATTi MANUALE:\n{estratti_rag}\n\n"
        f"DOMANDA CLIENTE:\n{domanda}"
    )
    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        options=OPZIONI_LLM
    )
    testo = risp["message"]["content"].strip()
    if "NON_PRESENTE" in testo.upper():
        return False, ""
    return True, testo


def nodo_assistenza(state: PraticaUfficioState) -> PraticaUfficioState:
    """Reparto Assistenza Tecnica: risolve via RAG dal manuale o apre/verifica ticket su SQLite."""
    print(f"\n🛠️ [REPARTO ASSISTENZA] Elaborazione richiesta per {state.get('mittente', 'Sconosciuto')}...")

    schema = AzioneAssistenza.model_json_schema()

    prompt = (
        "Sei l'addetto all'Helpdesk Tecnico di SupervisorHQ.\n\n"
        f"EMAIL DEL CLIENTE:\n{state['email_in_ingresso']}\n\n"
        "REGOLE:\n"
        "- Usa 'RISOLVI_RAG' per domande tecniche, errori software, installazione o configurazione.\n"
        "- Usa 'APRI_TICKET' se il cliente chiede esplicitamente di aprire un ticket o segnala un guasto critico/server down.\n"
        "- Usa 'STATO_TICKET' se chiede aggiornamenti su un ticket già aperto.\n"
        "- Usa 'CHIARIMENTO' se il messaggio è troppo vago e non descrive alcun problema tecnico.\n\n"
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
        cmd = AzioneAssistenza.model_validate_json(risp["message"]["content"].strip())
    except ValidationError as e:
        print(f"   -> [⚠️ ERRORE PYDANTIC ASSISTENZA] {e}")
        return {
            "esito_reparto": "Richiesta tecnica non chiara. Chiedere al cliente di descrivere l'errore riscontrato.",
            "prossimo_reparto": "SEGRETERIA_RISPONDE"
        }

    mittente = state.get("mittente", "sconosciuto@email.com")
    print(f"   -> Azione: {cmd.azione} | Priorità: {cmd.priorita} | Ticket: {cmd.codice_ticket}")

    try:
        if cmd.azione == "STATO_TICKET":
            if cmd.codice_ticket:
                tk = cerca_ticket(cmd.codice_ticket)
                if not tk:
                    esito = f"TICKET NON TROVATO: Nessun ticket registrato con codice '{cmd.codice_ticket}'."
                else:
                    esito = (
                        f"STATO TICKET {tk['codice_ticket']}:\n"
                        f"Stato: {tk['stato']} | Priorità: {tk['priorita']} | Aperto il: {tk['data_creazione']}\n"
                        f"Problema: {tk['problema']}"
                    )
            else:
                elenco = lista_ticket_cliente(mittente)
                if not elenco:
                    esito = f"NESSUN TICKET: Non risultano ticket aperti associati a {mittente}."
                else:
                    righe = "\n".join(f"- {t['codice_ticket']} ({t['stato']}, {t['priorita']}): {t['problema']}" for t in elenco)
                    esito = f"TICKET REGISTRATI PER {mittente}:\n{righe}"

        elif cmd.azione == "APRI_TICKET":
            tk = apri_ticket(mittente, cmd.riepilogo_problema or state["email_in_ingresso"], cmd.priorita)
            esito = (
                f"TICKET APERTO: Codice {tk['codice_ticket']} (Priorità: {tk['priorita']}, Stato: {tk['stato']}).\n"
                "Un tecnico umano prenderà in carico la segnalazione al più presto."
            )

        elif cmd.azione == "RISOLVI_RAG":
            query = cmd.query_manuale or state["email_in_ingresso"]
            estratti = cerca_soluzione(query)
            trovato, soluzione = _rispondi_da_manuale(query, str(estratti))

            if trovato:
                esito = f"SOLUZIONE DAL MANUALE TECNICO:\n{soluzione}"
            else:
                # Escalation automatica: se non è nel manuale, apre un ticket
                tk = apri_ticket(mittente, cmd.riepilogo_problema or query, cmd.priorita)
                esito = (
                    f"ESCALATION AUTOMATICA: Il problema non è coperto dal manuale tecnico.\n"
                    f"È stato aperto automaticamente il ticket {tk['codice_ticket']} (Priorità: {tk['priorita']}).\n"
                    "Comunicare al cliente il codice del ticket e che un tecnico lo contatterà a breve."
                )

        else:
            esito = "CHIARIMENTO NECESSARIO: Chiedere al cliente maggiori dettagli sul problema tecnico o sul messaggio di errore."

    except Exception as e:
        esito = f"ERRORE_ASSISTENZA: Impossibile completare l'operazione ({e})."

    print(f"   -> Esito Assistenza: {esito}")
    return {
        "esito_reparto": esito,
        "prossimo_reparto": "SEGRETERIA_RISPONDE"
    }