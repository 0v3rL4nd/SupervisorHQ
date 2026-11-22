import os
import fitz  # PyMuPDF
import chromadb

# Percorsi assoluti
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHROMA_DB_PATH = os.path.join(BASE_DIR, 'chroma_db')
DOCS_DIR = os.path.join(BASE_DIR, 'docs')

# Inizializza il client Chroma (salverà i vettori fisicamente su disco)
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
collection = chroma_client.get_or_create_collection(name="manuali_tecnici")


def indicizza_manuali():
    """Legge i PDF in /docs, li divide in chunk e li salva in ChromaDB."""
    if not os.path.exists(DOCS_DIR):
        os.makedirs(DOCS_DIR)
        return "Cartella /docs creata. Inserisci i PDF e riavvia."

    pdf_files = [f for f in os.listdir(DOCS_DIR) if f.endswith('.pdf')]
    if not pdf_files:
        return "Nessun PDF trovato nella cartella /docs."

    print("📚 [RAG] Indicizzazione manuali in corso...")

    for file in pdf_files:
        file_path = os.path.join(DOCS_DIR, file)
        doc = fitz.open(file_path)

        testo_completo = ""
        for pagina in doc:
            testo_completo += pagina.get_text()

        # Chunking base: dividiamo in blocchi di ~1000 caratteri
        chunks = [testo_completo[i:i + 1000] for i in range(0, len(testo_completo), 1000)]

        # Prepariamo gli ID e i metadati per ChromaDB
        ids = [f"{file}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"fonte": file, "chunk": i} for i in range(len(chunks))]

        # ChromaDB calcolerà gli embedding automaticamente al primo avvio
        collection.upsert(
            documents=chunks,
            metadatas=metadatas,
            ids=ids
        )
    return "Manuali indicizzati con successo."


def cerca_soluzione(query: str, n_risultati: int = 2) -> str:
    """Cerca la soluzione al problema tecnico nei manuali indicizzati."""
    if collection.count() == 0:
        indicizza_manuali()

    risultati = collection.query(
        query_texts=[query],
        n_results=n_risultati
    )

    documenti_trovati = risultati['documents'][0]

    if not documenti_trovati:
        return "Nessuna informazione tecnica trovata nei manuali."

    contesto = "\n\n--- ESTRATTO DAL MANUALE ---\n".join(documenti_trovati)
    return contesto