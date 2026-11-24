import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import ollama
from pydantic import BaseModel, Field

from src.core.database import (
    lista_dipendenti,
    ottieni_dipendente,
    salva_verbale_con_azioni,
    ottieni_azione_verbale,
    aggiorna_stato_azione_verbale,
    ottieni_tutte_le_soluzioni,
    crea_soluzione,
    aggiorna_soluzione,
    elimina_soluzione,
)
from src.tools.billing_tools import (
    ottieni_tutte_le_fatture,
    crea_nuova_fattura,
    gestisci_pagamento,
    aggiorna_fattura,
    elimina_fattura,
)
from src.tools.calendar_tools import prenota_appuntamento, verifica_disponibilita
from src.tools.email_tools import invia_email
from src.tools.ticket_tools import apri_ticket
from src.tools.document_parser import estrai_testo_da_bytes

MODELLO_LLM = "qwen2.5:14b"
OPZIONI_LLM = {"num_ctx": 8192, "temperature": 0.1}

MAPPA_AGENTI = {
    "RIUNIONE": "AGENTE_AGENDA",
    "DOCUMENTO": "AGENTE_DOCUMENTI",
    "TICKET": "AGENTE_SUPPORTO",
    "EMAIL": "AGENTE_COMMERCIALE",
    "ACTION_ITEM": "AGENTE_OPERATIVO",
    "CATALOGO": "AGENTE_CATALOGO",
    "FATTURA": "AGENTE_CONTABILITA",
}


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
    richiede_email: bool = Field(
        default=False,
        description="True se l'attività prevede di inviare un'email o un documento via email a un cliente o collega.",
    )
    destinatario_email: Optional[str] = Field(
        default=None,
        description="Indirizzo email (o nome se l'email non è nel testo) del destinatario.",
    )
    oggetto_email: Optional[str] = Field(
        default=None,
        description="Oggetto professionale dell'email da inviare.",
    )
    corpo_email: Optional[str] = Field(
        default=None,
        description="Testo pronto e professionale dell'email da inviare.",
    )
    allegato_richiesto: Optional[str] = Field(
        default=None,
        description="Nome del file locale da allegare all'email (es. 'listino_2026.pdf'), se il verbale chiede di inviarlo.",
    )
    includi_contenuto_file: Optional[str] = Field(
        default=None,
        description="Nome del file locale da leggere per includere dati o un estratto nel corpo dell'email.",
    )
    priorita_ticket: Optional[str] = Field(
        default="MEDIA",
        description="Se richiede_ticket=True, indica la priorità tra BASSA, MEDIA, ALTA, CRITICA.",
    )


class OperazioneCatalogo(BaseModel):
    azione: str = Field(description="Tipo operazione: 'CREA', 'AGGIORNA' oppure 'ELIMINA'.")
    soluzione_id: Optional[int] = Field(
        default=None,
        description="ID della soluzione esistente (obbligatorio per AGGIORNA o ELIMINA).",
    )
    titolo: Optional[str] = Field(default=None, description="Titolo della soluzione/pacchetto.")
    prezzo: Optional[str] = Field(default=None, description="Prezzo formattato (es. '€ 299 / mese').")
    descrizione: Optional[str] = Field(default=None, description="Descrizione breve della soluzione.")
    icona: str = Field(default="🚀", description="Emoji rappresentativa.")
    prompt_precompilato: Optional[str] = Field(
        default=None,
        description="Prompt precompilato per il portale clienti.",
    )
    responsabile: Optional[str] = Field(default=None, description="Nome o username di chi deve approvare.")


class OperazioneFattura(BaseModel):
    azione: str = Field(description="Tipo operazione: 'EMETTI', 'PAGA', 'AGGIORNA' oppure 'ELIMINA'.")
    numero_fattura: Optional[str] = Field(
        default=None,
        description="Numero fattura esistente (es. 'F-2026/05'), obbligatorio per PAGA, AGGIORNA, ELIMINA.",
    )
    importo: Optional[float] = Field(default=None, description="Importo in euro (es. 1500.0).")
    stato: Optional[str] = Field(default=None, description="Stato per AGGIORNA: 'DA_PAGARE' o 'PAGATA'.")
    responsabile: Optional[str] = Field(default=None, description="Nome o username di chi deve approvare.")


