import io
import os
import pymupdf
from docx import Document


def estrai_testo_da_bytes(contenuto: bytes, filename: str) -> str:
    """Estrae testo pulito da file PDF, DOCX, TXT o MD."""
    ext = os.path.splitext(filename.lower())[1]

    if ext == ".pdf":
        testo_pagine = []
        with pymupdf.open(stream=contenuto, filetype="pdf") as doc:
            for pagina in doc:
                testo_pagine.append(pagina.get_text("text"))
        return "\n".join(testo_pagine).strip()

    if ext == ".docx":
        doc = Document(io.BytesIO(contenuto))
        paragrafi = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        # Include eventuale testo dentro le tabelle del verbale
        for table in doc.tables:
            for row in table.rows:
                celle = [c.text.strip() for c in row.cells if c.text.strip()]
                if celle:
                    paragrafi.append(" | ".join(celle))
        return "\n".join(paragrafi).strip()

    if ext in {".txt", ".md", ""}:
        return contenuto.decode("utf-8", errors="replace").strip()

    raise ValueError(f"Formato file non supportato: '{ext}'. Usa PDF, DOCX, TXT o MD.")