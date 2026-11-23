import { apiFetch } from './api.js';

let memoriaTicket = [];
let memoriaFatture = [];

function aggiornaKPI() {
    const aperti = memoriaTicket.filter(t => (t.stato || '').toUpperCase() === 'APERTO').length;
    const inLav = memoriaTicket.filter(t => (t.stato || '').toUpperCase() === 'IN_LAVORAZIONE').length;
    const elTk = document.getElementById('kpi_ticket_aperti');
    const elTkSub = document.getElementById('kpi_ticket_sub');
    if (elTk) elTk.textContent = aperti;
    if (elTkSub) elTkSub.textContent = `${inLav} in lavorazione`;

    const daPagare = memoriaFatture.filter(f => (f.stato || '').toUpperCase() !== 'PAGATA');
    const pagate = memoriaFatture.filter(f => (f.stato || '').toUpperCase() === 'PAGATA');

    const residuo = daPagare.reduce((acc, f) => acc + Number(f.importo || 0), 0);
    const incassato = pagate.reduce((acc, f) => acc + Number(f.importo || 0), 0);

    const elFat = document.getElementById('kpi_fatture_aperte');
    const elRes = document.getElementById('kpi_fatture_residuo');
    const elInc = document.getElementById('kpi_totale_incassato');
    const elPag = document.getElementById('kpi_fatture_pagate');
    if (elFat) elFat.textContent = daPagare.length;
    if (elRes) elRes.textContent = `€ ${residuo.toFixed(2)} residui`;
    if (elInc) elInc.textContent = `€ ${incassato.toFixed(2)}`;
    if (elPag) elPag.textContent = `${pagate.length} fatture saldate`;
}

/* --- ACCOUNT GOOGLE MULTI-UTENTE --- */
export async function verificaStatoGoogle() {
    const badge = document.getElementById('google_status_badge');
    const emailEl = document.getElementById('google_status_email');
    const btn = document.getElementById('btn_collega_google');
    if (!badge || !btn) return;

    try {
        const res = await apiFetch('/api/v1/auth/google/status', {}, true);
        if (res.collegato) {
            badge.className = 'badge badge-ok';
            badge.textContent = 'Google Collegato';
            emailEl.textContent = res.email_aziendale || '';
            btn.textContent = '🔄 Ricollega Google';
        } else {
            badge.className = 'badge badge-err';
            badge.textContent = 'Google Non Collegato';
            emailEl.textContent = 'Collega il tuo account Gmail/Calendar per sincronizzare inbox e agenda.';
            btn.textContent = '🔗 Collega Account Google';
        }
    } catch {
        badge.className = 'badge badge-warn';
        badge.textContent = 'Stato Google non disponibile';
    }
}

export async function collegaGoogle() {
    try {
        const res = await apiFetch('/api/v1/auth/google/connect', {}, true);
        if (res.auth_url) {
            window.location.href = res.auth_url;
        }
    } catch (err) {
        alert(`Impossibile avviare il collegamento Google: ${err.message}`);
    }
}

export async function caricaTuttiDatiAdmin() {
    await Promise.allSettled([
        verificaStatoGoogle(),
        caricaTicket(),
        caricaFatture(),
        caricaCatalogoAdmin()
    ]);
}

