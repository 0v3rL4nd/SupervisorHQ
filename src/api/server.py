import os
import traceback

import ollama
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

from src.agents.minutes_agent import (
    elabora_verbale,
    esegui_azione_verbale,
    verifica_slot_azione_verbale,
)
from src.core.security import crea_token, verifica_admin
from src.core.google_auth import crea_url_autorizzazione, completa_autorizzazione
from src.core.database import (
    inizializza_database,
    autentica_dipendente,
    ottieni_dipendente,
    ottieni_email_elaborata,
    salva_email_elaborata,
    elimina_email_elaborata,
    ottieni_tutte_le_soluzioni,
    crea_soluzione,
    aggiorna_soluzione,
    elimina_soluzione,
    lista_verbali,
    aggiorna_stato_azione_verbale,
    aggiorna_azione_verbale,
    elimina_verbale,
)
from src.tools.document_parser import estrai_testo_da_bytes
from src.workflow.graph import compila_grafo_ufficio
from src.tools.calendar_tools import ottieni_prossimi_eventi
from src.tools.billing_tools import (
    ottieni_tutte_le_fatture,
    crea_nuova_fattura,
    gestisci_pagamento,
    aggiorna_fattura,
    elimina_fattura,
)
from src.tools.email_tools import (
    leggi_email_non_lette,
    leggi_tutte_le_email,
    segna_email_come_letta,
    elimina_email,
)
from src.tools.ticket_tools import (
    apri_ticket,
    lista_tutti_ticket,
    aggiorna_stato_ticket,
    aggiorna_ticket,
    elimina_ticket,
)

