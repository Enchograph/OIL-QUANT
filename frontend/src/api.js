export const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || '/api/v1';

function resolveApiBaseUrl() {
    if (/^https?:\/\//i.test(API_BASE_URL)) {
        return API_BASE_URL;
    }

    const normalizedBase = API_BASE_URL.startsWith('/') ? API_BASE_URL : `/${API_BASE_URL}`;
    const origin =
        typeof window !== 'undefined' && window.location?.origin
            ? window.location.origin
            : 'http://localhost';
    return `${origin}${normalizedBase}`;
}

function buildApiUrl(path, params = {}) {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    const url = new URL(`${resolveApiBaseUrl()}${normalizedPath}`);
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.set(key, value);
        }
    });
    return url;
}

async function readErrorPayload(response) {
    const payload = await response.json().catch(() => ({}));
    return payload.error || `Request failed: ${response.status}`;
}

export async function apiGet(path, params = {}) {
    const url = buildApiUrl(path, params);
    const response = await fetch(url.toString());
    if (!response.ok) {
        throw new Error(await readErrorPayload(response));
    }
    return response.json();
}

function buildAdminHeaders(auth = {}) {
    const headers = {};
    if (auth.sessionToken) {
        headers['X-Admin-Session'] = auth.sessionToken;
    }
    if (auth.adminKey) {
        headers['X-Admin-Key'] = auth.adminKey;
    }
    return headers;
}

export async function apiPost(path, params = {}, options = {}) {
    const url = buildApiUrl(path, params);
    const response = await fetch(url.toString(), {
        method: 'POST',
        headers: options.headers || {},
        body: options.body,
    });
    if (!response.ok) {
        throw new Error(await readErrorPayload(response));
    }
    return response.json();
}

export async function apiPostJson(path, body = {}, params = {}, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
    };
    return apiPost(path, params, {
        ...options,
        headers,
        body: JSON.stringify(body),
    });
}

export async function apiAdminGet(path, params = {}, auth = {}) {
    const url = buildApiUrl(path, params);
    const response = await fetch(url.toString(), {
        headers: buildAdminHeaders(auth),
    });
    if (!response.ok) {
        throw new Error(await readErrorPayload(response));
    }
    return response.json();
}

export async function apiAdminPost(path, params = {}, auth = {}) {
    return apiPost(path, params, { headers: buildAdminHeaders(auth) });
}

export async function apiAdminPostJson(path, body = {}, params = {}, auth = {}) {
    return apiPostJson(path, body, params, { headers: buildAdminHeaders(auth) });
}

export async function apiHealthCheck() {
    const startedAt = Date.now();
    const payload = await apiGet('/status/sources');
    return {
        payload,
        latencyMs: Date.now() - startedAt,
    };
}

export async function apiGetPredictionAiAnalysis() {
    return apiGet('/prediction/ai-analysis');
}

export async function apiGetChatBootstrap() {
    return apiGet('/chat/bootstrap');
}

export async function apiAskChat(payload) {
    return apiPostJson('/chat/ask', payload);
}
