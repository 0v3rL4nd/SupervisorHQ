import { apiFetch, getToken } from './api.js';

let verbali = [];
let selectedId = null;
let activeSubtab = 'azioni';

document.addEventListener('DOMContentLoaded', () => {
    if (!getToken()) {
        alert('Effettua il login dall\'Area Dipendenti per accedere ai Verbali.');
        window.location.href = '/';
        return;
    }

    document.getElementById('btn_nuovo_verbale').onclick = () => document.getElementById('panel_nuovo').classList.toggle('hidden');
    document.getElementById('btn_chiudi_nuovo').onclick = () => document.getElementById('panel_nuovo').classList.add('hidden');
    document.getElementById('btn_ws_refresh').onclick = caricaArchivio;
    document.getElementById('ws_search').oninput = renderSidebar;
    document.getElementById('ws_filter').onchange = renderSidebar;
    document.getElementById('btn_ws_analizza').onclick = inviaTesto;
    document.getElementById('btn_ws_upload').onclick = caricaFile;
    document.getElementById('btn_toggle_docs').onclick = () => {
        const p = document.getElementById('panel_docs');
        p.classList.toggle('hidden');
        if (!p.classList.contains('hidden')) caricaDocumenti();
    };
    document.getElementById('btn_chiudi_docs').onclick = () => document.getElementById('panel_docs').classList.add('hidden');
    document.getElementById('btn_doc_upload').onclick = uploadDocumento;

    caricaArchivio();
});

async function caricaArchivio() {
    try {
        const res = await apiFetch('/api/v1/amministrazione/verbali', {}, true);
        verbali = res.dati || [];
        if (selectedId && !verbali.some(v => v.id === selectedId)) selectedId = null;
        if (!selectedId && verbali.length) selectedId = verbali[0].id;
        renderSidebar();
        renderDetail();
    } catch (err) {
        document.getElementById('ws_detail').innerHTML = `<p style="color:var(--danger);">Errore: ${err.message}</p>`;
    }
}

function renderSidebar() {
    const listEl = document.getElementById('ws_list');
    const q = document.getElementById('ws_search').value.trim().toLowerCase();
    const flt = document.getElementById('ws_filter').value;
    listEl.innerHTML = '';

    const filtrati = verbali.filter(v => {
        const matchQ = (v.titolo || '').toLowerCase().includes(q)
            || (v.fonte || '').toLowerCase().includes(q)
            || (v.username_creatore || '').toLowerCase().includes(q);
        const pending = (v.azioni || []).filter(a => ['DA_CONFERMARE', 'CONFLITTO', 'ATTENZIONE', 'ERRORE'].includes(a.stato)).length;
        if (flt === 'SOSPESO' && pending === 0) return false;
        if (flt === 'COMPLETATI' && pending > 0) return false;
        return matchQ;
    });

    if (!filtrati.length) {
        listEl.innerHTML = '<p style="color:var(--text-muted); text-align:center; font-size:0.85rem;">Nessun verbale trovato.</p>';
        return;
    }

    filtrati.forEach(v => {
        const azioni = v.azioni || [];
        const ok = azioni.filter(a => a.stato === 'ESEGUITA').length;
        const pending = azioni.filter(a => a.stato === 'DA_CONFERMARE').length;

        const item = document.createElement('div');
        item.className = `ws-item ${v.id === selectedId ? 'active' : ''}`;
        item.onclick = () => { selectedId = v.id; renderSidebar(); renderDetail(); };
        item.innerHTML = `
            <div style="display:flex; justify-content:space-between; gap:6px; align-items:center;">
                <strong style="font-size:0.9rem;">${escapeHtml(v.titolo)}</strong>
                <span class="badge ${pending ? 'badge-warn' : 'badge-ok'}">${ok}/${azioni.length}</span>
            </div>
            <div style="font-size:0.75rem; color:var(--text-muted); margin-top:4px;">
                ${(v.data_creazione || '').slice(0, 16).replace('T', ' ')} · ${escapeHtml(v.fonte)}
            </div>
        `;
        listEl.appendChild(item);
    });
}

