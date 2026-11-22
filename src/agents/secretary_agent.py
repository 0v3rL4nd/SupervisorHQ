import json
import ollama
from datetime import datetime

from src.core.state import PraticaUfficioState
from src.core.schema import ParametriEvento
# Importiamo la TUA funzione con i TUOI parametri
from src.tools.calendar_tools import crea_evento_calendario

MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}


def nodo_agenda(state: PraticaUfficioState) -> PraticaUfficioState:
    print("\n📅 [UFFICIO AGENDA] Creazione evento sul calendario in corso...")

    schema_richiesto = ParametriEvento.model_json_schema()

    # Otteniamo la data odierna per dare contesto temporale a Qwen
    oggi = datetime.now()
    giorno_settimana = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"][oggi.weekday()]
    data_odierna_str = f"{giorno_settimana} {oggi.strftime('%d/%m/%Y')}"

    prompt = (
        "Sei il Segretario Organizzativo. Devi estrarre i dati per fissare una riunione su Google Calendar.\n\n"
        f"RICHIESTA DEL SUPERVISORE: {state['motivo_assegnazione']}\n"
        f"DATI ESTRATTI: {json.dumps(state['dati_estratti'])}\n\n"
        f"OGGI È: {data_odierna_str}.\n"
        "Calcola le date corrette se il cliente usa termini come 'giovedì prossimo' o 'domani'. "
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
        evento = ParametriEvento.model_validate_json(risp['message']['content'].strip())
        print(f"   -> Chiamata API Calendar: {evento.titolo} ({evento.data_inizio})")

        # CHIAMATA AL TUO TOOL FISICO
        # Passiamo anche il 'mittente' preso dallo state per invitare automaticamente il cliente!
        esito_calendar = crea_evento_calendario(
            titolo=evento.titolo,
            data_inizio=evento.data_inizio,
            ore_durata=evento.ore_durata,
            descrizione=evento.descrizione,
            partecipanti=[state["mittente"]]  # Il cliente riceverà l'invito Meet ufficiale
        )

        return {
            "esito_reparto": f"Appunti Segreteria: {esito_calendar}",
            "status_pratica": "COMPLETATA",
            # NUOVO: Blocca la Segreteria, il cliente riceverà solo l'invito di Calendar!
            "invia_email_finale": False
        }

    except Exception as e:
        print(f"   -> [⚠️ ERRORE CALENDAR] Impossibile creare l'evento: {e}")
        return {
            "esito_reparto": "Errore tecnico durante la creazione dell'evento su Google Calendar. Segnala al cliente l'imprevisto.",
            "status_pratica": "ERRORE"
        }