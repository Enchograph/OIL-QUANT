import { apiGet } from '../api';
import { getDashboardMarketCacheKey } from '../dashboardLive';

const dashboardOverviewSessionCache = {
    data: null,
    error: '',
    inFlightPromise: null,
};

const dashboardMarketChartSessionCache = new Map();

const expectedChartGranularity = {
    main: {
        '1D': '1m',
        '1W': '1m',
        '1M': '1m',
        '3M': '1d',
        '1Y': '1d',
    },
    sparkline: {
        '1D': '1m',
        '1W': '1d',
        '1M': '1d',
        '3M': '1d',
        '1Y': '1d',
    },
};

function isChartCacheCompatible(data, range, chartKind) {
    if (!data || typeof data !== 'object') {
        return false;
    }
    const expectedGranularity = expectedChartGranularity[chartKind]?.[range];
    if (!expectedGranularity) {
        return true;
    }
    return data.granularity === expectedGranularity;
}

export function getDashboardOverviewSessionCache() {
    return dashboardOverviewSessionCache;
}

export function getDashboardMarketChartCacheEntry(symbol, range, chartKind = 'main', options = {}) {
    const cacheKey = getDashboardMarketCacheKey(symbol, range, chartKind, options);

    if (!dashboardMarketChartSessionCache.has(cacheKey)) {
        dashboardMarketChartSessionCache.set(cacheKey, {
            data: null,
            error: '',
            inFlightPromise: null,
        });
    }

    return dashboardMarketChartSessionCache.get(cacheKey);
}

export function getInitialDashboardOverviewState() {
    if (dashboardOverviewSessionCache.data || dashboardOverviewSessionCache.error) {
        return {
            data: dashboardOverviewSessionCache.data,
            loading: false,
            error: dashboardOverviewSessionCache.error,
        };
    }

    return {
        data: null,
        loading: true,
        error: '',
    };
}

export function getInitialDashboardChartState(symbol, range, chartKind = 'main', options = {}) {
    const cacheEntry = getDashboardMarketChartCacheEntry(symbol, range, chartKind, options);
    if (cacheEntry.data && !isChartCacheCompatible(cacheEntry.data, range, chartKind)) {
        cacheEntry.data = null;
        cacheEntry.error = '';
    }

    if (cacheEntry.data || cacheEntry.error) {
        return {
            data: cacheEntry.data,
            loading: false,
            error: cacheEntry.error,
        };
    }

    return {
        data: null,
        loading: true,
        error: '',
    };
}

export function resolvePendingChartState(cacheEntry, fallbackData = null) {
    return {
        data: cacheEntry?.data ?? fallbackData ?? null,
        loading: true,
        error: '',
    };
}

export function fetchDashboardOverview(force = false) {
    if (!force && dashboardOverviewSessionCache.data) {
        return Promise.resolve(dashboardOverviewSessionCache.data);
    }

    if (!force && dashboardOverviewSessionCache.error) {
        return Promise.reject(new Error(dashboardOverviewSessionCache.error));
    }

    if (!force && dashboardOverviewSessionCache.inFlightPromise) {
        return dashboardOverviewSessionCache.inFlightPromise;
    }

    if (force) {
        dashboardOverviewSessionCache.error = '';
    }

    const request = apiGet('/dashboard/overview')
        .then((data) => {
            dashboardOverviewSessionCache.data = data;
            dashboardOverviewSessionCache.error = '';
            return data;
        })
        .catch((error) => {
            const message = error instanceof Error ? error.message : '请求失败';
            dashboardOverviewSessionCache.error = message;
            throw new Error(message);
        })
        .finally(() => {
            dashboardOverviewSessionCache.inFlightPromise = null;
        });

    dashboardOverviewSessionCache.inFlightPromise = request;
    return request;
}

export function fetchMarketChart(symbol, range, chartKind = 'main', options = {}) {
    const cacheEntry = getDashboardMarketChartCacheEntry(symbol, range, chartKind, options);
    if (cacheEntry.data && !isChartCacheCompatible(cacheEntry.data, range, chartKind)) {
        cacheEntry.data = null;
        cacheEntry.error = '';
    }

    if (cacheEntry.data) {
        return Promise.resolve(cacheEntry.data);
    }

    if (cacheEntry.error) {
        return Promise.reject(new Error(cacheEntry.error));
    }

    if (cacheEntry.inFlightPromise) {
        return cacheEntry.inFlightPromise;
    }

    const params = { symbol, range, kind: chartKind };
    if (chartKind === 'main' && options.viewportWidth) {
        params.width = Math.max(1, Math.round(options.viewportWidth));
    }

    const request = apiGet('/market/chart', params)
        .then((data) => {
            cacheEntry.data = isChartCacheCompatible(data, range, chartKind) ? data : null;
            cacheEntry.error = '';
            return cacheEntry.data ?? data;
        })
        .catch((error) => {
            const message = error instanceof Error ? error.message : '请求失败';
            cacheEntry.error = message;
            throw new Error(message);
        })
        .finally(() => {
            cacheEntry.inFlightPromise = null;
        });

    cacheEntry.inFlightPromise = request;
    return request;
}

export function prefetchMarketCharts(symbol, ranges = [], chartKind = 'main', options = {}) {
    const normalizedRanges = [...new Set((ranges || []).filter(Boolean))];
    if (!normalizedRanges.length) {
        return Promise.resolve([]);
    }

    const pendingRequests = normalizedRanges
        .map((range) => {
            const cacheEntry = getDashboardMarketChartCacheEntry(symbol, range, chartKind, options);
            if (cacheEntry.data || cacheEntry.inFlightPromise) {
                return null;
            }
            return fetchMarketChart(symbol, range, chartKind, options).catch(() => null);
        })
        .filter(Boolean);

    if (!pendingRequests.length) {
        return Promise.resolve([]);
    }

    return Promise.all(pendingRequests);
}

export function fetchBatchMarketCharts(symbols, range, chartKind = 'sparkline') {
    const normalizedSymbols = [...new Set((symbols || []).filter(Boolean))];
    if (!normalizedSymbols.length) {
        return Promise.resolve({});
    }

    return apiGet('/market/charts/batch', {
        symbols: normalizedSymbols.join(','),
        range,
        kind: chartKind,
    }).then((data) => data?.items ?? {});
}
