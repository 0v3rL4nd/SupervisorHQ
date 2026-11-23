from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from googleapiclient.discovery import build

from src.core.google_auth import ottieni_credenziali_utente

TZ_ROMA = ZoneInfo("Europe/Rome")


def _ottieni_servizio_calendar(username: str = "admin"):
    creds = ottieni_credenziali_utente(username)
    return build("calendar", "v3", credentials=creds)


def _parse_iso_roma(data_ora_iso: str) -> datetime:
    dt = datetime.fromisoformat(data_ora_iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_ROMA)
    return dt.astimezone(TZ_ROMA)


def ottieni_prossimi_eventi(username: str = "admin", limite: int = 10) -> str:
    """Restituisce i prossimi eventi sul Google Calendar del dipendente."""
    service = _ottieni_servizio_calendar(username)
    adesso = datetime.now(timezone.utc).isoformat()

    risultati = service.events().list(
        calendarId="primary",
        timeMin=adesso,
        maxResults=limite,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    eventi = risultati.get("items", [])
    if not eventi:
        return "Nessun evento in programma."

    righe = []
    for ev in eventi:
        inizio = ev["start"].get("dateTime", ev["start"].get("date"))
        righe.append(f"- {inizio}: {ev.get('summary', '(Senza titolo)')}")
    return "\n".join(righe)


def verifica_disponibilita(
    data_ora_iso: str,
    durata_minuti: int = 60,
    partecipanti: list[str] | None = None,
    username: str = "admin",
) -> dict:
    """Verifica disponibilità (freeBusy) per l'utente e gli eventuali partecipanti, proponendo alternative."""
    service = _ottieni_servizio_calendar(username)
    inizio = _parse_iso_roma(data_ora_iso)
    fine = inizio + timedelta(minutes=durata_minuti)

    items = [{"id": "primary"}]
    if partecipanti:
        items.extend({"id": email} for email in partecipanti if email)

    def _slot_conflitti(dt_start: datetime, dt_end: datetime) -> dict:
        body = {
            "timeMin": dt_start.isoformat(),
            "timeMax": dt_end.isoformat(),
            "timeZone": "Europe/Rome",
            "items": items,
        }
        risp = service.freebusy().query(body=body).execute()
        calendari = risp.get("calendars", {})
        return {
            cal_id: dati.get("busy", [])
            for cal_id, dati in calendari.items()
            if dati.get("busy")
        }

    conflitti = _slot_conflitti(inizio, fine)
    if not conflitti:
        return {"libero": True, "alternative": [], "conflitti": {}}

    # Cerca fino a 3 slot alternativi liberi nelle ore lavorative (09:00 - 18:00)
    alternative = []
    candidato = inizio + timedelta(minutes=60)
    for _ in range(8):
        if len(alternative) >= 3:
            break
        if 9 <= candidato.hour < 18:
            if not _slot_conflitti(candidato, candidato + timedelta(minutes=durata_minuti)):
                alternative.append(candidato.strftime("%Y-%m-%d %H:%M"))
        candidato += timedelta(minutes=60)

    return {"libero": False, "alternative": alternative, "conflitti": conflitti}


def prenota_appuntamento(
    titolo: str,
    data_ora_iso: str,
    durata_minuti: int = 60,
    email_cliente: str = "",
    partecipanti: list[str] | None = None,
    username: str = "admin",
) -> str:
    """Verifica disponibilità e crea l'evento su Google Calendar inviando gli inviti."""
    lista_partecipanti = list(partecipanti or [])
    if email_cliente and email_cliente not in lista_partecipanti:
        lista_partecipanti.append(email_cliente)

    check = verifica_disponibilita(
        data_ora_iso=data_ora_iso,
        durata_minuti=durata_minuti,
        partecipanti=lista_partecipanti,
        username=username,
    )
    if not check["libero"]:
        alt = ", ".join(check["alternative"]) or "nessun altro slot in giornata"
        return f"OCCUPATO: Lo slot {data_ora_iso} non è libero. Alternative disponibili: {alt}."

    service = _ottieni_servizio_calendar(username)
    inizio = _parse_iso_roma(data_ora_iso)
    fine = inizio + timedelta(minutes=durata_minuti)

    corpo = {
        "summary": titolo,
        "start": {"dateTime": inizio.isoformat(), "timeZone": "Europe/Rome"},
        "end": {"dateTime": fine.isoformat(), "timeZone": "Europe/Rome"},
    }
    if lista_partecipanti:
        corpo["attendees"] = [{"email": e} for e in lista_partecipanti]

    evento = service.events().insert(
        calendarId="primary", body=corpo, sendUpdates="all"
    ).execute()

    return f"PRENOTATO: '{titolo}' fissato per {inizio.strftime('%d/%m/%Y alle %H:%M')} (Link: {evento.get('htmlLink', 'N/D')})."


def _trova_evento_cliente(service, email_cliente: str) -> dict | None:
    adesso = datetime.now(timezone.utc).isoformat()
    risultati = service.events().list(
        calendarId="primary",
        timeMin=adesso,
        q=email_cliente,
        singleEvents=True,
        orderBy="startTime",
        maxResults=5,
    ).execute()
    eventi = risultati.get("items", [])
    return eventi[0] if eventi else None


def sposta_appuntamento(
    email_cliente: str,
    nuova_data_ora_iso: str,
    durata_minuti: int = 60,
    username: str = "admin",
) -> str:
    """Sposta il prossimo appuntamento futuro associato all'email del cliente."""
    service = _ottieni_servizio_calendar(username)
    evento = _trova_evento_cliente(service, email_cliente)
    if not evento:
        return f"NON TROVATO: Nessun appuntamento futuro trovato per {email_cliente}."

    check = verifica_disponibilita(nuova_data_ora_iso, durata_minuti, username=username)
    if not check["libero"]:
        alt = ", ".join(check["alternative"]) or "nessun altro slot in giornata"
        return f"OCCUPATO: Il nuovo slot {nuova_data_ora_iso} non è disponibile. Alternative: {alt}."

    inizio = _parse_iso_roma(nuova_data_ora_iso)
    fine = inizio + timedelta(minutes=durata_minuti)
    evento["start"] = {"dateTime": inizio.isoformat(), "timeZone": "Europe/Rome"}
    evento["end"] = {"dateTime": fine.isoformat(), "timeZone": "Europe/Rome"}

    service.events().update(
        calendarId="primary", eventId=evento["id"], body=evento, sendUpdates="all"
    ).execute()
    return f"SPOSTATO: Appuntamento '{evento.get('summary')}' spostato al {inizio.strftime('%d/%m/%Y alle %H:%M')}."


def cancella_appuntamento(email_cliente: str, username: str = "admin") -> str:
    """Cancella il prossimo appuntamento futuro associato all'email del cliente."""
    service = _ottieni_servizio_calendar(username)
    evento = _trova_evento_cliente(service, email_cliente)
    if not evento:
        return f"NON TROVATO: Nessun appuntamento futuro da cancellare per {email_cliente}."

    service.events().delete(
        calendarId="primary", eventId=evento["id"], sendUpdates="all"
    ).execute()
    return f"CANCELLATO: Appuntamento '{evento.get('summary')}' annullato con successo."