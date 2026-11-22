import os
import traceback

import ollama
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr

from src.core.security import crea_token, verifica_admin
from src.workflow.graph import compila_grafo_ufficio
from src.tools.calendar_tools import ottieni_prossimi_eventi
from src.tools.billing_tools import ottieni_tutte_le_fatture, crea_nuova_fattura, gestisci_pagamento
from src.tools.email_tools import leggi_email_non_lette
from src.core.database import (
    inizializza_database,
    autentica_dipendente,
    ottieni_tutte_le_soluzioni,
    crea_soluzione,
    aggiorna_soluzione,
    elimina_soluzione,
)
app = FastAPI(
    title="SupervisorHQ API",
    description="Microservizio multi-agente per l'automazione dell'ufficio.",
    version="1.0.0"
)

# Cache in memoria delle ultime email sincronizzate e degli esiti degli agenti
CACHE_EMAIL_INBOX = []
EMAIL_ELABORATE = {}  # { msg_id: {"reparto": ..., "risposta_ai": ..., "stato": ...} }

inizializza_database()

class SoluzioneRequest(BaseModel):
    titolo: str
    descrizione: str
    prezzo: str
    icona: str = "🚀"
    prompt_precompilato: str

print("⚙️ Compilazione Grafo LangGraph in corso...")
ufficio = compila_grafo_ufficio()
print("✅ Ufficio operativo e pronto a ricevere richieste.")

# Cache in memoria delle ultime email sincronizzate per l'Assistente Interno
CACHE_EMAIL_INBOX = []


# ==========================================
# SCHEMI PYDANTIC
# ==========================================
class LoginRequest(BaseModel):
    username: str
    password: str


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


# ==========================================
# 1. ROTTE PUBBLICHE (GUI, AUTH, PORTALE CLIENTI)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


