import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import {
    buildTimelineChartPoints,
    calculateSparklineDomain,
    createResizeObserverWidthUpdater,
    formatSystemClock,
    getChartViewportBucket,
    getDashboardMarketCacheKey,
    mergeMetricsWithRangeSparklines,
    toMetricSparklinePoints,
    useSystemClock,
} from '../dashboardLive';

function ClockProbe({ onRender }) {
    const now = useSystemClock();

    onRender(now);
    return <div>{formatSystemClock(now)}</div>;
}

describe('dashboardLive', () => {
    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    });

    afterAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    });

    test('getDashboardMarketCacheKey 按 symbol 和 range 生成缓存键', () => {
        expect(getDashboardMarketCacheKey('WTI_Close', '1M')).toBe('WTI_Close::1M::main::default');
        expect(getDashboardMarketCacheKey('WTI_Close', '1M')).not.toBe(getDashboardMarketCacheKey('WTI_Close', '1W'));
        expect(getDashboardMarketCacheKey('WTI_Close', '1M')).not.toBe(getDashboardMarketCacheKey('Brent_Close', '1M'));
    });

    test('getChartViewportBucket 将主图宽度折叠成稳定缓存桶', () => {
        expect(getChartViewportBucket()).toBe('default');
        expect(getChartViewportBucket(301)).toBe('360');
        expect(getChartViewportBucket(640)).toBe('600');
        expect(getChartViewportBucket(960)).toBe('960');
    });

    test('createResizeObserverWidthUpdater 将宽度更新延后到动画帧并合并为最后一次', () => {
        const committedWidths = [];
        const frameQueue = [];
        const updater = createResizeObserverWidthUpdater(
            (width) => committedWidths.push(width),
            (callback) => {
                frameQueue.push(callback);
                return frameQueue.length;
            },
            () => {},
        );

        updater.schedule(640);
        updater.schedule(648);

        expect(committedWidths).toEqual([]);
        expect(frameQueue).toHaveLength(1);

        frameQueue[0]();

        expect(committedWidths).toEqual([648]);
    });

    test('mergeMetricsWithRangeSparklines 只替换匹配指标的小折线', () => {
        const metrics = [
            { id: 'WTI_Close', sparkline: [{ value: 1 }] },
            { id: 'Brent_Close', sparkline: [{ value: 2 }] },
        ];
        const result = mergeMetricsWithRangeSparklines(metrics, {
            WTI_Close: [{ value: 10 }, { value: 11 }],
        });

        expect(result).toEqual([
            { id: 'WTI_Close', sparkline: [{ value: 10 }, { value: 11 }] },
            { id: 'Brent_Close', sparkline: [{ value: 2 }] },
        ]);
    });

    test('toMetricSparklinePoints 将 chart points 归一化成 sparkline value', () => {
        expect(
            toMetricSparklinePoints([
                { close: 70.12, observed_at: '2026-03-29T00:00:00Z' },
                { price: 71.34, observed_at: '2026-03-29T00:01:00Z' },
                { value: 69.88, observed_at: '2026-03-29T00:02:00Z' },
                { observed_at: '2026-03-29T00:00:00Z' },
            ]),
        ).toEqual([
            { value: 70.12, observed_at: '2026-03-29T00:00:00Z' },
            { value: 71.34, observed_at: '2026-03-29T00:01:00Z' },
            { value: 69.88, observed_at: '2026-03-29T00:02:00Z' },
        ]);
    });

    test('calculateSparklineDomain 按实际波动范围缩放并保留上下留白', () => {
        expect(calculateSparklineDomain([{ value: 100 }, { value: 101 }, { value: 102 }])).toEqual([99.8, 102.2]);
        expect(calculateSparklineDomain([{ value: 88.5 }, { value: 88.5 }])).toEqual([88.4, 88.6]);
    });

    test('buildTimelineChartPoints 在分钟缺口处插入断点避免连成平线', () => {
        const result = buildTimelineChartPoints(
            [
                { observed_at: '2026-03-30T00:00:00+00:00', price: 100, ma5: 101, ma20: 102, ma60: 103 },
                { observed_at: '2026-03-30T00:01:00+00:00', price: 101, ma5: 101, ma20: 102, ma60: 103 },
                { observed_at: '2026-03-30T01:05:00+00:00', price: 98, ma5: 99, ma20: 100, ma60: 101 },
            ],
            '1D',
        );

        expect(result).toEqual([
            { observed_at: '2026-03-30T00:00:00+00:00', observedAtMs: new Date('2026-03-30T00:00:00+00:00').getTime(), price: 100, ma5: 101, ma20: 102, ma60: 103 },
            { observed_at: '2026-03-30T00:01:00+00:00', observedAtMs: new Date('2026-03-30T00:01:00+00:00').getTime(), price: 101, ma5: 101, ma20: 102, ma60: 103 },
            { observed_at: '2026-03-30T00:02:00.000+00:00', observedAtMs: new Date('2026-03-30T00:02:00.000+00:00').getTime(), price: null, ma5: null, ma20: null, ma60: null },
            { observed_at: '2026-03-30T01:05:00+00:00', observedAtMs: new Date('2026-03-30T01:05:00+00:00').getTime(), price: 98, ma5: 99, ma20: 100, ma60: 101 },
        ]);
    });

    test('useSystemClock 每秒刷新一次时间', () => {
        jest.useFakeTimers();

        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);
        const renderedTimes = [];

        act(() => {
            root.render(<ClockProbe onRender={(value) => renderedTimes.push(value.getTime())} />);
        });

        const initialRenderCount = renderedTimes.length;

        act(() => {
            jest.advanceTimersByTime(1000);
        });

        expect(renderedTimes.length).toBeGreaterThan(initialRenderCount);
        expect(renderedTimes.at(-1)).toBeGreaterThanOrEqual(renderedTimes[0] + 1000);

        act(() => {
            root.unmount();
        });
        container.remove();
        jest.useRealTimers();
    });
});
