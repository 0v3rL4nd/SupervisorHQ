import json
from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import ollama
from pydantic import BaseModel, Field, ValidationError

from src.core.state import PraticaUfficioState
from src.tools.calendar_tools import (
    verifica_disponibilita,
    prenota_appuntamento,
    sposta_appuntamento,
    cancella_appuntamento,
)

MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}


class AzioneAgenda(BaseModel):
    azione: Literal["PRENOTA", "SPOSTA", "CANCELLA", "VERIFICA", "CHIARIMENTO"] = Field(
        description="Tipo di operazione richiesta dal cliente sull'agenda."
    )
    titolo: Optional[str] = Field(
        default="Call SupervisorHQ",
        description="Titolo breve dell'appuntamento (es. 'Demo Licenze Enterprise')."
    )
    data_ora_iso: Optional[str] = Field(
        default=None,
        description="Data e ora di inizio in formato ISO YYYY-MM-DDTHH:MM:00 (es. 2026-11-25T15:00:00). Null se manca."
    )
    durata_minuti: int = Field(
        default=60,
        description="Durata in minuti (default 60 se non specificata)."
    )
    nota_chiarimento: Optional[str] = Field(
        default=None,
        description="Se azione='CHIARIMENTO', spiega cosa manca (es. data o orario non indicati)."
    )


def nodo_agenda(state: PraticaUfficioState) -> PraticaUfficioState:
    """Reparto Agenda: gestisce prenotazioni, conflitti, spostamenti e cancellazioni su Google Calendar."""
    print(f"\n📅 [REPARTO AGENDA] Elaborazione richiesta per {state.get('mittente', 'Sconosciuto')}...")

    adesso = datetime.now(ZoneInfo("Europe/Rome"))
    schema = AzioneAgenda.model_json_schema()

    prompt = (
        "Sei l'addetto all'Ufficio Agenda di SupervisorHQ.\n"
        f"DATA E ORA ATTUALE: {adesso.strftime('%A %d/%m/%Y %H:%M')} (ISO: {adesso.strftime('%Y-%m-%dT%H:%M:%S')}).\n\n"
        f"EMAIL DEL CLIENTE:\n{state['email_in_ingresso']}\n\n"
        "REGOLE:\n"
        "- Usa 'PRENOTA' se il cliente chiede di fissare una call/riunione e fornisce data e ora.\n"
        "- Usa 'SPOSTA' se chiede di cambiare data/ora a un appuntamento già esistente.\n"
        "- Usa 'CANCELLA' se chiede di annullare un appuntamento.\n"
        "- Usa 'VERIFICA' se chiede solo se siamo liberi in un certo giorno/orario senza confermare.\n"
        "- Usa 'CHIARIMENTO' se mancano data o orario (NON inventare mai date).\n"
        "- Converti riferimenti relativi ('domani', 'lunedì prossimo') usando la DATA E ORA ATTUALE.\n\n"
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
        cmd = AzioneAgenda.model_validate_json(risp["message"]["content"].strip())
    except ValidationError as e:
        print(f"   -> [⚠️ ERRORE PYDANTIC AGENDA] {e}")
        return {
            "esito_reparto": "Non è stato possibile interpretare data e ora della richiesta. Chiedere al cliente di indicare giorno e orario precisi.",
            "prossimo_reparto": "SEGRETERIA_RISPONDE"
        }

    mittente = state.get("mittente", "")
    print(f"   -> Azione: {cmd.azione} | Data: {cmd.data_ora_iso} | Durata: {cmd.durata_minuti} min")

    try:
        if cmd.azione == "CHIARIMENTO" or (cmd.azione in ("PRENOTA", "SPOSTA", "VERIFICA") and not cmd.data_ora_iso):
            esito = f"CHIARIMENTO NECESSARIO: {cmd.nota_chiarimento or 'Mancano data o orario precisi per gestire l’appuntamento.'}"

        elif cmd.azione == "VERIFICA":
            check = verifica_disponibilita(cmd.data_ora_iso, cmd.durata_minuti)
            if check["libero"]:
                esito = f"DISPONIBILE: Lo slot {cmd.data_ora_iso} ({cmd.durata_minuti} min) è libero. Chiedi al cliente se vuole confermare."
            else:
                alt = ", ".join(check["alternative"]) or "nessun altro slot in giornata"
                esito = f"OCCUPATO: Lo slot {cmd.data_ora_iso} non è disponibile. Alternative libere: {alt}."

        elif cmd.azione == "PRENOTA":
            esito = prenota_appuntamento(
                titolo=cmd.titolo or f"Riunione con {mittente}",
                data_ora_iso=cmd.data_ora_iso,
                durata_minuti=cmd.durata_minuti,
                email_cliente=mittente
            )

        elif cmd.azione == "SPOSTA":
            esito = sposta_appuntamento(
                email_cliente=mittente,
                nuova_data_ora_iso=cmd.data_ora_iso,
                durata_minuti=cmd.durata_minuti
            )

        elif cmd.azione == "CANCELLA":
            esito = cancella_appuntamento(email_cliente=mittente)

    except Exception as e:
        esito = f"ERRORE_CALENDAR: Impossibile completare l'operazione su Google Calendar ({e})."

    print(f"   -> Esito Agenda: {esito}")
    return {
        "esito_reparto": esito,
        "prossimo_reparto": "SEGRETERIA_RISPONDE"
    }