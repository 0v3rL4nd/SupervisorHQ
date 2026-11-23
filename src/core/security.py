import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Chiave segreta (in produzione va caricata da variabile d'ambiente / .env)
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "chiave_super_segreta_supervisorhq_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Estrae automaticamente il token dall'header "Authorization: Bearer <token>"
security_scheme = HTTPBearer()


def crea_token(username: str, ruolo: str) -> str:
    """Genera un token JWT firmato contenente username (sub), ruolo e scadenza."""
    scadenza = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": username,
        "role": ruolo,
        "exp": scadenza
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verifica_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme)
    ) -> str:
    """Dependency FastAPI: valida il JWT e verifica che il ruolo sia ROLE_ADMIN."""
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        ruolo: str | None = payload.get("role")

        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token non valido: soggetto mancante."
            )

        if ruolo != "ROLE_ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permessi insufficienti: richiesto ROLE_ADMIN."
            )

        return username

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token scaduto. Effettua nuovamente il login."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token non valido o corrotto."
        )