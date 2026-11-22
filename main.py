import uvicorn

if __name__ == "__main__":
    print("🚀 Avvio di SupervisorHQ come Servizio Web (FastAPI)...")

    # Esegue il server. Importa l'app FastAPI dal modulo src.api.server
    # reload=True permette di ricaricare il server se modifichi il codice
    uvicorn.run("src.api.server:app", host="127.0.0.1", port=8000, reload=True)