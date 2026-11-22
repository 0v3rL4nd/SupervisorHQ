import os
import re
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# --- CONFIGURAZIONE PERCORSI (root del progetto, allineata a email_tools.py) ---
CURRENT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CREDENTIALS_PATH = os.path.join(CURRENT_DIR, 'credentials.json')
TOKEN_CALENDAR_PATH = os.path.join(CURRENT_DIR, 'token_calendar.json')

SCOPES = ['https://www.googleapis.com/auth/calendar.events']


def autentica_calendar():
    """Gestisce l'autenticazione OAuth2 e restituisce il servizio Google Calendar."""
    creds = None
    if os.path.exists(TOKEN_CALENDAR_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_CALENDAR_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(f"Impossibile trovare {CREDENTIALS_PATH}.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_CALENDAR_PATH, 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)


def crea_evento_calendario(
    titolo: str,
    data_inizio: str,
    ore_durata: int = 1,
    descrizione: str = "",
    intervallo_giorni=None,
    numero_ripetizioni=None,
    partecipanti=None
) -> str:
    """Crea un evento sul Google Calendar principale e invia gli inviti ai partecipanti."""
    try:
        service = autentica_calendar()

        inizio_dt = datetime.strptime(data_inizio, '%Y-%m-%d %H:%M')
        ore_pulite = int(re.sub(r'\D', '', str(ore_durata))) if str(ore_durata).strip() else 1
        fine_dt = inizio_dt + timedelta(hours=ore_pulite)

        evento = {
            'summary': titolo,
            'description': descrizione,
            'start': {'dateTime': inizio_dt.isoformat(), 'timeZone': 'Europe/Rome'},
            'end': {'dateTime': fine_dt.isoformat(), 'timeZone': 'Europe/Rome'},
        }

        if partecipanti and isinstance(partecipanti, list):
            evento['attendees'] = [{'email': email} for email in partecipanti]

        if intervallo_giorni and numero_ripetizioni:
            str_intervallo = re.sub(r'\D', '', str(intervallo_giorni))
            str_ripetizioni = re.sub(r'\D', '', str(numero_ripetizioni))

            if str_intervallo and str_ripetizioni:
                inv = int(str_intervallo)
                cnt = int(str_ripetizioni)
                if inv > 0 and cnt > 0:
                    evento['recurrence'] = [f"RRULE:FREQ=DAILY;INTERVAL={inv};COUNT={cnt}"]

        evento_creato = service.events().insert(
            calendarId='primary',
            body=evento,
            sendUpdates='all'
        ).execute()

        num_invitati = len(partecipanti) if partecipanti else 0
        return f"Evento '{titolo}' creato! Inviti spediti a {num_invitati} partecipanti. Link: {evento_creato.get('htmlLink')}"

    except Exception as e:
        return f"Errore durante la creazione dell'evento sul calendario: {e}"


def ottieni_prossimi_eventi(limite: int = 20) -> str:
    """Legge i prossimi eventi a calendario per la chat interna."""
    try:
        servizio = autentica_calendar()
        ora_attuale = datetime.now(timezone.utc).isoformat()

        risultati = servizio.events().list(
            calendarId='primary',
            timeMin=ora_attuale,
            maxResults=limite,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        eventi = risultati.get('items', [])

        riepilogo = ""
        for evento in eventi:
            inizio = evento['start'].get('dateTime', evento['start'].get('date'))
            titolo = evento.get('summary', 'Senza Titolo')
            riepilogo += f"- {inizio}: {titolo}\n"
        return riepilogo if riepilogo else "Nessun evento in programma."
    except Exception as e:
        return f"Errore lettura calendario: {e}"