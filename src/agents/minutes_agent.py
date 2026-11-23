import json
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import ollama
from pydantic import BaseModel, Field

from src.core.database import lista_dipendenti, salva_verbale_con_azioni

MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}


class RiunioneEstratta(BaseModel):
    titolo: str = Field(description="Titolo della prossima riunione o call.")
    data_ora_iso: Optional[str] = Field(
        default=None,
        description="Data e ora in formato ISO YYYY-MM-DDTHH:MM:00. Null se non specificata.",
    )
    durata_minuti: int = Field(default=60, description="Durata stimata in minuti.")
    partecipanti: list[str] = Field(
        default_factory=list,
        description="Nomi o indirizzi email dei partecipanti da invitare.",
    )
    is_rischedulazione: bool = Field(
        default=False,
        description="True se il verbale chiede di spostare una riunione già esistente.",
    )


class DocumentoCitato(BaseModel):
    nome: str = Field(description="Nome del file, manuale, report o allegato citato.")
    contesto: str = Field(description="Breve nota sul perché è stato citato.")


class ActionItem(BaseModel):
    descrizione: str = Field(description="Attività operativa da svolgere.")
    responsabile: Optional[str] = Field(default=None, description="Nome o email dell'assegnatario.")
    scadenza: Optional[str] = Field(default=None, description="Eventuale data di scadenza.")
    richiede_ticket: bool = Field(
        default=False,
        description="True se l'attività riguarda un bug, guasto o problema tecnico da tracciare come ticket.",
    )


class AnalisiVerbale(BaseModel):
    titolo_verbale: str = Field(description="Titolo sintetico della riunione.")
    riepilogo: str = Field(description="Riassunto esecutivo in 2-3 frasi.")
    riunioni: list[RiunioneEstratta] = Field(default_factory=list)
    documenti_citati: list[DocumentoCitato] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)


def _risolvi_email_partecipanti(nomi_o_email: list[str], rubrica: list[dict]) -> tuple[list[str], list[str]]:
    """Mappa i nomi citati nel verbale sulle email aziendali reali; segnala chi non ha email."""
    risolte = []
    non_trovati = []

    for voce in nomi_o_email:
        v = voce.strip()
        if "@" in v:
            risolte.append(v)
            continue

        v_low = v.lower()
        match = next(
            (
                d for d in rubrica
                if v_low in d["nome_completo"].lower() or v_low == d["username"].lower()
            ),
            None,
        )
        if match and match.get("email_aziendale"):
            risolte.append(match["email_aziendale"])
        else:
            non_trovati.append(v)

    return list(dict.fromkeys(risolte)), non_trovati


def elabora_verbale(testo: str, username: str, fonte: str = "TESTO") -> dict:
    """Analizza il testo di un verbale, risolve i partecipanti e salva le azioni in stato DA_CONFERMARE."""
    adesso = datetime.now(ZoneInfo("Europe/Rome"))
    rubrica = lista_dipendenti()
    elenco_team = "\n".join(
        f"- {d['nome_completo']} (username: {d['username']}, reparto: {d['reparto']}, email: {d.get('email_aziendale') or 'non collegata'})"
        for d in rubrica
    )

    prompt = (
        "Sei l'Agente Verbali di SupervisorHQ. Analizza il verbale di riunione qui sotto ed estrai "
        "tutte le riunioni da schedulare o spostare, i documenti citati da verificare e gli action item.\n"
        f"DATA E ORA ATTUALE: {adesso.strftime('%A %d/%m/%Y %H:%M')} (ISO: {adesso.strftime('%Y-%m-%dT%H:%M:%S')}).\n\n"
        f"TEAM AZIENDALE:\n{elenco_team}\n\n"
        f"TESTO DEL VERBALE:\n{testo}\n\n"
        "REGOLE:\n"
        "- Converti date relative ('giovedì prossimo', 'domani alle 10') in ISO usando la DATA E ORA ATTUALE.\n"
        "- Se una data/ora non è indicata, lascia data_ora_iso = null.\n"
        "- Rispondi ESCLUSIVAMENTE con un JSON valido conforme a questo schema:\n"
        f"{json.dumps(AnalisiVerbale.model_json_schema(), indent=2)}"
    )

    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options=OPZIONI_LLM,
    )

    analisi = AnalisiVerbale.model_validate_json(risp["message"]["content"].strip())

    # Trasforma l'analisi in azioni atomiche approvabili dalla dashboard
    azioni = []

    for r in analisi.riunioni:
        email_ok, nomi_mancanti = _risolvi_email_partecipanti(r.partecipanti, rubrica)
        azioni.append({
            "tipo": "RIUNIONE",
            "descrizione": f"{'Rischedula' if r.is_rischedulazione else 'Schedula'}: {r.titolo} ({r.data_ora_iso or 'data da definire'})",
            "payload": {
                "titolo": r.titolo,
                "data_ora_iso": r.data_ora_iso,
                "durata_minuti": r.durata_minuti,
                "partecipanti_email": email_ok,
                "partecipanti_non_risolti": nomi_mancanti,
                "is_rischedulazione": r.is_rischedulazione,
            },
        })

    for doc in analisi.documenti_citati:
        azioni.append({
            "tipo": "DOCUMENTO",
            "descrizione": f"Verifica documento: {doc.nome}",
            "payload": {"nome": doc.nome, "contesto": doc.contesto},
        })

    for item in analisi.action_items:
        tipo = "TICKET" if item.richiede_ticket else "ACTION_ITEM"
        azioni.append({
            "tipo": tipo,
            "descrizione": item.descrizione,
            "payload": {
                "descrizione": item.descrizione,
                "responsabile": item.responsabile,
                "scadenza": item.scadenza,
            },
        })

    verbale_id = salva_verbale_con_azioni(
        username=username,
        titolo=analisi.titolo_verbale,
        fonte=fonte,
        testo_originale=testo,
        riepilogo=analisi.riepilogo,
        azioni=azioni,
    )

    return {
        "verbale_id": verbale_id,
        "titolo": analisi.titolo_verbale,
        "riepilogo": analisi.riepilogo,
        "azioni_estratte": len(azioni),
    }