function renderDetail() {
    const box = document.getElementById('ws_detail');
    const v = verbali.find(x => x.id === selectedId);
    if (!v) {
        box.innerHTML = '<p style="color:var(--text-muted); text-align:center; padding:40px 0;">Nessun verbale selezionato.</p>';
        return;
    }

    box.innerHTML = `
        <div class="card-header" style="flex-wrap:wrap; gap:10px;">
            <div>
                <h2 style="margin:0;">📝 ${escapeHtml(v.titolo)}</h2>
                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:4px;">
                    Fonte: <strong>${escapeHtml(v.fonte)}</strong> · Caricato da <strong>${escapeHtml(v.username_creatore || '-')}</strong> il ${(v.data_creazione || '').slice(0, 16).replace('T', ' ')}
                </div>
            </div>
            <div class="quick-links">
                <a href="/#tab_ticket" class="btn btn-sm" style="text-decoration:none;">🛠️ Ticket</a>
                <a href="/#tab_inbox" class="btn btn-sm" style="text-decoration:none;">📧 Inbox</a>
                <button id="btn_del_verbale" class="btn btn-danger btn-sm">🗑️ Elimina Verbale</button>
            </div>
        </div>
        <p style="font-size:0.92rem; color:var(--text-muted); margin-top:0;">${escapeHtml(v.riepilogo || '')}</p>
        <div class="subtabs">
            <button class="btn btn-sm ${activeSubtab === 'azioni' ? 'btn-primary' : ''}" data-st="azioni">⚡ Azioni (${(v.azioni || []).length})</button>
            <button class="btn btn-sm ${activeSubtab === 'testo' ? 'btn-primary' : ''}" data-st="testo">📄 Testo Integrale</button>
            <button class="btn btn-sm ${activeSubtab === 'storico' ? 'btn-primary' : ''}" data-st="storico">🕒 Storico Esecuzioni</button>
        </div>
        <div id="ws_subcontent"></div>
    `;

    box.querySelector('#btn_del_verbale').onclick = async () => {
        if (!confirm(`Eliminare definitivamente "${v.titolo}" e tutte le sue azioni?`)) return;
        await apiFetch(`/api/v1/amministrazione/verbali/${v.id}`, { method: 'DELETE' }, true);
        selectedId = null;
        await caricaArchivio();
    };

    box.querySelectorAll('[data-st]').forEach(b => {
        b.onclick = () => { activeSubtab = b.dataset.st; renderDetail(); };
    });

    const sub = box.querySelector('#ws_subcontent');
    if (activeSubtab === 'testo') {
        sub.innerHTML = `<pre style="white-space:pre-wrap; font-family:inherit; font-size:0.88rem; color:var(--text-muted); background:rgba(0,0,0,0.25); padding:16px; border-radius:10px;">${escapeHtml(v.testo_originale || '(Non disponibile)')}</pre>`;
    } else if (activeSubtab === 'storico') {
        renderStorico(sub, v.azioni || []);
    } else {
        renderAzioni(sub, v.azioni || []);
    }
}

