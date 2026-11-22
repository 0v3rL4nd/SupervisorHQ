# SupervisorHQ
Sistema multi-agente per l'automazione d'ufficio basato su LangGraph, Ollama (Qwen 2.5) e FastAPI, con integrazione Gmail/Google Calendar, dashboard web protetta da JWT e ambiente di test per vulnerabilità LLM (OWASP Top 10).


# 🛡️ SupervisorHQ

**SupervisorHQ** è un microservizio multi-agente per l'automazione del back-office aziendale, sviluppato in Python con **LangGraph**, **FastAPI** e **Ollama** (modello locale `qwen2.5:14b`).

Il sistema orchestra un **Supervisore AI** che analizza le email e le richieste in ingresso, estrae i dati strutturati tramite **Pydantic** e smista automaticamente le pratiche verso quattro reparti specializzati (**Amministrazione**, **Commerciale**, **Assistenza Tecnica** e **Agenda**), interagendo in tempo reale con **Gmail API**, **Google Calendar API** e un database **SQLite**.

### ✨ Funzionalità principali
* **Orchestrazione Multi-Agente (LangGraph):** routing deterministico basato su schema Pydantic tra Supervisore e agenti di reparto, con memoria di conversazione (`MemorySaver`).
* **Integrazione Google Workspace:** lettura filtrata della posta in arrivo, elaborazione automatica delle email, invio risposte via Gmail API e pianificazione eventi con inviti su Google Calendar.
* **Doppia Interfaccia Web (`dashboard.html`):**
  * **Portale Clienti:** consultazione del catalogo soluzioni e invio diretto di richieste al Supervisore AI.
  * **Area Dipendenti (protetta da JWT):** sincronizzazione inbox con esiti AI, chat interna contestuale sui dati aziendali in tempo reale, gestione fatture/KPI e CRUD sul catalogo soluzioni.
* **Ambiente di Security Testing (LLM Red Teaming):** progettato anche come banco di prova per dimostrare e analizzare vulnerabilità reali in architetture agentiche (Indirect Prompt Injection, Email Relay/BEC, Excessive Agency su Calendar, System Prompt Leakage e DoS).

### 🛠️ Stack Tecnologico
`Python` · `FastAPI` · `LangGraph` · `Ollama (Qwen 2.5)` · `Pydantic` · `SQLite` · `JWT Auth` · `Gmail API` · `Google Calendar API` · `HTML/CSS/JS`
