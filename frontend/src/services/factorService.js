import { apiGet } from '../api';
import { defaultFactorColumns } from '../config/factors';

export function collectFactorColumns(apiColumns = [], rows = []) {
    const seen = new Set();
    const ordered = [];

    const pushColumn = (column) => {
        if (!column || seen.has(column)) {
            return;
        }
        seen.add(column);
        ordered.push(column);
    };

    defaultFactorColumns.forEach(pushColumn);
    apiColumns.forEach(pushColumn);
    rows.forEach((row) => {
        Object.keys(row || {}).forEach(pushColumn);
    });

    return ordered;
}

export function pickDefaultFactorColumns(availableColumns) {
    return defaultFactorColumns.filter((column) => availableColumns.includes(column));
}

const factorTableSessionCache = {
    data: null,
    error: '',
    loadedAt: 0,
    inFlightPromise: null,
    selectedColumns: null,
    hasCustomizedColumns: false,
};

export function getFactorTableSessionCache() {
    return factorTableSessionCache;
}

export function getInitialFactorTableState() {
    if (factorTableSessionCache.data || factorTableSessionCache.error) {
        return {
            data: factorTableSessionCache.data,
            loading: false,
            error: factorTableSessionCache.error,
        };
    }

    return {
        data: null,
        loading: true,
        error: '',
    };
}

export function fetchFactorTable(force = false) {
    if (!force) {
        if (factorTableSessionCache.data) {
            return Promise.resolve(factorTableSessionCache.data);
        }

        if (factorTableSessionCache.error) {
            return Promise.reject(new Error(factorTableSessionCache.error));
        }
    }

    if (!force && factorTableSessionCache.inFlightPromise) {
        return factorTableSessionCache.inFlightPromise;
    }

    const request = apiGet('/factors/table', { limit: 120 })
        .then((data) => {
            factorTableSessionCache.data = data;
            factorTableSessionCache.error = '';
            factorTableSessionCache.loadedAt = Date.now();
            return data;
        })
        .catch((error) => {
            const message = error instanceof Error ? error.message : '请求失败';
            factorTableSessionCache.error = message;
            throw new Error(message);
        })
        .finally(() => {
            factorTableSessionCache.inFlightPromise = null;
        });

    factorTableSessionCache.inFlightPromise = request;
    return request;
}