# 1. LOGIN SU DATABASE SQLITE
@app.post("/api/v1/auth/login")
async def login_operatore(req: LoginRequest):
    dipendente = autentica_dipendente(req.username, req.password)
    if not dipendente:
        raise HTTPException(status_code=401, detail="Credenziali non valide.")

    token = crea_token(dipendente["username"], dipendente["ruolo"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "nome": dipendente["nome_completo"],
        "reparto": dipendente["reparto"]
    }


# 2. SOLUZIONI - SOLA VISIONE (Pubblica per Portale Clienti e Dipendenti)
@app.get("/api/v1/soluzioni")
async def get_soluzioni():
    try:
        return {"status": "ok", "dati": ottieni_tutte_le_soluzioni()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore DB soluzioni: {str(e)}")


# 3. SOLUZIONI - CREAZIONE, MODIFICA, ELIMINAZIONE (Solo Dipendenti con JWT)
@app.post("/api/v1/amministrazione/soluzioni")
async def api_crea_soluzione(req: SoluzioneRequest, utente: str = Depends(verifica_admin)):
    nuovo_id = crea_soluzione(req.titolo, req.descrizione, req.prezzo, req.icona, req.prompt_precompilato)
    return {"status": "ok", "id": nuovo_id}


@app.put("/api/v1/amministrazione/soluzioni/{soluzione_id}")
async def api_aggiorna_soluzione(soluzione_id: int, req: SoluzioneRequest, utente: str = Depends(verifica_admin)):
    aggiornata = aggiorna_soluzione(soluzione_id, req.titolo, req.descrizione, req.prezzo, req.icona, req.prompt_precompilato)
    if not aggiornata:
        raise HTTPException(status_code=404, detail="Soluzione non trovata.")
    return {"status": "ok", "messaggio": "Soluzione aggiornata."}


@app.delete("/api/v1/amministrazione/soluzioni/{soluzione_id}")
async def api_elimina_soluzione(soluzione_id: int, utente: str = Depends(verifica_admin)):
    eliminata = elimina_soluzione(soluzione_id)
    if not eliminata:
        raise HTTPException(status_code=404, detail="Soluzione non trovata.")
    return {"status": "ok", "messaggio": "Soluzione eliminata."}


@app.post("/api/v1/pratiche/nuova", response_model=RispostaPratica)
async def smista_nuova_pratica(richiesta: RichiestaPratica):
    pratica_iniziale = {
        "email_in_ingresso": richiesta.testo_email,
        "mittente": richiesta.mittente,
        "storico_conversazione": [f"CLIENTE: {richiesta.testo_email}"],
        "invia_email_finale": True
    }
    config = {"configurable": {"thread_id": richiesta.mittente}}

    try:
        risultato = ufficio.invoke(pratica_iniziale, config=config)
        return RispostaPratica(
            status="COMPLETATA",
            reparto_lavorazione=risultato.get("motivo_assegnazione", "Autonomo"),
            risposta_inviata=risultato.get("risposta_coordinata", "Operazione completata con successo.")
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore LangGraph: {str(e)}")


# ==========================================
# 2. ROTTE AMMINISTRAZIONE (PROTETTE DA JWT)
# ==========================================
@app.get("/api/v1/amministrazione/fatture")
async def get_registro_fatture(utente: str = Depends(verifica_admin)):
    try:
        fatture = ottieni_tutte_le_fatture()
        return {"status": "ok", "dati": fatture}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore SQLite: {str(e)}")


@app.post("/api/v1/amministrazione/fatture/nuova")
async def api_crea_fattura(req: NuovaFatturaRequest, utente: str = Depends(verifica_admin)):
    try:
        numero = crea_nuova_fattura(req.importo)
        return {"status": "ok", "numero_fattura": numero}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/amministrazione/fatture/paga")
async def api_paga_fattura(req: PagamentoRequest, utente: str = Depends(verifica_admin)):
    try:
        esito = gestisci_pagamento(req.numero_fattura, req.importo_pagato)
        return {"status": "ok", "messaggio": esito}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/amministrazione/inbox")
async def get_posta_in_arrivo(utente: str = Depends(verifica_admin)):
    global CACHE_EMAIL_INBOX, EMAIL_ELABORATE
    try:
        # Su Tom (CPU) conviene tenere limite=5 per evitare attese lunghe alla prima sincronizzazione
        email_scaricate = leggi_email_non_lette(limite=5)
        risultati_arricchiti = []

        for email in email_scaricate:
            msg_id = email["id"]

            # Se l'email non è ancora stata letta dagli agenti, la passiamo subito a LangGraph
            if msg_id not in EMAIL_ELABORATE:
                print(f"🤖 [AUTO-LETTURA INBOX] Elaborazione email '{email['oggetto']}' da {email['mittente']}...")
                pratica = {
                    "email_in_ingresso": f"Oggetto: {email['oggetto']}\n\n{email['testo']}",
                    "mittente": email["mittente"],
                    "storico_conversazione": [f"CLIENTE ({email['mittente']}): {email['testo']}"],
                    "invia_email_finale": True  # Metti False se vuoi solo l'analisi senza invio automatico
                }
                config = {"configurable": {"thread_id": f"inbox_{msg_id}"}}

                try:
                    esito = ufficio.invoke(pratica, config=config)
                    EMAIL_ELABORATE[msg_id] = {
                        "stato_ai": "ELABORATA",
                        "reparto_ai": esito.get("motivo_assegnazione", "Autonomo"),
                        "risposta_ai": esito.get("risposta_coordinata", "Elaborazione completata.")
                    }
                except Exception as err:
                    traceback.print_exc()
                    EMAIL_ELABORATE[msg_id] = {
                        "stato_ai": "ERRORE",
                        "reparto_ai": "Errore agente",
                        "risposta_ai": f"Errore durante l'elaborazione: {err}"
                    }

            # Uniamo i dati originali dell'email con il verdetto degli agenti
            email_completa = {**email, **EMAIL_ELABORATE[msg_id]}
            risultati_arricchiti.append(email_completa)

        CACHE_EMAIL_INBOX = risultati_arricchiti
        return {"status": "ok", "dati": CACHE_EMAIL_INBOX}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore Gmail: {str(e)}")


@app.post("/api/v1/amministrazione/chat")
async def chat_assistente_interno(req: ChatInternaRequest, utente: str = Depends(verifica_admin)):
    global CACHE_EMAIL_INBOX
    try:
        print(f"💬 [CHAT - {utente}] Avvio recupero contesto...")

        if not CACHE_EMAIL_INBOX:
            print("   -> Cache vuota, scarico email da Gmail...")
            CACHE_EMAIL_INBOX = leggi_email_non_lette(limite=10)

        if CACHE_EMAIL_INBOX:
            contesto_email = "\n---\n".join([
                f"DA: {e['mittente']}\nOGGETTO: {e['oggetto']}\nTESTO:\n{e['testo']}"
                for e in CACHE_EMAIL_INBOX
            ])
        else:
            contesto_email = "Nessuna email presente in inbox."

        print("   -> Recupero eventi Calendar...")
        contesto_agenda = ottieni_prossimi_eventi()

        print("   -> Recupero fatture SQLite...")
        contesto_fatture = ottieni_tutte_le_fatture()

        print("   -> Recupero catalogo soluzioni SQLite...")
        soluzioni_db = ottieni_tutte_le_soluzioni()
        if soluzioni_db:
            contesto_soluzioni = "\n".join([
                f"- {s['titolo']} ({s['prezzo']}): {s['descrizione']}"
                for s in soluzioni_db
            ])
        else:
            contesto_soluzioni = "Nessuna soluzione presente a catalogo."

        print("   -> Interrogo Qwen...")
        prompt = (
            "Sei l'Assistente AI interno di SupervisorHQ. Rispondi alla domanda del dipendente in modo "
            "conciso, cortese e diretto, basandoti ESCLUSIVAMENTE sui seguenti dati in tempo reale.\n\n"
            f"📦 CATALOGO SOLUZIONI AZIENDALI:\n{contesto_soluzioni}\n\n"
            f"📧 ULTIMA INBOX COMPLETA (Mittente, Oggetto e Corpo):\n{contesto_email}\n\n"
            f"📅 PROSSIMI EVENTI:\n{contesto_agenda}\n\n"
            f"💰 FATTURE A SISTEMA:\n{contesto_fatture}\n\n"
            f"DOMANDA DEL DIPENDENTE: {req.domanda}"
        )

        risp = ollama.chat(
            model="qwen2.5:14b",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_ctx": 8192}
        )

        print("✅ [CHAT] Risposta generata.")
        return {"risposta": risp['message']['content']}

    except Exception as e:
        print(f"❌ [ERRORE CHAT]: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class RispostaEmailRequest(BaseModel):
    mittente: str
    oggetto: str = ""
    testo_email: str


@app.post("/api/v1/amministrazione/inbox/rispondi")
async def rispondi_email_da_inbox(req: RispostaEmailRequest, utente: str = Depends(verifica_admin)):
    """Passa l'email letta dalla inbox direttamente al Supervisore LangGraph per generare e inviare la risposta."""
    pratica = {
        "email_in_ingresso": f"Oggetto: {req.oggetto}\n\n{req.testo_email}",
        "mittente": req.mittente,
        "storico_conversazione": [f"CLIENTE ({req.mittente}): {req.testo_email}"],
        "invia_email_finale": True
    }
    config = {"configurable": {"thread_id": req.mittente}}

    try:
        risultato = ufficio.invoke(pratica, config=config)
        return {
            "status": "ok",
            "reparto": risultato.get("motivo_assegnazione", "Autonomo"),
            "risposta_inviata": risultato.get("risposta_coordinata", "Risposta inviata.")
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Errore invio risposta: {str(e)}")