class AnalisiVerbale(BaseModel):
    titolo_verbale: str = Field(default="Documento senza titolo", description="Titolo sintetico.")
    riepilogo: str = Field(default="Nessun riepilogo estratto.", description="Riassunto esecutivo in 2-3 frasi.")
    riunioni: list[RiunioneEstratta] = Field(default_factory=list)
    documenti_citati: list[DocumentoCitato] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    operazioni_catalogo: list[OperazioneCatalogo] = Field(default_factory=list)
    operazioni_fatture: list[OperazioneFattura] = Field(default_factory=list)


def _percorso_assoluto_progetto(percorso_rel: str) -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_dir, percorso_rel)


def _cerca_documento_locale(nome_doc: str) -> str | None:
    """Cerca il documento citato nelle cartelle locali del progetto (es. data/, docs/, manuali/)."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cartelle_target = [
        os.path.join(base_dir, "data"),
        os.path.join(base_dir, "docs"),
        os.path.join(base_dir, "manuali"),
        base_dir,
    ]
    target = nome_doc.strip().lower()

    for cartella in cartelle_target:
        if not os.path.isdir(cartella):
            continue
        for root, _, files in os.walk(cartella):
            if ".venv" in root or ".git" in root or "__pycache__" in root:
                continue
            for f in files:
                if target in f.lower() or f.lower() in target:
                    return os.path.relpath(os.path.join(root, f), base_dir)
    return None


def _leggi_documento_locale(percorso_rel: str, max_chars: int = 12000) -> str:
    """Estrae il testo da un file locale (PDF, DOCX, TXT, MD) usando document_parser."""
    abs_path = _percorso_assoluto_progetto(percorso_rel)
    with open(abs_path, "rb") as f:
        contenuto = f.read()
    testo = estrai_testo_da_bytes(contenuto, os.path.basename(abs_path))
    return (testo or "")[:max_chars]


def _arricchisci_corpo_email_con_file(corpo_base: str, nome_file: str, testo_file: str) -> str:
    """Riscrive la bozza email integrando i dati reali estratti dal documento locale."""
    prompt = (
        "Integra la bozza email qui sotto inserendo in modo chiaro e professionale le informazioni "
        f"rilevanti estratte dal documento '{nome_file}'. Restituisci SOLO il testo finale dell'email.\n\n"
        f"BOZZA EMAIL:\n{corpo_base}\n\n"
        f"CONTENUTO DEL DOCUMENTO ({nome_file}):\n{testo_file}"
    )
    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        options=OPZIONI_LLM,
    )
    return risp["message"]["content"].strip()


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


def _risolvi_username_assegnatario(
    nome_o_email: Optional[str],
    rubrica: list[dict],
    fallback_username: str,
) -> str:
    """Risolve il nome/email estratto dal verbale nello username reale della tabella dipendenti."""
    if not nome_o_email:
        return fallback_username
    target = nome_o_email.strip().lower()
    for d in rubrica:
        if (
            target == d["username"].lower()
            or target in d["nome_completo"].lower()
            or (d.get("email_aziendale") and target == d["email_aziendale"].lower())
        ):
            return d["username"]
    return fallback_username


def elabora_verbale(testo: str, username: str, fonte: str = "TESTO") -> dict:
    """Analizza il testo di un verbale, smista le azioni agli assegnatari/agenti e le salva in DA_CONFERMARE."""
    adesso = datetime.now(ZoneInfo("Europe/Rome"))
    rubrica = lista_dipendenti()
    elenco_team = "\n".join(
        f"- {d['nome_completo']} (username: {d['username']}, reparto: {d['reparto']}, email: {d.get('email_aziendale') or 'non collegata'})"
        for d in rubrica
    )

    catalogo_attuale = ottieni_tutte_le_soluzioni()
    elenco_catalogo = "\n".join(
        f"- ID {s['id']}: {s['titolo']} | Prezzo: {s['prezzo']} | Desc: {s['descrizione']}"
        for s in catalogo_attuale
    ) or "Nessuna soluzione a catalogo."

    fatture_attuali = ottieni_tutte_le_fatture()
    elenco_fatture = "\n".join(
        f"- {f['numero_fattura']} | Importo: € {f['importo']} | Stato: {f['stato']}"
        for f in fatture_attuali
    ) or "Nessuna fattura registrata."

    prompt = (
        "Sei l'Agente Verbali di SupervisorHQ. Analizza il testo qui sotto ed estrai "
        "un titolo sintetico, un breve riepilogo, eventuali riunioni da schedulare o spostare, "
        "documenti citati da verificare, operazioni su catalogo soluzioni, operazioni su fatture "
        "e action item (specificando se richiedono apertura ticket o invio email).\n"
        f"DATA E ORA ATTUALE: {adesso.strftime('%A %d/%m/%Y %H:%M')} (ISO: {adesso.strftime('%Y-%m-%dT%H:%M:%S')}).\n\n"
        f"TEAM AZIENDALE:\n{elenco_team}\n\n"
        f"CATALOGO SOLUZIONI ATTUALE:\n{elenco_catalogo}\n\n"
        f"FATTURE ATTUALI:\n{elenco_fatture}\n\n"
        f"TESTO DEL VERBALE:\n{testo}\n\n"
        "REGOLE:\n"
        "- Converti date relative ('giovedì prossimo', 'domani alle 10') in ISO YYYY-MM-DDTHH:MM:00 usando la DATA E ORA ATTUALE.\n"
        "- Se una data/ora non è indicata, lascia data_ora_iso = null.\n"
        "- Se un'attività prevede l'invio di un'email o di un listino/documento a qualcuno, imposta richiede_email = true e compila destinatario_email, oggetto_email, corpo_email e, se citati, allegato_richiesto e includi_contenuto_file.\n"
        "- Se il verbale chiede di aggiungere, modificare o eliminare un pacchetto dal catalogo, usa operazioni_catalogo (e NON duplicarlo in action_items).\n"
        "- Se il verbale chiede di emettere, pagare, aggiornare o eliminare una fattura, usa operazioni_fatture (e NON duplicarlo in action_items).\n"
        "- Indica sempre il responsabile reale dell'attività nel campo responsabile quando citato nel verbale.\n"
        "- Compila esclusivamente i campi richiesti dallo schema JSON."
    )

    print(f"📝 [VERBALI] Avvio analisi AI con {MODELLO_LLM} (fonte: {fonte}, caratteri: {len(testo)})...")
    risp = ollama.chat(
        model=MODELLO_LLM,
        messages=[{"role": "user", "content": prompt}],
        format=AnalisiVerbale.model_json_schema(),
        options=OPZIONI_LLM,
    )
    print("✅ [VERBALI] Risposta ricevuta da Ollama, validazione Pydantic in corso...")

    analisi = AnalisiVerbale.model_validate_json(risp["message"]["content"].strip())

    azioni = []

    for r in analisi.riunioni:
        email_ok, nomi_mancanti = _risolvi_email_partecipanti(r.partecipanti, rubrica)
        assegnatario = _risolvi_username_assegnatario(
            r.partecipanti[0] if r.partecipanti else None, rubrica, username
        )
        azioni.append({
            "tipo": "RIUNIONE",
            "assegnatario_username": assegnatario,
            "agente_competente": MAPPA_AGENTI["RIUNIONE"],
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
        percorso_trovato = _cerca_documento_locale(doc.nome)
        azioni.append({
            "tipo": "DOCUMENTO",
            "assegnatario_username": username,
            "agente_competente": MAPPA_AGENTI["DOCUMENTO"],
            "descrizione": f"Verifica documento: {doc.nome}",
            "payload": {
                "nome": doc.nome,
                "contesto": doc.contesto,
                "percorso_locale": percorso_trovato,
            },
        })

    for item in analisi.action_items:
        if item.richiede_ticket:
            tipo = "TICKET"
            email_resp, _ = _risolvi_email_partecipanti(
                [item.responsabile] if item.responsabile else [],
                rubrica,
            )
            dip_creatore = ottieni_dipendente(username)
            email_richiedente = (
                email_resp[0]
                if email_resp
                else ((dip_creatore or {}).get("email_aziendale") or f"{username}@supervisorhq.local")
            )
            priorita = (item.priorita_ticket or "MEDIA").upper()
            if priorita not in {"BASSA", "MEDIA", "ALTA", "CRITICA"}:
                priorita = "MEDIA"

            payload = {
                "email_cliente": email_richiedente,
                "problema": item.descrizione,
                "priorita": priorita,
                "responsabile": item.responsabile,
                "scadenza": item.scadenza,
            }
        elif item.richiede_email:
            tipo = "EMAIL"
            email_ok, non_risolti = _risolvi_email_partecipanti(
                [item.destinatario_email] if item.destinatario_email else [],
                rubrica,
            )
            destinatario_finale = email_ok[0] if email_ok else (non_risolti[0] if non_risolti else None)
            corpo_finale = item.corpo_email or item.descrizione

            if item.includi_contenuto_file:
                percorso_src = _cerca_documento_locale(item.includi_contenuto_file)
                if percorso_src:
                    try:
                        testo_file = _leggi_documento_locale(percorso_src)
                        if testo_file:
                            corpo_finale = _arricchisci_corpo_email_con_file(
                                corpo_finale, item.includi_contenuto_file, testo_file
                            )
                    except Exception as e:
                        print(f"⚠️ [VERBALI] Impossibile leggere '{percorso_src}': {e}")

            allegato_percorso = (
                _cerca_documento_locale(item.allegato_richiesto)
                if item.allegato_richiesto
                else None
            )

            payload = {
                "descrizione": item.descrizione,
                "destinatario": destinatario_finale,
                "oggetto": item.oggetto_email or f"Aggiornamento: {analisi.titolo_verbale}",
                "corpo": corpo_finale,
                "allegato_nome": item.allegato_richiesto,
                "allegato_percorso": allegato_percorso,
                "responsabile": item.responsabile,
                "scadenza": item.scadenza,
            }
        else:
            tipo = "ACTION_ITEM"
            email_resp, _ = _risolvi_email_partecipanti(
                [item.responsabile] if item.responsabile else [],
                rubrica,
            )
            payload = {
                "descrizione": item.descrizione,
                "responsabile": item.responsabile,
                "responsabile_email": email_resp[0] if email_resp else None,
                "scadenza": item.scadenza,
            }

        assegnatario = _risolvi_username_assegnatario(item.responsabile, rubrica, username)
        azioni.append({
            "tipo": tipo,
            "assegnatario_username": assegnatario,
            "agente_competente": MAPPA_AGENTI[tipo],
            "descrizione": item.descrizione,
            "payload": payload,
        })

    for cat in analisi.operazioni_catalogo:
        op = (cat.azione or "CREA").upper()
        assegnatario = _risolvi_username_assegnatario(cat.responsabile, rubrica, username)
        azioni.append({
            "tipo": "CATALOGO",
            "assegnatario_username": assegnatario,
            "agente_competente": MAPPA_AGENTI["CATALOGO"],
            "descrizione": f"{op} soluzione catalogo: {cat.titolo or f'ID #{cat.soluzione_id}'}",
            "payload": {
                "azione": op,
                "soluzione_id": cat.soluzione_id,
                "titolo": cat.titolo or "",
                "prezzo": cat.prezzo or "",
                "descrizione": cat.descrizione or "",
                "icona": cat.icona or "🚀",
                "prompt_precompilato": cat.prompt_precompilato or f"Vorrei informazioni su {cat.titolo or 'questa soluzione'}.",
            },
        })

    for fat in analisi.operazioni_fatture:
        op = (fat.azione or "EMETTI").upper()
        assegnatario = _risolvi_username_assegnatario(fat.responsabile, rubrica, username)
        desc_fat = (
            f"Emetti nuova fattura (€ {fat.importo})"
            if op == "EMETTI"
            else f"{op} fattura {fat.numero_fattura or '(numero mancante)'}"
        )
        azioni.append({
            "tipo": "FATTURA",
            "assegnatario_username": assegnatario,
            "agente_competente": MAPPA_AGENTI["FATTURA"],
            "descrizione": desc_fat,
            "payload": {
                "azione": op,
                "numero_fattura": fat.numero_fattura or "",
                "importo": fat.importo,
                "stato": (fat.stato or "").upper() or None,
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


def esegui_azione_verbale(azione_id: int, username: str, is_admin: bool = False) -> dict:
    """Esegue concretamente un'azione approvata dall'assegnatario (o admin) dopo il commit umano."""
    azione = ottieni_azione_verbale(azione_id)
    if not azione:
        raise ValueError(f"Azione #{azione_id} non trovata.")

    assegnatario = azione.get("assegnatario_username")
    if assegnatario and assegnatario != username and not is_admin:
        raise PermissionError(
            f"Accesso negato: questa azione è assegnata a '{assegnatario}'."
        )

    tipo = azione["tipo"]
    payload = azione["payload"]

    try:
        if tipo == "RIUNIONE":
            data_ora = payload.get("data_ora_iso")
            if not data_ora:
                raise ValueError("Data/ora mancante nel verbale: impossibile schedulare automaticamente.")
            esito = prenota_appuntamento(
                titolo=payload.get("titolo", "Riunione SupervisorHQ"),
                data_ora_iso=data_ora,
                durata_minuti=int(payload.get("durata_minuti", 60)),
                partecipanti=payload.get("partecipanti_email", []),
                username=username,
            )
            stato_finale = "CONFLITTO" if esito.startswith("OCCUPATO") else "ESEGUITA"

        elif tipo == "DOCUMENTO":
            nome = payload.get("nome", "")
            percorso = _cerca_documento_locale(nome)
            if percorso:
                try:
                    testo_doc = _leggi_documento_locale(percorso)
                    risp_rev = ollama.chat(
                        model=MODELLO_LLM,
                        messages=[{
                            "role": "user",
                            "content": (
                                f"Fai una breve revisione esecutiva (massimo 4 righe) del documento '{nome}' "
                                f"nel contesto: {payload.get('contesto', 'verifica generale')}.\n\n{testo_doc}"
                            ),
                        }],
                        options=OPZIONI_LLM,
                    )
                    sintesi = risp_rev["message"]["content"].strip()
                    esito = f"TROVATO ({percorso}) — Revisione AI:\n{sintesi}"
                except Exception as err:
                    esito = f"TROVATO ({percorso}), ma lettura non riuscita: {err}"
                stato_finale = "ESEGUITA"
            else:
                esito = f"MANCANTE: nessun file corrispondente a '{nome}' trovato nelle cartelle locali."
                stato_finale = "ATTENZIONE"

        elif tipo == "TICKET":
            dip = ottieni_dipendente(username)
            email_ref = (
                (payload.get("email_cliente") or "").strip()
                or (dip or {}).get("email_aziendale")
                or f"{username}@supervisorhq.local"
            )
            nuovo_tk = apri_ticket(
                email_cliente=email_ref,
                problema=payload.get("problema") or payload.get("descrizione") or azione["descrizione"],
                priorita=(payload.get("priorita") or "MEDIA").upper(),
            )
            codice = nuovo_tk.get("codice_ticket") if isinstance(nuovo_tk, dict) else str(nuovo_tk)
            esito = f"Ticket committato e aperto: {codice} (Priorità: {(payload.get('priorita') or 'MEDIA').upper()})"
            stato_finale = "ESEGUITA"

        elif tipo == "EMAIL":
            destinatario = (payload.get("destinatario") or "").strip()
            allegato_nome = (payload.get("allegato_nome") or "").strip()
            allegato_percorso = payload.get("allegato_percorso")

            if allegato_nome and not allegato_percorso:
                allegato_percorso = _cerca_documento_locale(allegato_nome)

            if "@" not in destinatario:
                esito = (
                    f"INDIRIZZO MANCANTE: impossibile inviare l'email "
                    f"(destinatario rilevato: '{destinatario or 'nessuno'}'). Usa 'Modifica' per inserire l'email."
                )
                stato_finale = "ATTENZIONE"
            elif allegato_nome and not allegato_percorso:
                esito = (
                    f"ALLEGATO MANCANTE: il file '{allegato_nome}' non è stato trovato in locale. "
                    "Caricalo nella cartella docs/ o rimuovilo con 'Modifica' prima di inviare."
                )
                stato_finale = "ATTENZIONE"
            else:
                oggetto = payload.get("oggetto") or "Comunicazione da SupervisorHQ"
                corpo = payload.get("corpo") or azione["descrizione"]
                lista_allegati = [_percorso_assoluto_progetto(allegato_percorso)] if allegato_percorso else None
                esito = invia_email(
                    destinatario=destinatario,
                    oggetto=oggetto,
                    corpo=corpo,
                    username=username,
                    allegati=lista_allegati,
                )
                stato_finale = "ESEGUITA"

        elif tipo == "CATALOGO":
            op = (payload.get("azione") or "CREA").upper()
            if op == "CREA":
                nuovo_id = crea_soluzione(
                    payload.get("titolo", "Nuova Soluzione"),
                    payload.get("descrizione", ""),
                    payload.get("prezzo", "€ 0"),
                    payload.get("icona", "🚀"),
                    payload.get("prompt_precompilato", ""),
                )
                esito = f"Soluzione creata a catalogo (ID #{nuovo_id}): {payload.get('titolo')}"
                stato_finale = "ESEGUITA"
            elif op == "AGGIORNA":
                sid = payload.get("soluzione_id")
                if not sid:
                    raise ValueError("ID soluzione mancante per l'aggiornamento.")
                ok = aggiorna_soluzione(
                    int(sid),
                    payload.get("titolo", ""),
                    payload.get("descrizione", ""),
                    payload.get("prezzo", ""),
                    payload.get("icona", "🚀"),
                    payload.get("prompt_precompilato", ""),
                )
                if not ok:
                    raise ValueError(f"Soluzione ID #{sid} non trovata.")
                esito = f"Soluzione ID #{sid} aggiornata sul catalogo."
                stato_finale = "ESEGUITA"
            elif op == "ELIMINA":
                sid = payload.get("soluzione_id")
                if not sid:
                    raise ValueError("ID soluzione mancante per l'eliminazione.")
                ok = elimina_soluzione(int(sid))
                if not ok:
                    raise ValueError(f"Soluzione ID #{sid} non trovata.")
                esito = f"Soluzione ID #{sid} rimossa dal catalogo."
                stato_finale = "ESEGUITA"
            else:
                raise ValueError(f"Operazione catalogo non valida: {op}")

        elif tipo == "FATTURA":
            op = (payload.get("azione") or "EMETTI").upper()
            if op == "EMETTI":
                imp = float(payload.get("importo") or 0)
                if imp <= 0:
                    raise ValueError("Importo non valido per emissione fattura.")
                num = crea_nuova_fattura(imp)
                esito = f"Nuova fattura emessa: {num} (€ {imp:.2f})"
                stato_finale = "ESEGUITA"
            elif op == "PAGA":
                num = (payload.get("numero_fattura") or "").strip()
                if not num:
                    raise ValueError("Numero fattura mancante per registrare il pagamento.")
                esito = gestisci_pagamento(num, str(payload.get("importo") or "0"))
                stato_finale = "ESEGUITA"
            elif op == "AGGIORNA":
                num = (payload.get("numero_fattura") or "").strip()
                if not num:
                    raise ValueError("Numero fattura mancante.")
                ok = aggiorna_fattura(
                    num,
                    float(payload["importo"]) if payload.get("importo") is not None else None,
                    payload.get("stato"),
                )
                if not ok:
                    raise ValueError(f"Fattura {num} non trovata.")
                esito = f"Fattura {num} aggiornata."
                stato_finale = "ESEGUITA"
            elif op == "ELIMINA":
                num = (payload.get("numero_fattura") or "").strip()
                if not num:
                    raise ValueError("Numero fattura mancante.")
                ok = elimina_fattura(num)
                if not ok:
                    raise ValueError(f"Fattura {num} non trovata.")
                esito = f"Fattura {num} eliminata."
                stato_finale = "ESEGUITA"
            else:
                raise ValueError(f"Operazione fattura non valida: {op}")

        else:  # ACTION_ITEM -> notifica reale al responsabile
            resp = payload.get("responsabile") or username
            resp_email = (payload.get("responsabile_email") or "").strip()
            scad = payload.get("scadenza") or "non specificata"

            if "@" in resp_email:
                oggetto = f"[SupervisorHQ] Nuovo compito assegnato: {azione['descrizione'][:60]}"
                corpo = (
                    f"Ciao {resp},\n\n"
                    f"ti è stato assegnato un nuovo compito emerso dal verbale di riunione:\n\n"
                    f"- Attività: {azione['descrizione']}\n"
                    f"- Scadenza: {scad}\n"
                    f"- Assegnato da: {username}\n\n"
                    f"Buon lavoro,\nSupervisorHQ"
                )
                invio = invia_email(
                    destinatario=resp_email,
                    oggetto=oggetto,
                    corpo=corpo,
                    username=username,
                )
                esito = f"Compito assegnato e notificato via email a {resp} ({resp_email}). [{invio}]"
                stato_finale = "ESEGUITA"
            else:
                esito = (
                    f"EMAIL ASSEGNATARIO MANCANTE: '{resp}' non ha un'email collegata in rubrica. "
                    "Usa 'Modifica' per inserire l'email e inviare la notifica."
                )
                stato_finale = "ATTENZIONE"

        aggiorna_stato_azione_verbale(azione_id, stato_finale, esito, eseguito_da=username)
        return {"azione_id": azione_id, "stato": stato_finale, "esito": esito}

    except Exception as e:
        aggiorna_stato_azione_verbale(azione_id, "ERRORE", str(e), eseguito_da=username)
        raise


def verifica_slot_azione_verbale(azione_id: int, username: str) -> dict:
    """Controlla eventuali sovrapposizioni su Google Calendar PRIMA di approvare/calendarizzare."""
    azione = ottieni_azione_verbale(azione_id)
    if not azione:
        raise ValueError(f"Azione #{azione_id} non trovata.")
    if azione["tipo"] != "RIUNIONE":
        raise ValueError("La verifica disponibilità è valida solo per azioni di tipo RIUNIONE.")

    payload = azione["payload"]
    data_ora = payload.get("data_ora_iso")
    if not data_ora:
        return {
            "libero": False,
            "messaggio": "Data/ora mancante. Usa 'Modifica' per inserirla prima di verificare.",
            "alternative": [],
        }

    check = verifica_disponibilita(
        data_ora_iso=data_ora,
        durata_minuti=int(payload.get("durata_minuti", 60)),
        partecipanti=payload.get("partecipanti_email", []),
        username=username,
    )
    if check["libero"]:
        return {
            "libero": True,
            "messaggio": f"✅ Slot libero ({data_ora}). Puoi approvare e calendarizzare.",
            "alternative": [],
        }

    alt = ", ".join(check["alternative"]) or "nessuna alternativa in giornata"
    return {
        "libero": False,
        "messaggio": f"⚠️ Sovrapposizione rilevata su {data_ora}. Alternative libere: {alt}",
        "alternative": check["alternative"],
    }