/* --- INBOX --- */
export async function sincronizzaInbox() {
    const tbody = document.getElementById('tbody_inbox');
    const btn = document.getElementById('btn_sync_inbox');
    btn.disabled = true;
    btn.textContent = '⏳ Sincronizzazione...';
    tbody.innerHTML = '<tr><td colspan="4">Lettura e smistamento AI in corso...</td></tr>';

    try {
        const res = await apiFetch('/api/v1/amministrazione/inbox', {}, true);
        tbody.innerHTML = '';
        const lista = res.dati || [];

        if (!lista.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Nessuna email trovata.</td></tr>';
            return;
        }

        lista.forEach(e => {
            const tr = document.createElement('tr');

            const td1 = document.createElement('td');
            const strong = document.createElement('strong');
            strong.textContent = e.oggetto || '(Senza oggetto)';
            const sub = document.createElement('div');
            sub.style.cssText = 'font-size:0.8rem; color:var(--text-muted);';
            sub.textContent = e.mittente;
            td1.append(strong, sub);

            const td2 = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = `badge ${e.stato_ai === 'ELABORATA' ? 'badge-ok' : 'badge-warn'}`;
            badge.textContent = e.reparto_ai || 'Autonomo';
            td2.appendChild(badge);

            const td3 = document.createElement('td');
            td3.textContent = (e.risposta_ai || '').slice(0, 160);

            const td4 = document.createElement('td');
            const del = document.createElement('button');
            del.className = 'btn btn-danger btn-sm';
            del.textContent = '🗑️ Cestina';
            del.onclick = async () => {
                if (!confirm(`Spostare nel cestino "${e.oggetto || 'questa email'}"?`)) return;
                try {
                    await apiFetch(`/api/v1/amministrazione/inbox/${encodeURIComponent(e.id)}`, { method: 'DELETE' }, true);
                    tr.remove();
                } catch (err) {
                    alert(`Errore eliminazione email: ${err.message}`);
                }
            };
            td4.appendChild(del);

            tr.append(td1, td2, td3, td4);
            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="4" style="color:var(--danger);">Errore: ${err.message}</td></tr>`;
    } finally {
        btn.disabled = false;
        btn.textContent = '🔄 Sincronizza Gmail';
    }
}

/* --- TICKET --- */
export async function caricaTicket() {
    try {
        const res = await apiFetch('/api/v1/amministrazione/ticket', {}, true);
        memoriaTicket = res.dati || [];
        renderTicket();
        aggiornaKPI();
    } catch {}
}

/* --- TICKET --- */
export function renderTicket() {
    const tbody = document.getElementById('tbody_ticket');
    const filtro = document.getElementById('filtro_ticket').value;
    tbody.innerHTML = '';

    const lista = memoriaTicket.filter(t => filtro === 'TUTTI' || (t.stato || '').toUpperCase() === filtro);
    if (!lista.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted);">Nessun ticket trovato.</td></tr>';
        return;
    }

    lista.forEach(t => {
        const tr = document.createElement('tr');
        const stato = (t.stato || 'APERTO').toUpperCase();
        const prio = (t.priorita || 'MEDIA').toUpperCase();

        [t.codice_ticket, t.email_cliente, t.problema].forEach(val => {
            const td = document.createElement('td');
            td.textContent = val;
            tr.appendChild(td);
        });

        const tdPrio = document.createElement('td');
        const bPrio = document.createElement('span');
        bPrio.className = `badge ${prio === 'CRITICA' || prio === 'ALTA' ? 'badge-err' : 'badge-warn'}`;
        bPrio.textContent = prio;
        tdPrio.appendChild(bPrio);

        const tdStato = document.createElement('td');
        const bStato = document.createElement('span');
        bStato.className = `badge ${stato === 'CHIUSO' ? 'badge-ok' : stato === 'IN_LAVORAZIONE' ? 'badge-warn' : 'badge-err'}`;
        bStato.textContent = stato.replace('_', ' ');
        tdStato.appendChild(bStato);

        const tdAz = document.createElement('td');
        tdAz.style.cssText = 'display:flex; gap:6px; flex-wrap:wrap;';

        if (stato === 'APERTO') {
            const b1 = document.createElement('button');
            b1.className = 'btn btn-sm';
            b1.textContent = '⚙️ Prendi';
            b1.onclick = () => aggiornaTicket(t.codice_ticket, 'IN_LAVORAZIONE');
            tdAz.appendChild(b1);
        }
        if (stato !== 'CHIUSO') {
            const b2 = document.createElement('button');
            b2.className = 'btn btn-success btn-sm';
            b2.textContent = '✔️ Chiudi';
            b2.onclick = () => aggiornaTicket(t.codice_ticket, 'CHIUSO');
            tdAz.appendChild(b2);
        }

        const bEdit = document.createElement('button');
        bEdit.className = 'btn btn-sm';
        bEdit.textContent = '✏️';
        bEdit.title = 'Modifica ticket';
        bEdit.onclick = async () => {
            const nuovoProblema = prompt('Descrizione problema:', t.problema);
            if (nuovoProblema === null) return;
            const nuovaPrio = prompt('Priorità (BASSA, MEDIA, ALTA, CRITICA):', prio);
            if (nuovaPrio === null) return;
            try {
                await apiFetch(`/api/v1/amministrazione/ticket/${encodeURIComponent(t.codice_ticket)}`, {
                    method: 'PUT',
                    body: JSON.stringify({ problema: nuovoProblema.trim(), priorita: nuovaPrio.trim().toUpperCase() })
                }, true);
                await caricaTicket();
            } catch (err) {
                alert(`Errore modifica ticket: ${err.message}`);
            }
        };

        const bDel = document.createElement('button');
        bDel.className = 'btn btn-danger btn-sm';
        bDel.textContent = '🗑️';
        bDel.title = 'Elimina ticket';
        bDel.onclick = async () => {
            if (!confirm(`Eliminare definitivamente il ticket ${t.codice_ticket}?`)) return;
            try {
                await apiFetch(`/api/v1/amministrazione/ticket/${encodeURIComponent(t.codice_ticket)}`, { method: 'DELETE' }, true);
                await caricaTicket();
            } catch (err) {
                alert(`Errore eliminazione ticket: ${err.message}`);
            }
        };

        tdAz.append(bEdit, bDel);
        tr.append(tdPrio, tdStato, tdAz);
        tbody.appendChild(tr);
    });
}

async function aggiornaTicket(codice, stato) {
    await apiFetch(`/api/v1/amministrazione/ticket/${encodeURIComponent(codice)}/stato`, {
        method: 'PUT',
        body: JSON.stringify({ stato })
    }, true);
    await caricaTicket();
}

/* --- FATTURE --- */
export async function caricaFatture() {
    const tbody = document.getElementById('tbody_fatture');
    tbody.innerHTML = '';
    try {
        const res = await apiFetch('/api/v1/amministrazione/fatture', {}, true);
        memoriaFatture = res.dati || [];

        if (!memoriaFatture.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Nessuna fattura registrata.</td></tr>';
            aggiornaKPI();
            return;
        }

        memoriaFatture.forEach(f => {
            const tr = document.createElement('tr');
            const pagata = (f.stato || '').toUpperCase() === 'PAGATA';
            const td1 = document.createElement('td'); td1.textContent = f.numero_fattura;
            const td2 = document.createElement('td'); td2.textContent = `€ ${Number(f.importo).toFixed(2)}`;
            const td3 = document.createElement('td');
            const b = document.createElement('span');
            b.className = `badge ${pagata ? 'badge-ok' : 'badge-err'}`;
            b.textContent = f.stato;
            td3.appendChild(b);

            const td4 = document.createElement('td');
            td4.style.cssText = 'display:flex; gap:6px; flex-wrap:wrap;';

            if (!pagata) {
                const btn = document.createElement('button');
                btn.className = 'btn btn-success btn-sm';
                btn.textContent = '✔️ Pagata';
                btn.onclick = async () => {
                    await apiFetch('/api/v1/amministrazione/fatture/paga', {
                        method: 'POST',
                        body: JSON.stringify({ numero_fattura: f.numero_fattura, importo_pagato: String(f.importo) })
                    }, true);
                    await caricaFatture();
                };
                td4.appendChild(btn);
            }

            const bEdit = document.createElement('button');
            bEdit.className = 'btn btn-sm';
            bEdit.textContent = '✏️';
            bEdit.title = 'Modifica fattura';
            bEdit.onclick = async () => {
                const nuovoImp = prompt(`Nuovo importo (€) per ${f.numero_fattura}:`, f.importo);
                if (nuovoImp === null) return;
                const nuovoStato = prompt('Stato (DA_PAGARE / PAGATA):', f.stato);
                if (nuovoStato === null) return;
                try {
                    await apiFetch(`/api/v1/amministrazione/fatture/${f.numero_fattura}`, {
                        method: 'PUT',
                        body: JSON.stringify({ importo: parseFloat(nuovoImp), stato: nuovoStato.trim().toUpperCase() })
                    }, true);
                    await caricaFatture();
                } catch (err) {
                    alert(`Errore modifica fattura: ${err.message}`);
                }
            };

            const bDel = document.createElement('button');
            bDel.className = 'btn btn-danger btn-sm';
            bDel.textContent = '🗑️';
            bDel.title = 'Elimina fattura';
            bDel.onclick = async () => {
                if (!confirm(`Eliminare definitivamente la fattura ${f.numero_fattura}?`)) return;
                try {
                    await apiFetch(`/api/v1/amministrazione/fatture/${f.numero_fattura}`, { method: 'DELETE' }, true);
                    await caricaFatture();
                } catch (err) {
                    alert(`Errore eliminazione fattura: ${err.message}`);
                }
            };

            td4.append(bEdit, bDel);
            tr.append(td1, td2, td3, td4);
            tbody.appendChild(tr);
        });

        aggiornaKPI();
    } catch (e) {
        console.error('Errore caricaFatture:', e);
        tbody.innerHTML = `<tr><td colspan="4" style="color:var(--danger);">Errore caricamento fatture: ${e.message}</td></tr>`;
    }
}


export async function creaFattura() {
    const val = parseFloat(document.getElementById('nuova_fattura_importo').value);
    if (!val || val <= 0) return alert('Inserisci un importo valido.');
    await apiFetch('/api/v1/amministrazione/fatture/nuova', {
        method: 'POST',
        body: JSON.stringify({ importo: val })
    }, true);
    document.getElementById('nuova_fattura_importo').value = '';
    await caricaFatture();
}

/* --- CATALOGO --- */
export async function caricaCatalogoAdmin() {
    const tbody = document.getElementById('tbody_catalogo');
    tbody.innerHTML = '';
    try {
        const res = await apiFetch('/api/v1/soluzioni');
        const lista = res.dati || [];

        if (!lista.length) {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:var(--text-muted);">Nessuna soluzione a catalogo.</td></tr>';
            return;
        }

        lista.forEach(s => {
            const tr = document.createElement('tr');
            const td1 = document.createElement('td'); td1.textContent = `${s.icona || '🚀'} ${s.titolo}`;
            const td2 = document.createElement('td'); td2.textContent = s.prezzo;
            const td3 = document.createElement('td');
            const del = document.createElement('button');
            del.className = 'btn btn-danger btn-sm';
            del.textContent = 'Elimina';
            del.onclick = async () => {
                await apiFetch(`/api/v1/amministrazione/soluzioni/${s.id}`, { method: 'DELETE' }, true);
                await caricaCatalogoAdmin();
            };
            td3.appendChild(del);
            tr.append(td1, td2, td3);
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error('Errore caricaCatalogoAdmin:', e);
        tbody.innerHTML = `<tr><td colspan="3" style="color:var(--danger);">Errore caricamento catalogo: ${e.message}</td></tr>`;
    }
}

export async function creaSoluzioneAdmin() {
    const body = {
        titolo: document.getElementById('sol_titolo').value.trim(),
        prezzo: document.getElementById('sol_prezzo').value.trim(),
        icona: document.getElementById('sol_icona').value.trim() || '🚀',
        descrizione: document.getElementById('sol_desc').value.trim(),
        prompt_precompilato: document.getElementById('sol_prompt').value.trim()
    };
    if (!body.titolo || !body.prezzo) return alert('Titolo e prezzo obbligatori.');
    await apiFetch('/api/v1/amministrazione/soluzioni', {
        method: 'POST',
        body: JSON.stringify(body)
    }, true);
    ['sol_titolo', 'sol_prezzo', 'sol_desc', 'sol_prompt'].forEach(id => document.getElementById(id).value = '');
    await caricaCatalogoAdmin();
}

/* --- CHAT INTERNA AI --- */
export async function inviaChatInterna(testoOverride = null) {
    const input = document.getElementById('chat_input');
    const domanda = (testoOverride || input.value).trim();
    if (!domanda) return;
    if (!testoOverride) input.value = '';

    const box = document.getElementById('chat_box');
    const uDiv = document.createElement('div'); uDiv.className = 'msg msg-user'; uDiv.textContent = domanda;
    const aDiv = document.createElement('div'); aDiv.className = 'msg msg-ai'; aDiv.textContent = '⏳ Elaborazione...';
    box.append(uDiv, aDiv);
    box.scrollTop = box.scrollHeight;

    try {
        const res = await apiFetch('/api/v1/amministrazione/chat', {
            method: 'POST',
            body: JSON.stringify({ domanda })
        }, true);
        aDiv.textContent = res.risposta;
    } catch (e) {
        aDiv.textContent = `Errore: ${e.message}`;
    }
    box.scrollTop = box.scrollHeight;
}