import os
from fpdf import FPDF
from datetime import datetime

# Creiamo una cartella per salvare i PDF generati temporaneamente
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMP_DIR = os.path.join(BASE_DIR, 'temp_invoices')

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)


def genera_ricevuta_pdf(numero_fattura: str, email_cliente: str, importo: float, codici: list[str]) -> str:
    """Genera un PDF con la ricevuta d'acquisto e i codici di attivazione. Ritorna il path del file."""

    pdf = FPDF()
    pdf.add_page()

    # Intestazione Aziendale
    pdf.set_font("helvetica", "B", 18)
    pdf.set_text_color(123, 44, 191)  # Colore Deep Purple
    pdf.cell(0, 10, "SUPERVISOR HQ - ENTERPRISE SOFTWARE", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("helvetica", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, "Ricevuta di Acquisto Digitale", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.line(10, 30, 200, 30)
    pdf.ln(10)

    # Dati Transazione
    pdf.set_font("helvetica", "", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, f"Data Transazione: {datetime.now().strftime('%d/%m/%Y %H:%M')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Cliente: {email_cliente}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Documento Riferimento: {numero_fattura}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Importo Totale Saldato: EUR {importo:.2f}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)

    # Tabella Codici
    pdf.set_font("helvetica", "B", 14)
    pdf.set_text_color(123, 44, 191)
    pdf.cell(0, 10, "I TUOI CODICI DI ATTIVAZIONE (PRODUCT KEYS)", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("courier", "B", 12)
    pdf.set_text_color(0, 0, 0)

    # Disegniamo un box per ogni codice
    for index, codice in enumerate(codici):
        pdf.cell(10, 10, f"{index + 1}.", border=0)
        pdf.cell(0, 10, codice, border=1, new_x="LMARGIN", new_y="NEXT", align="C", fill=False)
        pdf.ln(2)

    pdf.ln(10)
    pdf.set_font("helvetica", "I", 9)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 10, "Grazie per aver scelto SupervisorHQ. Per supporto: it-support@tua-azienda.com", new_x="LMARGIN",
             new_y="NEXT", align="C")

    # Salvataggio fisico del file
    file_name = f"Ricevuta_{numero_fattura.replace('/', '_')}.pdf"
    file_path = os.path.join(TEMP_DIR, file_name)
    pdf.output(file_path)

    return file_path