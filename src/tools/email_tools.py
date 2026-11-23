import base64
from email.mime.text import MIMEText
from googleapiclient.discovery import build

from src.core.google_auth import ottieni_credenziali_utente


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


def invia_email(destinatario: str, oggetto: str, corpo: str, username: str = "admin") -> str:
    """Invia un'email dalla casella Gmail del dipendente specificato."""
    service = _ottieni_servizio_gmail(username)
    messaggio = MIMEText(corpo)
    messaggio["to"] = destinatario
    messaggio["subject"] = oggetto
    raw = base64.urlsafe_b64encode(messaggio.as_bytes()).decode("utf-8")

    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return f"Email inviata con successo a {destinatario}."


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