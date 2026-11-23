import json
import ollama
from pydantic import ValidationError

from src.core.state import PraticaUfficioState
from src.core.schema import DecisioneSupervisore
from src.tools.email_tools import invia_email

# Costanti LLM
MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}


def nodo_segreteria_smistamento(state: PraticaUfficioState) -> PraticaUfficioState:
    """Fase 1: La Segreteria legge la mail in ingresso e compila il modulo Pydantic per il routing."""
    print(f"\n👩‍💼 [SEGRETERIA - SMISTAMENTO] Analisi della mail di {state.get('mittente', 'Sconosciuto')} in corso...")

    schema_richiesto = DecisioneSupervisore.model_json_schema()
    storico_formattato = "\n".join(state.get("storico_conversazione", []))

    prompt = (
        "Sei il Direttore Operativo (Supervisore) di un'azienda. Il tuo compito è leggere l'email "
        "del cliente, estrarre i dati fondamentali e assegnare la pratica al reparto corretto.\n\n"
        f"STORICO DELLE CONVERSAZIONI PRECEDENTI CON QUESTO CLIENTE:\n{storico_formattato}\n\n"
        f"NUOVA EMAIL IN INGRESSO: {state['email_in_ingresso']}\n\n"
        "REGOLE DI ASSEGNAZIONE RIGOROSE:\n"
        "- AMMINISTRAZIONE: per fatture, pagamenti, iban, ritardi di pagamento.\n"
        "- COMMERCIALE: per richieste di preventivi, nuovi ordini, calcolo costi (SOLO SE ESPLICITAMENTE RICHIESTO).\n"
        "- ASSISTENZA: per problemi tecnici, supporto, resi o malfunzionamenti.\n"
        "- AGENDA: per fissare, spostare, verificare disponibilità o cancellare appuntamenti, call o riunioni.\n"        "- SEGRETERIA_RISPONDE: per domande generiche, semplici saluti o se il cliente CHIEDE DI PARLARE CON UN UMANO/OPERATORE senza specificare il motivo (chiedi come possiamo aiutarlo prima di passargli un tecnico).\n"        "🛑 REGOLA ANTI-ALLUCINAZIONE:\n"
        "Se l'email contiene solo un saluto o è troppo breve per capire cosa vuole il cliente, NON INVENTARE richieste di preventivi o assistenza. "
        "Assegna IMMEDIATAMENTE a 'SEGRETERIA_RISPONDE' e scrivi nel 'motivo_assegnazione' di salutare e chiedere come possiamo essere d'aiuto.\n\n"
        "Devi rispondere ESCLUSIVAMENTE con un oggetto JSON valido che rispetti questo schema esatto:\n"
        f"{json.dumps(schema_richiesto, indent=2)}"
    )

    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        format='json',
        options=OPZIONI_LLM
    )

    testo_json = risp['message']['content'].strip()

    try:
        dati_validati = DecisioneSupervisore.model_validate_json(testo_json)

        print(f"   -> Ragionamento: {dati_validati.ragionamento}")
        print(f"   -> Reparto Scelto: {dati_validati.prossimo_reparto}")
        print(f"   -> Dati Estratti: {dati_validati.dati_estratti}")

        return {
            "prossimo_reparto": dati_validati.prossimo_reparto,
            "motivo_assegnazione": dati_validati.motivo_assegnazione,
            "dati_estratti": dati_validati.dati_estratti,
            "status_pratica": "IN_LAVORAZIONE"
        }

    except ValidationError as e:
        print(f"   -> [⚠️ ERRORE VALIDAZIONE PYDANTIC] Qwen ha generato un output non conforme: {e}")
        return {
            "prossimo_reparto": "SEGRETERIA_RISPONDE",
            "motivo_assegnazione": "Impossibile comprendere la richiesta o output non conforme allo schema. Chiedere chiarimenti al cliente.",
            "dati_estratti": {},
            "status_pratica": "IN_LAVORAZIONE"
        }


def nodo_segreteria_risposta(state: PraticaUfficioState) -> PraticaUfficioState:
    """Fase 2: Il collega ha finito. La Segreteria legge il resoconto e scrive la mail finale al cliente."""
    print("\n👩‍💼 [SEGRETERIA - RISPOSTA FINALE] Impacchettamento della risposta per il cliente...")

    if state["prossimo_reparto"] == "SEGRETERIA_RISPONDE" and not state.get("esito_reparto"):
        resoconto = f"L'email non richiedeva l'intervento di altri reparti. Motivo originario: {state['motivo_assegnazione']}"
    else:
        resoconto = (
            f"Il reparto {state['prossimo_reparto']} ha lavorato la pratica.\n"
            f"Esito del loro lavoro: {state.get('esito_reparto', 'Nessun esito riportato.')}"
        )

    prompt = (
        "Sei l'Assistente di Direzione dell'ufficio. Devi scrivere un'email formale e cortese di "
        f"risposta al cliente ({state['mittente']}).\n\n"
        f"EMAIL ORIGINALE DEL CLIENTE:\n{state['email_in_ingresso']}\n\n"
        f"LAVORO SVOLTO DAI TUOI COLLEGHI (o da te in precedenza):\n{resoconto}\n\n"
        "REGOLE: Scrivi solo il testo dell'email. Sii professionale, chiaro e rassicurante. "
        "Firma come 'Segreteria Direzionale - SupervisorHQ'."
    )

    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        options={"num_ctx": 8192, "temperature": 0.4}
    )

    testo_mail = risp['message']['content'].strip()

    if state.get("invia_email_finale", True):
        print(f"   -> Contatto API Gmail per inviare a: {state['mittente']}...")
        try:
            motivo_pulito = str(state.get('motivo_assegnazione', 'Aggiornamento')).replace('\n', ' ').replace('\r',
                                                                                                              ' ').strip()
            oggetto_mail = f"Risposta alla sua richiesta: {motivo_pulito[:80]}"
            esito_email = invia_email(destinatario=state["mittente"], oggetto=oggetto_mail, corpo=testo_mail)
            print(f"   -> Esito Gmail: {esito_email}")
        except Exception as e:
            print(f"   ❌ Errore API Gmail: {e}")
    else:
        print("   ℹ️ Invio Gmail saltato (invia_email_finale è False: gestito da un altro agente).")

    return {
        "risposta_coordinata": testo_mail,
        "status_pratica": "COMPLETATA",
        "prossimo_reparto": "FINE",
        "storico_conversazione": [f"SUPERVISORHQ: {testo_mail}"]
    }