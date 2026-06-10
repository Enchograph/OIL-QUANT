import { apiAdminGet, apiAdminPost, apiAdminPostJson } from '../api';
import { adminActionDefinitions } from '../config/adminActions';

export function createAdminFormState() {
    return adminActionDefinitions.reduce((accumulator, action) => {
        accumulator[action.id] = { ...action.defaults };
        return accumulator;
    }, {});
}

export function createAdminRunState() {
    return adminActionDefinitions.reduce((accumulator, action) => {
        accumulator[action.id] = {
            loading: false,
            error: '',
            result: null,
        };
        return accumulator;
    }, {});
}

export async function loginAdmin(password) {
    return apiAdminPostJson('/admin/auth/login', { password });
}

export async function fetchAdminOverview(sessionToken) {
    return apiAdminGet('/admin/console/overview', {}, { sessionToken });
}

export async function fetchAdminConfig(sessionToken) {
    return apiAdminGet('/admin/console/config', {}, { sessionToken });
}

export async function fetchAdminPrograms(sessionToken) {
    return apiAdminGet('/admin/console/programs', {}, { sessionToken });
}

export async function fetchAdminLogs(sessionToken, filters = {}) {
    return apiAdminGet('/admin/console/logs', filters, { sessionToken });
}

export async function fetchAdminLogDetail(sessionToken, runId) {
    return apiAdminGet(`/admin/console/logs/${runId}`, {}, { sessionToken });
}

export async function runAdminAction(action, form, sessionToken) {
    return apiAdminPost(action.path, action.buildParams(form), { sessionToken });
}
