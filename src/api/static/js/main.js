import { apiFetch, getToken, setToken, clearToken } from './api.js';
import { caricaCatalogoClienti, inviaPraticaCliente } from './client.js';
import {
    caricaTuttiDatiAdmin, sincronizzaInbox, caricaTicket, renderTicket,
    creaFattura, creaSoluzioneAdmin, inviaChatInterna, collegaGoogle,
    caricaVerbali, renderArchivioVerbali, inviaVerbaleTesto, caricaFileVerbale
} from './admin.js';

function mostraVista(nome) {
    ['view_client', 'view_login', 'view_admin'].forEach(id => document.getElementById(id).classList.add('hidden'));
    document.getElementById(nome).classList.remove('hidden');
    document.getElementById('btn_logout').classList.toggle('hidden', !getToken());
}

async function eseguiLogin() {
    const username = document.getElementById('login_user').value.trim();
    const password = document.getElementById('login_pass').value.trim();
    const err = document.getElementById('login_err');
    err.textContent = '';

    try {
        const res = await apiFetch('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
        setToken(res.access_token);
        mostraVista('view_admin');
        await caricaTuttiDatiAdmin();
    } catch (e) {
        err.textContent = e.message;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    caricaCatalogoClienti();

    // Navigazione principale
    document.getElementById('btn_vista_clienti').onclick = () => { mostraVista('view_client'); caricaCatalogoClienti(); };
    document.getElementById('btn_vista_admin').onclick = () => {
        if (getToken()) { mostraVista('view_admin'); caricaTuttiDatiAdmin(); }
        else mostraVista('view_login');
    };
    document.getElementById('btn_logout').onclick = () => { clearToken(); mostraVista('view_client'); };

    // Eventi Client & Login
    document.getElementById('btn_invia_pratica').onclick = inviaPraticaCliente;
    document.getElementById('btn_do_login').onclick = eseguiLogin;
    document.getElementById('btn_collega_google')?.addEventListener('click', collegaGoogle);

    // Tabs Admin
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.admin-panel').forEach(p => p.classList.add('hidden'));
            btn.classList.add('active');
            document.getElementById(btn.dataset.tab).classList.remove('hidden');
        };
    });

    // Eventi Admin
    document.getElementById('btn_sync_inbox').onclick = sincronizzaInbox;
    document.getElementById('btn_refresh_ticket').onclick = caricaTicket;
    document.getElementById('filtro_ticket').onchange = renderTicket;
    document.getElementById('btn_crea_fattura').onclick = creaFattura;
    document.getElementById('btn_crea_soluzione').onclick = creaSoluzioneAdmin;
    document.getElementById('btn_send_chat').onclick = () => inviaChatInterna();
    document.getElementById('btn_refresh_verbali')?.addEventListener('click', caricaVerbali);
    document.getElementById('btn_analizza_verbale')?.addEventListener('click', inviaVerbaleTesto);
    document.getElementById('btn_upload_verbale')?.addEventListener('click', caricaFileVerbale);
    document.getElementById('filtro_verbali')?.addEventListener('input', renderArchivioVerbali);
    document.getElementById('btn_chiudi_anteprima')?.addEventListener('click', () => {
        document.getElementById('verbale_anteprima')?.classList.add('hidden');
    });
    document.querySelectorAll('.chip-chat').forEach(c => c.onclick = () => inviaChatInterna(c.dataset.q));
});