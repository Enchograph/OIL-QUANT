import { apiAskChat, apiGetChatBootstrap } from '../api';

export const QA_SESSION_STORAGE_KEY = 'citi-oil-platform-qa-session';
export const QA_SESSION_SCHEMA_VERSION = 4;

export function loadStoredQaSession() {
    if (typeof window === 'undefined') {
        return null;
    }
    try {
        const raw = window.localStorage.getItem(QA_SESSION_STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch (error) {
        return null;
    }
}

export function isCompatibleQaSession(session) {
    if (!session || typeof session !== 'object') {
        return false;
    }
    return Number(session.schemaVersion || 0) >= QA_SESSION_SCHEMA_VERSION;
}

export function persistQaSession(session) {
    if (typeof window === 'undefined') {
        return;
    }
    window.localStorage.setItem(
        QA_SESSION_STORAGE_KEY,
        JSON.stringify({
            schemaVersion: QA_SESSION_SCHEMA_VERSION,
            ...session,
        }),
    );
}

export function clearStoredQaSession() {
    if (typeof window === 'undefined') {
        return;
    }
    window.localStorage.removeItem(QA_SESSION_STORAGE_KEY);
}

export async function fetchQaBootstrap() {
    return apiGetChatBootstrap();
}

export async function sendQaQuestion(payload) {
    return apiAskChat(payload);
}
