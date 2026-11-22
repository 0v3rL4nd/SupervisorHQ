import os
import base64
import re
import mimetypes
from email.message import EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# --- CONFIGURAZIONE PERCORSI ---
CURRENT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CREDENTIALS_PATH = os.path.join(CURRENT_DIR, 'credentials.json')
TOKEN_PATH = os.path.join(CURRENT_DIR, 'token_gmail.json')

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

EMAIL_AZIENDALE = "provaaa6767@gmail.com"

PAROLE_CHIAVE_OGGETTO = ["richiesta", "informazioni", "preventivo", "assistenza", "fattura"]


def autentica_gmail():
    """Gestisce il login Google. Apre il browser se il token è mancante o scaduto."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(f"Impossibile trovare {CREDENTIALS_PATH}. Scaricalo da Google Cloud.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    profilo = service.users().getProfile(userId='me').execute()
    print(f"📧 [GMAIL ATTIVA]: {profilo.get('emailAddress')}")
    return service


def invia_email(destinatario: str, oggetto: str, corpo: str, allegato_path: str = None):
    """Invia un'email testuale dall'account autenticato, opzionalmente con un file allegato."""
    print(f"📤 [INVIA_EMAIL] Da: {EMAIL_AZIENDALE} -> A: {destinatario} | Oggetto: {oggetto}")
    try:
        service = autentica_gmail()
        message = EmailMessage()
        message.set_content(corpo)
        message['From'] = EMAIL_AZIENDALE
        message['To'] = destinatario
        message['Subject'] = oggetto

        if allegato_path and os.path.exists(allegato_path):
            ctype, encoding = mimetypes.guess_type(allegato_path)
            if ctype is None or encoding is not None:
                ctype = 'application/octet-stream'
            maintype, subtype = ctype.split('/', 1)

            with open(allegato_path, 'rb') as f:
                dati_file = f.read()

            message.add_attachment(
                dati_file,
                maintype=maintype,
                subtype=subtype,
                filename=os.path.basename(allegato_path)
            )

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_message = service.users().messages().send(
            userId="me",
            body={'raw': encoded_message}
        ).execute()

        if allegato_path and os.path.exists(allegato_path):
            os.remove(allegato_path)

        print(f"✅ [INVIA_EMAIL] Inviata con successo! ID: {send_message['id']}")
        return f"Email inviata con successo! ID: {send_message['id']}"
    except Exception as e:
        print(f"❌ [INVIA_EMAIL ERRORE]: {e}")
        return f"Errore durante l'invio dell'email: {e}"

def _decodifica_b64(data_b64: str) -> str:
    data_b64 += "=" * ((4 - len(data_b64) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(data_b64).decode('utf-8', errors='replace')
    except Exception as e:
        return f"[Errore di decodifica: {e}]"


def _estrai_corpo_ricorsivo(payload: dict) -> str:
    """Estrae il testo plain anche da email multipart annidate."""
    mime_type = payload.get('mimeType', '')
    body_data = payload.get('body', {}).get('data')

    if mime_type == 'text/plain' and body_data:
        return _decodifica_b64(body_data)

    if 'parts' in payload:
        for part in payload['parts']:
            testo = _estrai_corpo_ricorsivo(part)
            if testo:
                return testo

    # Fallback se l'email ha solo un body diretto senza parts
    if body_data:
        return _decodifica_b64(body_data)

    return ""

def leggi_email_non_lette(limite: int = 10) -> list[dict]:
    """Legge solo le email in Posta in Arrivo il cui oggetto contiene le parole chiave consentite."""
    servizio = autentica_gmail()

    # Costruisce la query Gmail: es. subject:(richiesta OR informazioni)
    query_filtro = f"subject:({' OR '.join(PAROLE_CHIAVE_OGGETTO)})"

    risultati = servizio.users().messages().list(
        userId='me',
        labelIds=['INBOX'],
        q=query_filtro,
        maxResults=limite
    ).execute()
    messaggi = risultati.get('messages', [])

    email_trovate = []

    for msg in messaggi:
        msg_id = msg['id']
        messaggio_completo = servizio.users().messages().get(
            userId='me', id=msg_id, format='full'
        ).execute()

        headers = messaggio_completo['payload'].get('headers', [])
        oggetto = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'Nessun Oggetto')

        mittente_raw = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Sconosciuto')
        mittente_pulito = re.findall(r'<([^>]+)>', mittente_raw)
        mittente = mittente_pulito[0] if mittente_pulito else mittente_raw

        corpo = _estrai_corpo_ricorsivo(messaggio_completo['payload'])

        email_trovate.append({
            "id": msg_id,
            "mittente": mittente,
            "oggetto": oggetto,
            "testo": corpo.strip()
        })

    return email_trovate