function renderStorico(container, azioni) {
    const eseguite = azioni.filter(a => a.stato !== 'DA_CONFERMARE');
    if (!eseguite.length) {
        container.innerHTML = '<p style="color:var(--text-muted);">Nessuna azione ancora approvata o rifiutata su questo verbale.</p>';
        return;
    }
    const rows = eseguite.map(a => `
        <tr>
            <td><span class="badge ${a.stato === 'ESEGUITA' ? 'badge-ok' : 'badge-err'}">${a.tipo} · ${a.stato}</span></td>
            <td>${escapeHtml(a.descrizione)}</td>
            <td>${escapeHtml(a.eseguito_da || '-')}</td>
            <td>${(a.data_esecuzione || '-').slice(0, 16)}</td>
            <td style="font-size:0.82rem; color:var(--text-muted);">${escapeHtml(a.esito || '')}</td>
        </tr>
    `).join('');
    container.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Stato</th><th>Azione</th><th>Utente</th><th>Data</th><th>Esito</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

const COMMIT_LABELS = {
    EMAIL: '📧 Committa e Invia',
    ACTION_ITEM: '📨 Committa e Notifica',
    TICKET: '🎫 Committa e Apri Ticket',
    RIUNIONE: '📅 Committa su Calendar',
    DOCUMENTO: '📄 Verifica e Analizza',
    CATALOGO: '📦 Committa su Catalogo',
    FATTURA: '💰 Committa Fattura',
};

function renderAzioni(container, azioni) {
    container.style.cssText = 'display:flex; flex-direction:column; gap:12px;';
    if (!azioni.length) {
        container.innerHTML = '<p style="color:var(--text-muted);">Nessuna azione estratta.</p>';
        return;
    }

    azioni.forEach(a => {
        const p = a.payload || {};
        const card = document.createElement('div');
        card.style.cssText = 'padding:14px; border-radius:10px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06);';

        const badgeCls = a.stato === 'ESEGUITA'
            ? 'badge-ok'
            : (a.stato === 'DA_CONFERMARE' ? 'badge-warn' : 'badge-err');

        const top = document.createElement('div');
        top.style.cssText = 'display:flex; justify-content:space-between; align-items:flex-start; gap:10px; flex-wrap:wrap;';

        const info = document.createElement('div');
        info.style.flex = '1';
        const meta = `<span class="badge" style="margin-right:6px; background:rgba(157,78,221,0.22); color:#e0aaff;">🤖 ${escapeHtml(a.agente_competente || 'AGENTE')}</span>`
            + `<span class="badge" style="margin-right:8px; background:rgba(255,255,255,0.08);">👤 ${escapeHtml(a.assegnatario_username || '-')}</span>`;

        info.innerHTML = `<div style="margin-bottom:6px;">${meta}<span class="badge ${badgeCls}">${a.tipo} · ${a.stato}</span></div><strong>${escapeHtml(a.descrizione)}</strong>`;

        const preview = creaAnteprimaAzione(a.tipo, p);
        if (preview) info.appendChild(preview);

        const statusLine = document.createElement('div');
        statusLine.style.cssText = 'font-size:0.8rem; color:var(--text-muted); margin-top:6px; white-space:pre-wrap;';
        if (a.esito) statusLine.textContent = `Esito: ${a.esito}`;
        info.appendChild(statusLine);

        const actions = document.createElement('div');
        actions.style.cssText = 'display:flex; gap:6px; flex-wrap:wrap;';

        const editBox = document.createElement('div');
        editBox.className = 'hidden';
        editBox.style.cssText = 'margin-top:12px; padding-top:12px; border-top:1px solid rgba(255,255,255,0.1); display:flex; flex-direction:column; gap:8px;';

        if (['DA_CONFERMARE', 'CONFLITTO', 'ATTENZIONE', 'ERRORE'].includes(a.stato)) {
            if (a.tipo === 'RIUNIONE') {
                const bChk = document.createElement('button');
                bChk.className = 'btn btn-sm';
                bChk.textContent = '🔍 Verifica Slot';
                bChk.onclick = async () => {
                    bChk.disabled = true; bChk.textContent = '⏳...';
                    try {
                        const chk = await apiFetch(`/api/v1/amministrazione/verbali/azioni/${a.id}/verifica-calendar`, {}, true);
                        statusLine.textContent = chk.dati.messaggio;
                        statusLine.style.color = chk.dati.libero ? '#00f5d4' : '#ff006e';
                    } catch (err) {
                        statusLine.textContent = `Errore: ${err.message}`;
                    } finally {
                        bChk.disabled = false; bChk.textContent = '🔍 Verifica Slot';
                    }
                };
                actions.appendChild(bChk);
            }

            const bEdit = document.createElement('button');
            bEdit.className = 'btn btn-sm';
            bEdit.textContent = '✏️ Modifica';
            bEdit.onclick = () => {
                editBox.classList.toggle('hidden');
                if (!editBox.dataset.built) {
                    costruisciFormModifica(editBox, a);
                    editBox.dataset.built = '1';
                }
            };

            const bOk = document.createElement('button');
            bOk.className = 'btn btn-success btn-sm';
            bOk.textContent = COMMIT_LABELS[a.tipo] || '✔️ Conferma & Committa';
            bOk.onclick = () => eseguiAzione(a.id, 'approva');

            const bNo = document.createElement('button');
            bNo.className = 'btn btn-danger btn-sm';
            bNo.textContent = '✖️ Rifiuta';
            bNo.onclick = () => eseguiAzione(a.id, 'rifiuta');

            actions.append(bEdit, bOk, bNo);
        }

        top.append(info, actions);
        card.append(top, editBox);
        container.appendChild(card);
    });
}

function creaAnteprimaAzione(tipo, p) {
    const div = document.createElement('div');
    div.className = 'preview-box';

    if (tipo === 'EMAIL') {
        const allInfo = p.allegato_nome
            ? `\n📎 Allegato: ${p.allegato_nome} ${p.allegato_percorso ? `(✅ ${p.allegato_percorso})` : '(⚠️ non trovato in locale)'}`
            : '';
        div.textContent = `📧 ANTEPRIMA EMAIL\nA: ${p.destinatario || '⚠️ (indirizzo mancante — clicca Modifica)'}\nOggetto: ${p.oggetto || '-'}${allInfo}\n\n${p.corpo || ''}`;
        return div;
    }
    if (tipo === 'ACTION_ITEM') {
        div.textContent = `👤 Assegnatario: ${p.responsabile || '-'} (${p.responsabile_email || '⚠️ email mancante in rubrica'})\n📅 Scadenza: ${p.scadenza || 'non specificata'}`;
        return div;
    }
    if (tipo === 'RIUNIONE') {
        const part = (p.partecipanti_email || []).join(', ') || 'nessuno';
        div.textContent = `📅 Data/Ora: ${p.data_ora_iso || 'da definire'} · Durata: ${p.durata_minuti || 60} min\n👥 Invitati: ${part}`;
        return div;
    }
    if (tipo === 'TICKET') {
        div.textContent = `🎫 BOZZA TICKET (in attesa di commit)\nRichiedente: ${p.email_cliente || '-'}\nPriorità: ${p.priorita || 'MEDIA'}\nProblema: ${p.problema || p.descrizione || '-'}`;
        return div;
    }
    if (tipo === 'DOCUMENTO') {
        const statoFile = p.percorso_locale ? `✅ Trovato (${p.percorso_locale})` : '⚠️ Non trovato in docs/';
        div.textContent = `📄 VERIFICA DOCUMENTO\nFile: ${p.nome || '-'} · ${statoFile}\nContesto: ${p.contesto || '-'}`;
        return div;
    }
    if (tipo === 'CATALOGO') {
        const idTxt = p.soluzione_id ? ` (ID #${p.soluzione_id})` : '';
        div.textContent = `📦 BOZZA CATALOGO · ${p.azione || 'CREA'}${idTxt}\nTitolo: ${p.icona || '🚀'} ${p.titolo || '-'}\nPrezzo: ${p.prezzo || '-'}\nDescrizione: ${p.descrizione || '-'}`;
        return div;
    }
    if (tipo === 'FATTURA') {
        const numTxt = p.numero_fattura ? ` · N° ${p.numero_fattura}` : '';
        const impTxt = p.importo != null ? `€ ${p.importo}` : '-';
        div.textContent = `💰 BOZZA FATTURA · ${p.azione || 'EMETTI'}${numTxt}\nImporto: ${impTxt}${p.stato ? ` · Nuovo stato: ${p.stato}` : ''}`;
        return div;
    }
    return null;
}

function costruisciFormModifica(container, azione) {
    const p = { ...(azione.payload || {}) };
    const campo = (label, val, type = 'text') => {
        const w = document.createElement('div');
        w.innerHTML = `<label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">${label}</label>`;
        const el = type === 'textarea' ? document.createElement('textarea') : document.createElement('input');
        if (type !== 'textarea') el.type = type; else el.rows = 3;
        el.value = val ?? '';
        w.appendChild(el);
        container.appendChild(w);
        return el;
    };

    let raccogli = () => ({ descrizione: azione.descrizione, payload: p });

    if (azione.tipo === 'RIUNIONE') {
        const inT = campo('Titolo riunione', p.titolo || '');
        const inD = campo('Data e ora', (p.data_ora_iso || '').slice(0, 16), 'datetime-local');
        const inM = campo('Durata (min)', p.durata_minuti || 60, 'number');
        const inP = campo('Partecipanti (email separate da virgola)', (p.partecipanti_email || []).join(', '));
        raccogli = () => {
            const iso = inD.value ? `${inD.value}:00` : null;
            return {
                descrizione: `${p.is_rischedulazione ? 'Rischedula' : 'Schedula'}: ${inT.value.trim()} (${iso || 'data da definire'})`,
                payload: { ...p, titolo: inT.value.trim(), data_ora_iso: iso, durata_minuti: parseInt(inM.value, 10) || 60, partecipanti_email: inP.value.split(',').map(s => s.trim()).filter(Boolean) }
            };
        };
    } else if (azione.tipo === 'EMAIL') {
        const inDest = campo('Destinatario (email)', p.destinatario || '', 'email');
        const inOgg = campo('Oggetto email', p.oggetto || '');
        const inAll = campo('Allegato locale (nome file, opzionale)', p.allegato_nome || '');
        const inCorpo = campo('Testo email', p.corpo || azione.descrizione, 'textarea');
        raccogli = () => ({
            descrizione: `Invia email a ${inDest.value.trim() || '(mancante)'}: ${inOgg.value.trim()}`,
            payload: {
                ...p,
                destinatario: inDest.value.trim(),
                oggetto: inOgg.value.trim(),
                allegato_nome: inAll.value.trim() || null,
                allegato_percorso: inAll.value.trim() === (p.allegato_nome || '') ? p.allegato_percorso : null,
                corpo: inCorpo.value.trim(),
            }
        });
    } else if (azione.tipo === 'ACTION_ITEM') {
        const inDesc = campo('Descrizione compito', azione.descrizione);
        const inResp = campo('Responsabile (nome)', p.responsabile || '');
        const inEmail = campo('Email responsabile (per notifica)', p.responsabile_email || '', 'email');
        const inScad = campo('Scadenza', p.scadenza || '');
        raccogli = () => ({
            descrizione: inDesc.value.trim(),
            payload: { ...p, descrizione: inDesc.value.trim(), responsabile: inResp.value.trim(), responsabile_email: inEmail.value.trim(), scadenza: inScad.value.trim() }
        });
    } else if (azione.tipo === 'TICKET') {
        const inEmail = campo('Email richiedente', p.email_cliente || '', 'email');
        const inPrio = campo('Priorità (BASSA, MEDIA, ALTA, CRITICA)', p.priorita || 'MEDIA');
        const inProb = campo('Descrizione problema', p.problema || azione.descrizione, 'textarea');
        raccogli = () => ({
            descrizione: inProb.value.trim(),
            payload: {
                ...p,
                email_cliente: inEmail.value.trim(),
                priorita: (inPrio.value.trim() || 'MEDIA').toUpperCase(),
                problema: inProb.value.trim(),
            }
        });

    }  else if (azione.tipo === 'CATALOGO') {
        const inOp = campo('Operazione (CREA, AGGIORNA, ELIMINA)', p.azione || 'CREA');
        const inId = campo('ID soluzione (per AGGIORNA/ELIMINA)', p.soluzione_id ?? '', 'number');
        const inTit = campo('Titolo soluzione', p.titolo || '');
        const inPrz = campo('Prezzo', p.prezzo || '');
        const inIco = campo('Icona', p.icona || '🚀');
        const inDesc = campo('Descrizione', p.descrizione || '', 'textarea');
        raccogli = () => {
            const op = (inOp.value.trim() || 'CREA').toUpperCase();
            return {
                descrizione: `${op} soluzione catalogo: ${inTit.value.trim() || `ID #${inId.value}`}`,
                payload: {
                    ...p,
                    azione: op,
                    soluzione_id: inId.value ? parseInt(inId.value, 10) : null,
                    titolo: inTit.value.trim(),
                    prezzo: inPrz.value.trim(),
                    icona: inIco.value.trim() || '🚀',
                    descrizione: inDesc.value.trim(),
                }
            };
        };
    } else if (azione.tipo === 'FATTURA') {
        const inOp = campo('Operazione (EMETTI, PAGA, AGGIORNA, ELIMINA)', p.azione || 'EMETTI');
        const inNum = campo('Numero fattura (es. F-2026/05)', p.numero_fattura || '');
        const inImp = campo('Importo (€)', p.importo ?? '', 'number');
        const inSt = campo('Stato (DA_PAGARE / PAGATA, solo per AGGIORNA)', p.stato || '');
        raccogli = () => {
            const op = (inOp.value.trim() || 'EMETTI').toUpperCase();
            const imp = inImp.value !== '' ? parseFloat(inImp.value) : null;
            return {
                descrizione: op === 'EMETTI' ? `Emetti nuova fattura (€ ${imp})` : `${op} fattura ${inNum.value.trim()}`,
                payload: {
                    ...p,
                    azione: op,
                    numero_fattura: inNum.value.trim(),
                    importo: imp,
                    stato: inSt.value.trim().toUpperCase() || null,
                }
            };
        };
    } else {
        const inDesc = campo('Descrizione', azione.descrizione);
        raccogli = () => ({ descrizione: inDesc.value.trim(), payload: { ...p, descrizione: inDesc.value.trim() } });
    }

    const btn = document.createElement('button');
    btn.className = 'btn btn-primary btn-sm';
    btn.style.alignSelf = 'flex-start';
    btn.textContent = '💾 Salva modifiche';
    btn.onclick = async () => {
        await apiFetch(`/api/v1/amministrazione/verbali/azioni/${azione.id}`, { method: 'PUT', body: JSON.stringify(raccogli()) }, true);
        await caricaArchivio();
    };
    container.appendChild(btn);
}

async function eseguiAzione(id, op) {
    try {
        await apiFetch(`/api/v1/amministrazione/verbali/azioni/${id}/${op}`, { method: 'POST' }, true);
        await caricaArchivio();
    } catch (err) { alert(`Errore: ${err.message}`); }
}

async function inviaTesto() {
    const ta = document.getElementById('ws_testo');
    const btn = document.getElementById('btn_ws_analizza');
    if (!ta.value.trim()) return alert('Incolla il testo del verbale.');
    btn.disabled = true; btn.textContent = '⏳ Analisi AI...';
    try {
        const res = await apiFetch('/api/v1/amministrazione/verbali/testo', { method: 'POST', body: JSON.stringify({ testo: ta.value.trim() }) }, true);
        ta.value = '';
        selectedId = res.dati?.verbale_id || null;
        document.getElementById('panel_nuovo').classList.add('hidden');
        await caricaArchivio();
    } catch (err) { alert(`Errore: ${err.message}`); }
    finally { btn.disabled = false; btn.textContent = '🤖 Analizza Verbale'; }
}

async function caricaFile() {
    const inp = document.getElementById('ws_file');
    const btn = document.getElementById('btn_ws_upload');
    if (!inp.files.length) return alert('Seleziona un file PDF, DOCX, TXT o MD.');
    const fd = new FormData();
    fd.append('file', inp.files[0]);
    btn.disabled = true; btn.textContent = '⏳ Caricamento...';
    try {
        const res = await fetch('/api/v1/amministrazione/verbali/upload', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${getToken() || ''}` },
            body: fd
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Errore upload');
        inp.value = '';
        selectedId = data.dati?.verbale_id || null;
        document.getElementById('panel_nuovo').classList.add('hidden');
        await caricaArchivio();
    } catch (err) { alert(`Errore: ${err.message}`); }
    finally { btn.disabled = false; btn.textContent = '📤 Carica File'; }
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

async function caricaDocumenti() {
    const box = document.getElementById('lista_docs');
    box.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">Caricamento...</p>';
    try {
        const res = await apiFetch('/api/v1/amministrazione/documenti', {}, true);
        const files = res.dati || [];
        box.innerHTML = '';
        if (!files.length) {
            box.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">Nessun documento caricato in docs/.</p>';
            return;
        }
        files.forEach(f => {
            const row = document.createElement('div');
            row.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:8px 12px; background:rgba(255,255,255,0.03); border-radius:8px;';
            row.innerHTML = `<span>📄 <strong>${escapeHtml(f.nome)}</strong> <small style="color:var(--text-muted);">(${f.dimensione_kb} KB)</small></span>`;
            const del = document.createElement('button');
            del.className = 'btn btn-danger btn-sm';
            del.textContent = '🗑️';
            del.onclick = async () => {
                if (!confirm(`Eliminare "${f.nome}"?`)) return;
                await apiFetch(`/api/v1/amministrazione/documenti/${encodeURIComponent(f.nome)}`, { method: 'DELETE' }, true);
                await caricaDocumenti();
            };
            row.appendChild(del);
            box.appendChild(row);
        });
    } catch (err) {
        box.innerHTML = `<p style="color:var(--danger);">Errore: ${err.message}</p>`;
    }
}

async function uploadDocumento() {
    const inp = document.getElementById('doc_file');
    const btn = document.getElementById('btn_doc_upload');
    if (!inp.files.length) return alert('Seleziona un file da caricare.');
    const fd = new FormData();
    fd.append('file', inp.files[0]);
    btn.disabled = true; btn.textContent = '⏳ Caricamento...';
    try {
        const res = await fetch('/api/v1/amministrazione/documenti/upload', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${getToken() || ''}` },
            body: fd
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Errore upload');
        inp.value = '';
        await caricaDocumenti();
    } catch (err) { alert(`Errore upload: ${err.message}`); }
    finally { btn.disabled = false; btn.textContent = '📤 Carica in Archivio'; }
}