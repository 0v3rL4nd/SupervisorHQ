import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from src.core.database import ottieni_dipendente, aggiorna_google_dipendente

# Evita errori se Google restituisce scope extra già concessi in precedenza
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
TOKENS_DIR = os.path.join(BASE_DIR, "tokens")
REDIRECT_URI = "http://127.0.0.1:8000/api/v1/auth/google/callback"

os.makedirs(TOKENS_DIR, exist_ok=True)

# Conserva il code_verifier PKCE tra /connect e /callback
_PKCE_VERIFIERS: dict[str, str] = {}


def _percorso_token(username: str) -> str:
    safe_user = "".join(c for c in username if c.isalnum() or c in ("_", "-")).lower()
    return os.path.join(TOKENS_DIR, f"{safe_user}_token.json")


def crea_url_autorizzazione(username: str) -> str:
    """Genera l'URL OAuth2 di Google salvando il code_verifier PKCE per la callback."""
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=username,
    )
    if flow.code_verifier:
        _PKCE_VERIFIERS[username] = flow.code_verifier
    return auth_url


def completa_autorizzazione(code: str, username: str) -> str:
    """Scambia il codice OAuth2 usando il code_verifier salvato e registra il token del dipendente."""
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    verifier = _PKCE_VERIFIERS.pop(username, None)
    if verifier:
        flow.code_verifier = verifier

    flow.fetch_token(code=code)
    creds = flow.credentials

    token_path = _percorso_token(username)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    gmail_service = build("gmail", "v1", credentials=creds)
    profilo = gmail_service.users().getProfile(userId="me").execute()
    email_reale = profilo.get("emailAddress")

    aggiorna_google_dipendente(username, token_path, email_reale)
    return email_reale


def ottieni_credenziali_utente(username: str) -> Credentials:
    """Carica e aggiorna automaticamente le credenziali Google del singolo dipendente."""
    dip = ottieni_dipendente(username)
    if not dip or not dip.get("google_token_path"):
        raise PermissionError(
            f"L'utente '{username}' non ha ancora collegato il proprio account Google."
        )

    token_path = dip["google_token_path"]
    if not os.path.exists(token_path):
        raise PermissionError(
            f"Token Google mancante per '{username}'. Ripeti il collegamento dalla dashboard."
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds