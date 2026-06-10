import { apiGet } from '../api';

const NEWS_LIST_CACHE_TTL_MS = 60000;
const NEWS_OVERVIEW_CACHE_TTL_MS = 60000;
const NEWS_DATE_BOUNDS_CACHE_TTL_MS = 60000;
const NEWS_FEED_CACHE_TTL_MS = 60000;

const newsListSessionCache = new Map();
const newsOverviewSessionCache = new Map();
const newsDateBoundsSessionCache = new Map();
const newsDetailSessionCache = new Map();
const newsFeedSessionCache = new Map();

function createCacheEntry() {
    return {
        data: null,
        error: '',
        inFlightPromise: null,
        fetchedAt: 0,
    };
}

function getCacheEntry(cacheMap, cacheKey) {
    if (!cacheMap.has(cacheKey)) {
        cacheMap.set(cacheKey, createCacheEntry());
    }

    return cacheMap.get(cacheKey);
}

function buildCacheKey(params = {}) {
    return JSON.stringify(
        Object.entries(params)
            .filter(([, value]) => value !== undefined && value !== null && value !== '')
            .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey)),
    );
}

function isCacheFresh(entry, ttlMs) {
    return Boolean(entry.fetchedAt) && Date.now() - entry.fetchedAt < ttlMs;
}

function getInitialState(entry) {
    if (entry.data || entry.error) {
        return {
            data: entry.data,
            loading: false,
            error: entry.error,
        };
    }

    return {
        data: null,
        loading: true,
        error: '',
    };
}

function fetchWithCache(cacheMap, cacheKey, loader, { force = false, ttlMs = 0 } = {}) {
    const cacheEntry = getCacheEntry(cacheMap, cacheKey);

    if (!force && cacheEntry.data && (!ttlMs || isCacheFresh(cacheEntry, ttlMs))) {
        return Promise.resolve(cacheEntry.data);
    }

    if (!force && cacheEntry.error && (!ttlMs || isCacheFresh(cacheEntry, ttlMs))) {
        return Promise.reject(new Error(cacheEntry.error));
    }

    if (!force && cacheEntry.inFlightPromise) {
        return cacheEntry.inFlightPromise;
    }

    if (force) {
        cacheEntry.error = '';
    }

    const request = loader()
        .then((data) => {
            cacheEntry.data = data;
            cacheEntry.error = '';
            cacheEntry.fetchedAt = Date.now();
            return data;
        })
        .catch((error) => {
            const message = error instanceof Error ? error.message : '请求失败';
            cacheEntry.error = message;
            cacheEntry.fetchedAt = Date.now();
            throw new Error(message);
        })
        .finally(() => {
            cacheEntry.inFlightPromise = null;
        });

    cacheEntry.inFlightPromise = request;
    return request;
}

export function getNewsListCacheEntry(params) {
    return getCacheEntry(newsListSessionCache, buildCacheKey(params));
}

export function getNewsOverviewCacheEntry(params) {
    return getCacheEntry(newsOverviewSessionCache, buildCacheKey(params));
}

export function getNewsDateBoundsCacheEntry(params) {
    return getCacheEntry(newsDateBoundsSessionCache, buildCacheKey(params));
}

export function getNewsDetailCacheEntry(articleId) {
    return getCacheEntry(newsDetailSessionCache, articleId || '__empty__');
}

export function getNewsFeedCacheEntry(params) {
    return getCacheEntry(newsFeedSessionCache, buildCacheKey(params));
}

export function getInitialNewsListState(params) {
    return getInitialState(getNewsListCacheEntry(params));
}

export function getInitialNewsOverviewState(params) {
    return getInitialState(getNewsOverviewCacheEntry(params));
}

export function getInitialNewsDateBoundsState(params) {
    return getInitialState(getNewsDateBoundsCacheEntry(params));
}

export function getInitialNewsDetailState(articleId) {
    return getInitialState(getNewsDetailCacheEntry(articleId));
}

export function getInitialNewsFeedState(params) {
    return getInitialState(getNewsFeedCacheEntry(params));
}

export function fetchNewsList(params, force = false) {
    const cacheKey = buildCacheKey(params);
    return fetchWithCache(newsListSessionCache, cacheKey, () => apiGet('/news/list', params), {
        force,
        ttlMs: NEWS_LIST_CACHE_TTL_MS,
    });
}

export function fetchNewsOverview(params, force = false) {
    const cacheKey = buildCacheKey(params);
    return fetchWithCache(newsOverviewSessionCache, cacheKey, () => apiGet('/news/overview', params), {
        force,
        ttlMs: NEWS_OVERVIEW_CACHE_TTL_MS,
    });
}

export function fetchNewsDateBounds(params, force = false) {
    const cacheKey = buildCacheKey(params);
    return fetchWithCache(newsDateBoundsSessionCache, cacheKey, () => apiGet('/news/date-bounds', params), {
        force,
        ttlMs: NEWS_DATE_BOUNDS_CACHE_TTL_MS,
    });
}

export function fetchNewsDetail(articleId, force = false) {
    const cacheKey = articleId || '__empty__';
    return fetchWithCache(newsDetailSessionCache, cacheKey, () => apiGet(`/news/${articleId}`), {
        force,
    });
}

export function fetchNewsFeed(params, force = false) {
    const cacheKey = buildCacheKey(params);
    return fetchWithCache(newsFeedSessionCache, cacheKey, () => apiGet('/news/feed', params), {
        force,
        ttlMs: NEWS_FEED_CACHE_TTL_MS,
    });
}
