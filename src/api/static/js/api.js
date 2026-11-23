export const getToken = () => localStorage.getItem('shq_token');
export const setToken = (t) => localStorage.setItem('shq_token', t);
export const clearToken = () => localStorage.removeItem('shq_token');

export async function apiFetch(url, options = {}, requiresAuth = false) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (requiresAuth) {
        const token = getToken();
        if (!token) throw new Error('AUTH_REQUIRED');
        headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(url, { ...options, headers });
    if (res.status === 401 && requiresAuth) {
        clearToken();
        throw new Error('UNAUTHORIZED');
    }

    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Errore HTTP ${res.status}`);
    return data;
}