app = FastAPI(
    title="SupervisorHQ API",
    description="Microservizio multi-agente per l'automazione dell'ufficio.",
    version="1.0.0",
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
os.makedirs(DOCS_DIR, exist_ok=True)

if not os.path.isdir(STATIC_DIR):
    raise RuntimeError(f"Cartella static non trovata in: {STATIC_DIR}")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

CACHE_EMAIL_PER_UTENTE: dict[str, list] = {}
inizializza_database()

print("⚙️ Compilazione Grafo LangGraph in corso...")
ufficio = compila_grafo_ufficio()
print("✅ Ufficio operativo e pronto a ricevere richieste.")


# ==========================================
# SCHEMI PYDANTIC
# ==========================================
class LoginRequest(BaseModel):
    username: str
    password: str


class SoluzioneRequest(BaseModel):
    titolo: str
    descrizione: str
    prezzo: str
    icona: str = "🚀"
    prompt_precompilato: str


class RichiestaPratica(BaseModel):
    mittente: EmailStr
    testo_email: str


class RispostaPratica(BaseModel):
    status: str
    reparto_lavorazione: str
    risposta_inviata: str


class NuovaFatturaRequest(BaseModel):
    importo: float


class PagamentoRequest(BaseModel):
    numero_fattura: str
    importo_pagato: str


class ChatInternaRequest(BaseModel):
    domanda: str


class RispostaEmailRequest(BaseModel):
    mittente: str
    oggetto: str = ""
    testo_email: str


class AggiornaStatoTicketRequest(BaseModel):
    stato: str


class AggiornaFatturaRequest(BaseModel):
    importo: float | None = None
    stato: str | None = None


class CreaTicketAdminRequest(BaseModel):
    email_cliente: EmailStr
    problema: str
    priorita: str = "MEDIA"


class AggiornaTicketRequest(BaseModel):
    problema: str | None = None
    priorita: str | None = None
    stato: str | None = None


class VerbaleTestoRequest(BaseModel):
    testo: str


class AggiornaAzioneVerbaleRequest(BaseModel):
    descrizione: str | None = None
    payload: dict | None = None

def _utente_e_admin(username: str) -> bool:
    dip = ottieni_dipendente(username)
    return bool(dip and (dip.get("ruolo") == "ADMIN" or username == "admin"))

# ==========================================
# 1. ROTTE PUBBLICHE (GUI, AUTH, PORTALE CLIENTI)
# ==========================================
@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    index_path = os.path.join(STATIC_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/verbali", response_class=HTMLResponse)
def serve_verbali_workspace():
    verbali_path = os.path.join(STATIC_DIR, "verbali.html")
    with open(verbali_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/v1/auth/login")
def login_operatore(req: LoginRequest):
    dipendente = autentica_dipendente(req.username, req.password)
    if not dipendente:
        raise HTTPException(status_code=401, detail="Credenziali non valide.")

    token = crea_token(dipendente["username"], dipendente["ruolo"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "nome": dipendente["nome_completo"],
        "reparto": dipendente["reparto"],
    }


@app.get("/api/v1/auth/google/status")
def stato_google_utente(utente: str = Depends(verifica_admin)):
    dip = ottieni_dipendente(utente)
    if not dip:
        raise HTTPException(status_code=404, detail="Dipendente non trovato.")
    return {
        "collegato": bool(dip.get("google_collegato")),
        "email_aziendale": dip.get("email_aziendale"),
    }


@app.get("/api/v1/auth/google/connect")
def avvia_collegamento_google(utente: str = Depends(verifica_admin)):
    try:
        url = crea_url_autorizzazione(utente)
        return {"auth_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore avvio OAuth Google: {str(e)}")


@app.get("/api/v1/auth/google/callback")
def callback_google(code: str, state: str):
    """Callback invocato da Google dopo il consenso del dipendente."""
    try:
        completa_autorizzazione(code=code, username=state)
        return RedirectResponse(url="/?google_connected=1")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore callback Google: {str(e)}")


@app.get("/api/v1/soluzioni")
def get_soluzioni():
    try:
        return {"status": "ok", "dati": ottieni_tutte_le_soluzioni()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore DB soluzioni: {str(e)}")


@app.post("/api/v1/pratiche/nuova", response_model=RispostaPratica)
def smista_nuova_pratica(richiesta: RichiestaPratica):
    pratica_iniziale = {
        "email_in_ingresso": richiesta.testo_email,
        "mittente": richiesta.mittente,
        "storico_conversazione": [f"CLIENTE: {richiesta.testo_email}"],
        "invia_email_finale": True,
    }
    config = {"configurable": {"thread_id": richiesta.mittente}}

    try:
        risultato = ufficio.invoke(pratica_iniziale, config=config)
        return RispostaPratica(
            status="COMPLETATA",
            reparto_lavorazione=risultato.get("motivo_assegnazione", "Autonomo"),
            risposta_inviata=risultato.get("risposta_coordinata", "Operazione completata con successo."),
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore LangGraph: {str(e)}")


# ==========================================
# 2. ROTTE AMMINISTRAZIONE (PROTETTE DA JWT)
# ==========================================

# --- SOLUZIONI (CRUD) ---
@app.post("/api/v1/amministrazione/soluzioni")
def api_crea_soluzione(req: SoluzioneRequest, utente: str = Depends(verifica_admin)):
    nuovo_id = crea_soluzione(req.titolo, req.descrizione, req.prezzo, req.icona, req.prompt_precompilato)
    return {"status": "ok", "id": nuovo_id}


@app.put("/api/v1/amministrazione/soluzioni/{soluzione_id}")
def api_aggiorna_soluzione(soluzione_id: int, req: SoluzioneRequest, utente: str = Depends(verifica_admin)):
    aggiornata = aggiorna_soluzione(
        soluzione_id, req.titolo, req.descrizione, req.prezzo, req.icona, req.prompt_precompilato
    )
    if not aggiornata:
        raise HTTPException(status_code=404, detail="Soluzione non trovata.")
    return {"status": "ok", "messaggio": "Soluzione aggiornata."}


@app.delete("/api/v1/amministrazione/soluzioni/{soluzione_id}")
def api_elimina_soluzione(soluzione_id: int, utente: str = Depends(verifica_admin)):
    eliminata = elimina_soluzione(soluzione_id)
    if not eliminata:
        raise HTTPException(status_code=404, detail="Soluzione non trovata.")
    return {"status": "ok", "messaggio": "Soluzione eliminata."}


# --- FATTURE ---
@app.get("/api/v1/amministrazione/fatture")
def get_registro_fatture(utente: str = Depends(verifica_admin)):
    try:
        fatture = ottieni_tutte_le_fatture()
        return {"status": "ok", "dati": fatture}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore SQLite: {str(e)}")


@app.post("/api/v1/amministrazione/fatture/nuova")
def api_crea_fattura(req: NuovaFatturaRequest, utente: str = Depends(verifica_admin)):
    try:
        numero = crea_nuova_fattura(req.importo)
        return {"status": "ok", "numero_fattura": numero}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/amministrazione/fatture/paga")
def api_paga_fattura(req: PagamentoRequest, utente: str = Depends(verifica_admin)):
    try:
        esito = gestisci_pagamento(req.numero_fattura, req.importo_pagato)
        return {"status": "ok", "messaggio": esito}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v1/amministrazione/fatture/{numero_fattura:path}")
def api_aggiorna_fattura(
    numero_fattura: str,
    req: AggiornaFatturaRequest,
    utente: str = Depends(verifica_admin),
):
    try:
        aggiornata = aggiorna_fattura(numero_fattura, req.importo, req.stato)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not aggiornata:
        raise HTTPException(status_code=404, detail=f"Fattura {numero_fattura} non trovata.")
    return {"status": "ok", "messaggio": f"Fattura {numero_fattura} aggiornata."}


@app.delete("/api/v1/amministrazione/fatture/{numero_fattura:path}")
def api_elimina_fattura(numero_fattura: str, utente: str = Depends(verifica_admin)):
    eliminata = elimina_fattura(numero_fattura)
    if not eliminata:
        raise HTTPException(status_code=404, detail=f"Fattura {numero_fattura} non trovata.")
    return {"status": "ok", "messaggio": f"Fattura {numero_fattura} eliminata."}


# --- TICKET ASSISTENZA TECNICA ---
@app.get("/api/v1/amministrazione/ticket")
def get_ticket_admin(utente: str = Depends(verifica_admin)):
    try:
        return {"status": "ok", "dati": lista_tutti_ticket()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore DB ticket: {str(e)}")


@app.put("/api/v1/amministrazione/ticket/{codice_ticket}/stato")
def put_stato_ticket(
    codice_ticket: str,
    req: AggiornaStatoTicketRequest,
    utente: str = Depends(verifica_admin),
):
    try:
        aggiornato = aggiorna_stato_ticket(codice_ticket, req.stato)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore aggiornamento ticket: {str(e)}")

    if not aggiornato:
        raise HTTPException(status_code=404, detail=f"Ticket {codice_ticket} non trovato.")

    return {"status": "ok", "messaggio": f"Ticket {codice_ticket} aggiornato a {req.stato.upper()}."}


@app.post("/api/v1/amministrazione/ticket")
def api_crea_ticket_admin(req: CreaTicketAdminRequest, utente: str = Depends(verifica_admin)):
    try:
        nuovo = apri_ticket(req.email_cliente, req.problema, req.priorita)
        return {"status": "ok", "dati": nuovo}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore creazione ticket: {str(e)}")


@app.put("/api/v1/amministrazione/ticket/{codice_ticket}")
def api_aggiorna_ticket(
    codice_ticket: str,
    req: AggiornaTicketRequest,
    utente: str = Depends(verifica_admin),
):
    try:
        aggiornato = aggiorna_ticket(codice_ticket, req.problema, req.priorita, req.stato)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not aggiornato:
        raise HTTPException(status_code=404, detail=f"Ticket {codice_ticket} non trovato.")
    return {"status": "ok", "messaggio": f"Ticket {codice_ticket} aggiornato."}


@app.delete("/api/v1/amministrazione/ticket/{codice_ticket}")
def api_elimina_ticket(codice_ticket: str, utente: str = Depends(verifica_admin)):
    eliminato = elimina_ticket(codice_ticket)
    if not eliminato:
        raise HTTPException(status_code=404, detail=f"Ticket {codice_ticket} non trovato.")
    return {"status": "ok", "messaggio": f"Ticket {codice_ticket} eliminato."}


# --- INBOX GMAIL & RISPOSTA AI ---
@app.get("/api/v1/amministrazione/inbox")
def get_posta_in_arrivo(utente: str = Depends(verifica_admin)):
    try:
        email_scaricate = leggi_tutte_le_email(username=utente, limite=10)
        risultati_arricchiti = []

        for email in email_scaricate:
            msg_id = email["id"]
            da_elaborare = email.get("in_arrivo", False) and email.get("non_letta", False)

            if not da_elaborare:
                esito_ai = {
                    "stato_ai": "SOLO_VISIONE",
                    "reparto_ai": "Inviata / Già letta" if not email.get("in_arrivo") else "Già letta",
                    "risposta_ai": "Visualizzata solo in lettura (nessuna risposta automatica).",
                }
            else:
                elaborata = ottieni_email_elaborata(utente, msg_id)
                if not elaborata:
                    print(f"🤖 [AUTO-LETTURA INBOX - {utente}] Elaborazione '{email['oggetto']}' da {email['mittente']}...")
                    pratica = {
                        "email_in_ingresso": f"Oggetto: {email['oggetto']}\n\n{email['testo']}",
                        "mittente": email["mittente"],
                        "storico_conversazione": [f"CLIENTE ({email['mittente']}): {email['testo']}"],
                        "invia_email_finale": True,
                    }
                    config = {"configurable": {"thread_id": f"inbox_{utente}_{msg_id}"}}

                    try:
                        esito = ufficio.invoke(pratica, config=config)
                        segna_email_come_letta(msg_id, username=utente)
                        email["non_letta"] = False
                        elaborata = {
                            "stato_ai": "ELABORATA",
                            "reparto_ai": esito.get("motivo_assegnazione", "Autonomo"),
                            "risposta_ai": esito.get("risposta_coordinata", "Elaborazione completata."),
                        }
                    except Exception as err:
                        traceback.print_exc()
                        elaborata = {
                            "stato_ai": "ERRORE",
                            "reparto_ai": "Errore agente",
                            "risposta_ai": f"Errore durante l'elaborazione: {err}",
                        }

                    salva_email_elaborata(
                        utente,
                        msg_id,
                        elaborata["stato_ai"],
                        elaborata["reparto_ai"],
                        elaborata["risposta_ai"],
                    )

                esito_ai = elaborata

            risultati_arricchiti.append({**email, **esito_ai})

        CACHE_EMAIL_PER_UTENTE[utente] = risultati_arricchiti
        return {"status": "ok", "dati": risultati_arricchiti}

    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore Gmail: {str(e)}")


@app.delete("/api/v1/amministrazione/inbox/{msg_id}")
def api_elimina_email(msg_id: str, utente: str = Depends(verifica_admin)):
    try:
        elimina_email(msg_id, username=utente)
        elimina_email_elaborata(utente, msg_id)
        return {"status": "ok", "messaggio": "Email spostata nel cestino."}
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore eliminazione email: {str(e)}")


# --- CHAT ASSISTENTE INTERNO AI ---
@app.post("/api/v1/amministrazione/chat")
def chat_assistente_interno(req: ChatInternaRequest, utente: str = Depends(verifica_admin)):
    try:
        print(f"💬 [CHAT - {utente}] Avvio recupero contesto...")

        cache_utente = CACHE_EMAIL_PER_UTENTE.get(utente, [])
        if not cache_utente:
            try:
                cache_utente = leggi_email_non_lette(username=utente, limite=10)
                CACHE_EMAIL_PER_UTENTE[utente] = cache_utente
            except PermissionError:
                cache_utente = []

        if cache_utente:
            contesto_email = "\n---\n".join([
                f"DA: {e['mittente']}\nOGGETTO: {e['oggetto']}\nTESTO:\n{e['testo']}"
                for e in cache_utente
            ])
        else:
            contesto_email = "Nessuna email disponibile (o account Google non ancora collegato)."

        try:
            contesto_agenda = ottieni_prossimi_eventi(username=utente)
        except PermissionError:
            contesto_agenda = "Calendario non disponibile (account Google non collegato)."

        contesto_fatture = ottieni_tutte_le_fatture()

        soluzioni_db = ottieni_tutte_le_soluzioni()
        contesto_soluzioni = "\n".join([
            f"- {s['titolo']} ({s['prezzo']}): {s['descrizione']}"
            for s in soluzioni_db
        ]) if soluzioni_db else "Nessuna soluzione presente a catalogo."

        ticket_db = lista_tutti_ticket()
        contesto_ticket = "\n".join([
            f"- {t['codice_ticket']} | Stato: {t['stato']} | Priorità: {t['priorita']} | Cliente: {t['email_cliente']} | Problema: {t['problema']}"
            for t in ticket_db
        ]) if ticket_db else "Nessun ticket di assistenza presente."

        prompt = (
            "Sei l'Assistente AI interno di SupervisorHQ. Rispondi alla domanda del dipendente in modo "
            "conciso, cortese e diretto, basandoti ESCLUSIVAMENTE sui seguenti dati in tempo reale.\n\n"
            f"📦 CATALOGO SOLUZIONI AZIENDALI:\n{contesto_soluzioni}\n\n"
            f"📧 ULTIMA INBOX COMPLETA (Mittente, Oggetto e Corpo):\n{contesto_email}\n\n"
            f"📅 PROSSIMI EVENTI:\n{contesto_agenda}\n\n"
            f"💰 FATTURE A SISTEMA:\n{contesto_fatture}\n\n"
            f"🛠️ TICKET ASSISTENZA TECNICA:\n{contesto_ticket}\n\n"
            f"DOMANDA DEL DIPENDENTE: {req.domanda}"
        )

        risp = ollama.chat(
            model="qwen2.5:14b",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_ctx": 8192},
        )

        return {"risposta": risp["message"]["content"]}

    except Exception as e:
        print(f"❌ [ERRORE CHAT]: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# --- VERBALI DI RIUNIONE (HUMAN-IN-THE-LOOP) ---
@app.get("/api/v1/amministrazione/verbali")
def api_lista_verbali(utente: str = Depends(verifica_admin)):
    try:
        return {"status": "ok", "dati": lista_verbali(username=utente, is_admin=_utente_e_admin(utente))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore lettura verbali: {str(e)}")


@app.post("/api/v1/amministrazione/verbali/azioni/{azione_id}/approva")
def api_approva_azione_verbale(azione_id: int, utente: str = Depends(verifica_admin)):
    try:
        res = esegui_azione_verbale(azione_id, username=utente, is_admin=_utente_e_admin(utente))
        return {"status": "ok", "dati": res}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore esecuzione azione: {str(e)}")

@app.post("/api/v1/amministrazione/verbali/testo")
def api_verbale_da_testo(req: VerbaleTestoRequest, utente: str = Depends(verifica_admin)):
    if not req.testo.strip():
        raise HTTPException(status_code=400, detail="Il testo del verbale è vuoto.")
    try:
        risultato = elabora_verbale(req.testo.strip(), username=utente, fonte="TESTO")
        return {"status": "ok", "dati": risultato}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore analisi verbale: {str(e)}")


@app.post("/api/v1/amministrazione/verbali/upload")
async def api_verbale_da_file(file: UploadFile = File(...), utente: str = Depends(verifica_admin)):
    try:
        contenuto = await file.read()
        testo = await run_in_threadpool(estrai_testo_da_bytes, contenuto, file.filename or "verbale.txt")
        if not testo:
            raise HTTPException(status_code=400, detail="Impossibile estrarre testo dal file caricato.")
        risultato = await run_in_threadpool(elabora_verbale, testo, utente, f"FILE:{file.filename}")
        return {"status": "ok", "dati": risultato}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore elaborazione file: {str(e)}")


@app.post("/api/v1/amministrazione/verbali/azioni/{azione_id}/approva")
def api_approva_azione_verbale(azione_id: int, utente: str = Depends(verifica_admin)):
    try:
        res = esegui_azione_verbale(azione_id, username=utente)
        return {"status": "ok", "dati": res}
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore esecuzione azione: {str(e)}")


@app.post("/api/v1/amministrazione/verbali/azioni/{azione_id}/rifiuta")
def api_rifiuta_azione_verbale(azione_id: int, utente: str = Depends(verifica_admin)):
    ok = aggiorna_stato_azione_verbale(azione_id, "RIFIUTATA", f"Rifiutata da {utente}")
    if not ok:
        raise HTTPException(status_code=404, detail="Azione non trovata.")
    return {"status": "ok", "messaggio": "Azione rifiutata."}


@app.put("/api/v1/amministrazione/verbali/azioni/{azione_id}")
def api_aggiorna_azione_verbale(
    azione_id: int,
    req: AggiornaAzioneVerbaleRequest,
    utente: str = Depends(verifica_admin),
):
    ok = aggiorna_azione_verbale(azione_id, req.descrizione, req.payload)
    if not ok:
        raise HTTPException(status_code=404, detail="Azione non trovata.")
    return {"status": "ok", "messaggio": "Azione aggiornata e riportata in attesa di conferma."}


@app.get("/api/v1/amministrazione/verbali/azioni/{azione_id}/verifica-calendar")
def api_verifica_calendar_azione(azione_id: int, utente: str = Depends(verifica_admin)):
    try:
        res = verifica_slot_azione_verbale(azione_id, username=utente)
        return {"status": "ok", "dati": res}
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore verifica calendario: {str(e)}")


@app.delete("/api/v1/amministrazione/verbali/{verbale_id}")
def api_elimina_verbale(verbale_id: int, utente: str = Depends(verifica_admin)):
    ok = elimina_verbale(verbale_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Verbale non trovato.")
    return {"status": "ok", "messaggio": f"Verbale #{verbale_id} eliminato."}

# --- ARCHIVIO DOCUMENTI AZIENDALI (cartella docs/) ---
@app.get("/api/v1/amministrazione/documenti")
def api_lista_documenti(utente: str = Depends(verifica_admin)):
    files = []
    for nome in sorted(os.listdir(DOCS_DIR)):
        full = os.path.join(DOCS_DIR, nome)
        if os.path.isfile(full):
            stat = os.stat(full)
            files.append({
                "nome": nome,
                "dimensione_kb": round(stat.st_size / 1024, 1),
            })
    return {"status": "ok", "dati": files}


@app.post("/api/v1/amministrazione/documenti/upload")
async def api_upload_documento(file: UploadFile = File(...), utente: str = Depends(verifica_admin)):
    nome_sicuro = os.path.basename(file.filename or "").strip()
    if not nome_sicuro:
        raise HTTPException(status_code=400, detail="Nome file non valido.")
    contenuto = await file.read()
    dest = os.path.join(DOCS_DIR, nome_sicuro)
    with open(dest, "wb") as f:
        f.write(contenuto)
    return {"status": "ok", "nome": nome_sicuro, "messaggio": f"File '{nome_sicuro}' caricato in docs/."}


@app.delete("/api/v1/amministrazione/documenti/{nome_file}")
def api_elimina_documento(nome_file: str, utente: str = Depends(verifica_admin)):
    nome_sicuro = os.path.basename(nome_file)
    target = os.path.join(DOCS_DIR, nome_sicuro)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="Documento non trovato.")
    os.remove(target)
    return {"status": "ok", "messaggio": f"File '{nome_sicuro}' eliminato."}