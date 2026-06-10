jest.mock('../api', () => ({
    apiGet: jest.fn(),
}));

import { apiGet } from '../api';
import {
    resolvePendingChartState,
    fetchDashboardOverview,
    fetchMarketChart,
    prefetchMarketCharts,
    getDashboardMarketChartCacheEntry,
    getDashboardOverviewSessionCache,
} from '../services/dashboardService';

describe('dashboardService', () => {
    beforeEach(() => {
        const cache = getDashboardOverviewSessionCache();
        cache.data = null;
        cache.error = '';
        cache.inFlightPromise = null;
        const chartCache = getDashboardMarketChartCacheEntry('WTI_Close', '1M', 'main');
        chartCache.data = null;
        chartCache.error = '';
        chartCache.inFlightPromise = null;
        const compactChartCache = getDashboardMarketChartCacheEntry('WTI_Close', '1M', 'main', { viewportWidth: 640 });
        compactChartCache.data = null;
        compactChartCache.error = '';
        compactChartCache.inFlightPromise = null;
        const widerChartCache = getDashboardMarketChartCacheEntry('WTI_Close', '1M', 'main', { viewportWidth: 960 });
        widerChartCache.data = null;
        widerChartCache.error = '';
        widerChartCache.inFlightPromise = null;
        apiGet.mockReset();
    });

    test('fetchDashboardOverview 在 force=true 时绕过 session cache 重新请求', async () => {
        apiGet
            .mockResolvedValueOnce({ regime: [{ subject: 'Macro', value: 68 }] })
            .mockResolvedValueOnce({ regime: [{ subject: 'Macro', value: 55 }] });

        const first = await fetchDashboardOverview();
        const second = await fetchDashboardOverview(true);

        expect(first).toEqual({ regime: [{ subject: 'Macro', value: 68 }] });
        expect(second).toEqual({ regime: [{ subject: 'Macro', value: 55 }] });
        expect(apiGet).toHaveBeenCalledTimes(2);
        expect(apiGet).toHaveBeenNthCalledWith(1, '/dashboard/overview');
        expect(apiGet).toHaveBeenNthCalledWith(2, '/dashboard/overview');
    });

    test('fetchMarketChart 在主图请求中附带 viewport width 并按宽度区分缓存', async () => {
        apiGet
            .mockResolvedValueOnce({ points: [{ price: 70.5 }], granularity: '1m' })
            .mockResolvedValueOnce({ points: [{ price: 71.5 }], granularity: '1m' });

        const compact = await fetchMarketChart('WTI_Close', '1M', 'main', { viewportWidth: 640 });
        const wide = await fetchMarketChart('WTI_Close', '1M', 'main', { viewportWidth: 960 });

        expect(compact).toEqual({ points: [{ price: 70.5 }], granularity: '1m' });
        expect(wide).toEqual({ points: [{ price: 71.5 }], granularity: '1m' });
        expect(apiGet).toHaveBeenNthCalledWith(1, '/market/chart', { symbol: 'WTI_Close', range: '1M', kind: 'main', width: 640 });
        expect(apiGet).toHaveBeenNthCalledWith(2, '/market/chart', { symbol: 'WTI_Close', range: '1M', kind: 'main', width: 960 });
    });

    test('fetchMarketChart 对 sparkline 请求不附带 viewport width', async () => {
        apiGet.mockResolvedValueOnce({ points: [{ value: 1 }], granularity: '1d' });

        await fetchMarketChart('WTI_Close', '1M', 'sparkline', { viewportWidth: 640 });

        expect(apiGet).toHaveBeenCalledWith('/market/chart', { symbol: 'WTI_Close', range: '1M', kind: 'sparkline' });
    });

    test('prefetchMarketCharts 仅预取未缓存的其它周期主图', async () => {
        const cached = getDashboardMarketChartCacheEntry('WTI_Close', '1W', 'main', { viewportWidth: 640 });
        cached.data = { points: [{ price: 71 }], granularity: '1m' };
        apiGet
            .mockResolvedValueOnce({ points: [{ price: 70 }], granularity: '1m' })
            .mockResolvedValueOnce({ points: [{ price: 72 }], granularity: '1d' });

        const result = await prefetchMarketCharts('WTI_Close', ['1M', '1W', '3M'], 'main', { viewportWidth: 640 });

        expect(result).toHaveLength(2);
        expect(apiGet).toHaveBeenCalledTimes(2);
        expect(apiGet).toHaveBeenNthCalledWith(1, '/market/chart', { symbol: 'WTI_Close', range: '1M', kind: 'main', width: 640 });
        expect(apiGet).toHaveBeenNthCalledWith(2, '/market/chart', { symbol: 'WTI_Close', range: '3M', kind: 'main', width: 640 });
    });

    test('resolvePendingChartState 在切换到未缓存周期时保留上一份可交互数据', () => {
        expect(
            resolvePendingChartState(
                { data: null, error: '' },
                { points: [{ price: 70.5 }], granularity: '1m' },
            ),
        ).toEqual({
            data: { points: [{ price: 70.5 }], granularity: '1m' },
            loading: true,
            error: '',
        });
    });
});
