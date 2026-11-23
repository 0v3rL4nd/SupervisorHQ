import { apiFetch } from './api.js';

export async function caricaCatalogoClienti() {
    const grid = document.getElementById('grid_soluzioni_client');
    grid.innerHTML = '';
    try {
        const res = await apiFetch('/api/v1/soluzioni');
        (res.dati || []).forEach(s => {
            const card = document.createElement('div');
            card.className = 'glass soluzione-card';

            const top = document.createElement('div');
            const h3 = document.createElement('h3');
            h3.textContent = `${s.icona || '🚀'} ${s.titolo}`;
            const p = document.createElement('p');
            p.style.cssText = 'color: var(--text-muted); font-size: 0.88rem; margin-top: 6px;';
            p.textContent = s.descrizione;
            top.append(h3, p);

            const bottom = document.createElement('div');
            bottom.style.cssText = 'display:flex; justify-content:space-between; align-items:center; margin-top:8px;';
            const price = document.createElement('span');
            price.className = 'soluzione-price';
            price.textContent = s.prezzo;

            const btn = document.createElement('button');
            btn.className = 'btn btn-sm';
            btn.textContent = 'Richiedi';
            btn.onclick = () => {
                document.getElementById('client_testo').value = s.prompt_precompilato || `Vorrei informazioni su ${s.titolo}`;
                document.getElementById('client_testo').focus();
            };

            bottom.append(price, btn);
            card.append(top, bottom);
            grid.appendChild(card);
        });
    } catch (e) {
        grid.textContent = 'Impossibile caricare il catalogo.';
    }
}

export async function inviaPraticaCliente() {
    const mittente = document.getElementById('client_email').value.trim();
    const testo_email = document.getElementById('client_testo').value.trim();
    const box = document.getElementById('client_esito');
    const btn = document.getElementById('btn_invia_pratica');

    if (!mittente || !testo_email) return alert('Inserisci email e testo della richiesta.');

    btn.disabled = true;
    btn.textContent = '⏳ Elaborazione AI...';
    box.classList.remove('hidden');
    box.textContent = 'Il Supervisore AI sta smistando la tua pratica...';

    try {
        const res = await apiFetch('/api/v1/pratiche/nuova', {
            method: 'POST',
            body: JSON.stringify({ mittente, testo_email })
        });
        box.textContent = `[Reparto: ${res.reparto_lavorazione}]\n\n${res.risposta_inviata}`;
    } catch (e) {
        box.textContent = `Errore: ${e.message}`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Invia Richiesta';
    }
}