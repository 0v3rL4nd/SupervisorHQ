import base64
import mimetypes
import os
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from src.core.database import registra_evento_sicurezza
from src.core.google_auth import ottieni_credenziali_utente
from src.core.security_guard import ispeziona_output_dlp

# Cartella whitelist consentita per gli allegati in uscita
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS_DIR = os.path.realpath(os.path.join(BASE_DIR, "docs"))
os.makedirs(DOCS_DIR, exist_ok=True)


# ==========================================
# SANDBOX FILESYSTEM PER ALLEGATI (docs/)
# ==========================================
def risolvi_percorso_sicuro_docs(percorso_o_nome: str) -> str | None:
    """
    Risolve un percorso verificando che punti a un file realmente dentro docs/.
    Blocca Path Traversal (../), symlink esterni e file sensibili nella root.
    """
    if not percorso_o_nome or not percorso_o_nome.strip():
        return None

    candidato = percorso_o_nome.strip()
    target = candidato if os.path.isabs(candidato) else os.path.join(DOCS_DIR, candidato)
    target_real = os.path.realpath(target)

    # Verifica che il percorso canonico rimanga strettamente dentro DOCS_DIR
    try:
        dentro_docs = os.path.commonpath([DOCS_DIR, target_real]) == DOCS_DIR
    except ValueError:
        dentro_docs = False

    if not dentro_docs or target_real == DOCS_DIR:
        registra_evento_sicurezza(
            modulo="SANDBOX",
            livello_rischio="ALTO",
            azione="BLOCCATO",
            dettaglio=f"Tentativo di accesso file fuori sandbox docs/: '{percorso_o_nome}'",
            contesto="email_attachments_sandbox",
        )
        return None

    if not os.path.isfile(target_real):
        return None

    return target_real


def cerca_allegato_in_docs(nome_richiesto: str) -> str | None:
    """Cerca un allegato esclusivamente all'interno di docs/ (esatto o per sottostringa sicura)."""
    if not nome_richiesto or not nome_richiesto.strip():
        return None

    # Rifiuta subito tentativi con separatori di directory o traversal
    if "/" in nome_richiesto or "\\" in nome_richiesto or ".." in nome_richiesto:
        return risolvi_percorso_sicuro_docs(nome_richiesto)

    # 1. Match diretto
    diretto = risolvi_percorso_sicuro_docs(nome_richiesto)
    if diretto:
        return diretto

    # 2. Match case-insensitive tra i soli file in docs/
    needle = nome_richiesto.strip().lower()
    for fname in sorted(os.listdir(DOCS_DIR)):
        if needle in fname.lower():
            return risolvi_percorso_sicuro_docs(fname)

    return None


# ==========================================
# CLIENT GMAIL MULTI-UTENTE
# ==========================================
def _ottieni_servizio_gmail(username: str = "admin"):
    creds = ottieni_credenziali_utente(username)
    return build("gmail", "v1", credentials=creds)


def _estrai_testo_email(payload: dict, snippet: str = "") -> str:
    """Estrae il corpo testuale (text/plain) dal payload Gmail, con fallback sullo snippet."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace").strip()

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            data = part["body"]["data"]
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace").strip()

    return snippet


def leggi_tutte_le_email(username: str = "admin", limite: int = 10) -> list[dict]:
    """Scarica le ultime email dell'utente specificato marcando quelle in arrivo e non lette."""
    service = _ottieni_servizio_gmail(username)
    risultati = service.users().messages().list(userId="me", maxResults=limite).execute()
    messaggi = risultati.get("messages", [])
    email_lista = []

    for msg in messaggi:
        dettaglio = service.users().messages().get(
            userId="me", id=msg["id"], format="full"
        ).execute()

        labels = dettaglio.get("labelIds", [])
        payload = dettaglio.get("payload", {})
        headers = payload.get("headers", [])
        mittente = next((h["value"] for h in headers if h["name"].lower() == "from"), "Sconosciuto")
        oggetto = next((h["value"] for h in headers if h["name"].lower() == "subject"), "(Senza oggetto)")
        testo = _estrai_testo_email(payload, dettaglio.get("snippet", ""))

        email_lista.append({
            "id": msg["id"],
            "mittente": mittente,
            "oggetto": oggetto,
            "testo": testo,
            "in_arrivo": ("INBOX" in labels) and ("SENT" not in labels),
            "non_letta": "UNREAD" in labels,
        })

    return email_lista


def leggi_email_non_lette(username: str = "admin", limite: int = 5) -> list[dict]:
    """Scarica solo le email in arrivo non ancora lette dell'utente."""
    tutte = leggi_tutte_le_email(username=username, limite=limite * 2)
    return [e for e in tutte if e["in_arrivo"] and e["non_letta"]][:limite]


def invia_email(
    destinatario: str,
    oggetto: str,
    corpo: str,
    username: str = "admin",
    allegati: list[str] | None = None,
) -> str:
    """
    Invia un'email via Gmail applicando:
    1. Output DLP fail-closed su oggetto e corpo (prima di contattare Gmail).
    2. Sandbox rigorosa sugli allegati (ammessi solo file dentro docs/).
    """
    # 1. Output DLP (fail-fast prima di aprire la connessione Gmail)
    check_dlp = ispeziona_output_dlp(f"{oggetto}\n\n{corpo}", destinatario=destinatario)
    if not check_dlp["sicuro"]:
        raise PermissionError(
            f"🛡️ [OUTPUT DLP - INVIO BLOCCATO] Rilevati dati sensibili in uscita verso '{destinatario}': "
            f"{', '.join(check_dlp['violazioni'])}."
        )

    # 2. Validazione sandbox su tutti gli allegati richiesti
    allegati_sicuri: list[str] = []
    if allegati:
        for path in allegati:
            if not path:
                continue
            path_verificato = risolvi_percorso_sicuro_docs(path)
            if not path_verificato:
                raise PermissionError(
                    f"🛡️ [SANDBOX - ALLEGATO BLOCCATO] Il file '{path}' non è autorizzato o è fuori dalla cartella docs/."
                )
            allegati_sicuri.append(path_verificato)

    service = _ottieni_servizio_gmail(username)

    if allegati_sicuri:
        msg = MIMEMultipart()
        msg.attach(MIMEText(corpo, "plain", "utf-8"))
        for path in allegati_sicuri:
            ctype, _ = mimetypes.guess_type(path)
            maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
            with open(path, "rb") as f:
                part = MIMEBase(maintype, subtype)
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=os.path.basename(path),
            )
            msg.attach(part)
    else:
        msg = MIMEText(corpo, "plain", "utf-8")

    msg["to"] = destinatario
    msg["subject"] = oggetto

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    inviata = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    extra = f" con {len(allegati_sicuri)} allegato/i" if allegati_sicuri else ""
    return f"Email inviata{extra} (ID: {inviata.get('id')})"


def segna_email_come_letta(msg_id: str, username: str = "admin") -> bool:
    """Rimuove l'etichetta UNREAD su Gmail per evitare doppie elaborazioni."""
    service = _ottieni_servizio_gmail(username)
    service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()
    return True


def elimina_email(msg_id: str, username: str = "admin") -> bool:
    """Sposta l'email nel cestino di Gmail."""
    service = _ottieni_servizio_gmail(username)
    service.users().messages().trash(userId="me", id=msg_id).execute()
    return True