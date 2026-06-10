import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';

jest.mock('lightweight-charts', () => ({
    __esModule: true,
    createChart: jest.fn(),
    AreaSeries: Symbol('AreaSeries'),
    LineSeries: Symbol('LineSeries'),
    CrosshairMode: { Normal: 0 },
    LineStyle: { Dashed: 2, Dotted: 1 },
    LineType: { Curved: 2, WithSteps: 1 },
}));

import DashboardMainChart, {
    findNearestTooltipPoint,
    resolveTooltipState,
} from '../components/charts/DashboardMainChart';

describe('DashboardMainChart', () => {
    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    });

    afterAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    });

    test('将主图数据映射到 Canvas 图表的面积层和均线层', () => {
        const seriesInstances = [];
        const chart = {
            addSeries: jest.fn(() => {
                const series = {
                    setData: jest.fn(),
                    applyOptions: jest.fn(),
                };
                seriesInstances.push(series);
                return series;
            }),
            applyOptions: jest.fn(),
            remove: jest.fn(),
            resize: jest.fn(),
            subscribeCrosshairMove: jest.fn(),
            unsubscribeCrosshairMove: jest.fn(),
            timeScale: jest.fn(() => ({
                fitContent: jest.fn(),
            })),
        };
        const chartFactory = jest.fn(() => chart);
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        act(() => {
            root.render(
                <DashboardMainChart
                    range="1M"
                    timeZone="UTC"
                    width={720}
                    height={280}
                    points={[
                        { observed_at: '2026-03-30T00:00:00+00:00', price: 70, ma5: 69, ma20: 68, ma60: 67 },
                        { observed_at: '2026-03-30T00:01:00+00:00', price: 71, ma5: 70, ma20: 69, ma60: 68 },
                    ]}
                    chartFactory={chartFactory}
                    chartPrimitives={{ AreaSeries: Symbol('AreaSeries'), LineSeries: Symbol('LineSeries') }}
                />,
            );
        });

        expect(chartFactory).toHaveBeenCalledTimes(1);
        expect(chartFactory.mock.calls[0][1]).toEqual(expect.objectContaining({ autoSize: false, width: 720, height: 280 }));
        expect(chart.addSeries).toHaveBeenCalledTimes(4);
        expect(seriesInstances).toHaveLength(4);
        expect(seriesInstances[0].setData).toHaveBeenCalledWith([
            { time: 1774828800, value: 67 },
            { time: 1774828860, value: 68 },
        ]);
        expect(seriesInstances[3].setData).toHaveBeenCalledWith([
            { time: 1774828800, value: 70 },
            { time: 1774828860, value: 71 },
        ]);

        act(() => {
            root.unmount();
        });
        container.remove();
    });

    test('父级重渲染且数据未变化时不应因默认图元对象变化而重建空图', () => {
        const chart = {
            addSeries: jest.fn(() => ({
                setData: jest.fn(),
                applyOptions: jest.fn(),
            })),
            applyOptions: jest.fn(),
            remove: jest.fn(),
            resize: jest.fn(),
            subscribeCrosshairMove: jest.fn(),
            unsubscribeCrosshairMove: jest.fn(),
            timeScale: jest.fn(() => ({
                fitContent: jest.fn(),
            })),
        };
        const chartFactory = jest.fn(() => chart);
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);
        const points = [
            { observed_at: '2026-03-30T00:00:00+00:00', price: 70, ma5: 69, ma20: 68, ma60: 67 },
            { observed_at: '2026-03-30T00:01:00+00:00', price: 71, ma5: 70, ma20: 69, ma60: 68 },
        ];

        act(() => {
            root.render(
                <DashboardMainChart
                    range="1M"
                    timeZone="UTC"
                    width={720}
                    height={280}
                    points={points}
                    chartFactory={chartFactory}
                />,
            );
        });

        act(() => {
            root.render(
                <DashboardMainChart
                    range="1M"
                    timeZone="UTC"
                    width={720}
                    height={280}
                    points={points}
                    chartFactory={chartFactory}
                />,
            );
        });

        expect(chartFactory).toHaveBeenCalledTimes(1);
        expect(chart.remove).not.toHaveBeenCalled();

        act(() => {
            root.unmount();
        });
        container.remove();
    });

    test('切换 range 和 points 时应复用同一个 chart 实例并刷新系列数据', () => {
        const seriesInstances = [];
        const chart = {
            addSeries: jest.fn(() => {
                const series = {
                    setData: jest.fn(),
                    applyOptions: jest.fn(),
                };
                seriesInstances.push(series);
                return series;
            }),
            applyOptions: jest.fn(),
            remove: jest.fn(),
            resize: jest.fn(),
            subscribeCrosshairMove: jest.fn(),
            unsubscribeCrosshairMove: jest.fn(),
            timeScale: jest.fn(() => ({
                fitContent: jest.fn(),
            })),
        };
        const chartFactory = jest.fn(() => chart);
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        act(() => {
            root.render(
                <DashboardMainChart
                    range="1D"
                    timeZone="UTC"
                    width={720}
                    height={280}
                    points={[
                        { observed_at: '2026-03-30T00:00:00+00:00', price: 100, ma5: 99, ma20: 98, ma60: 97 },
                        { observed_at: '2026-03-30T00:01:00+00:00', price: 101, ma5: 100, ma20: 99, ma60: 98 },
                    ]}
                    chartFactory={chartFactory}
                />,
            );
        });

        act(() => {
            root.render(
                <DashboardMainChart
                    range="1W"
                    timeZone="UTC"
                    width={720}
                    height={280}
                    points={[
                        { observed_at: '2026-03-25T00:00:00+00:00', price: 90, ma5: 91, ma20: 92, ma60: 93 },
                        { observed_at: '2026-03-30T00:00:00+00:00', price: 105, ma5: 103, ma20: 100, ma60: 96 },
                    ]}
                    chartFactory={chartFactory}
                />,
            );
        });

        expect(chartFactory).toHaveBeenCalledTimes(1);
        expect(chart.remove).not.toHaveBeenCalled();
        expect(chart.applyOptions).toHaveBeenCalledWith(expect.objectContaining({
            timeScale: expect.objectContaining({ timeVisible: true }),
        }));
        expect(seriesInstances[3].setData).toHaveBeenLastCalledWith([
            { time: 1774396800, value: 90 },
            { time: 1774828800, value: 105 },
        ]);

        act(() => {
            root.unmount();
        });
        container.remove();
    });

    test('未传固定高度时应使用容器实际高度初始化图表', () => {
        const chart = {
            addSeries: jest.fn(() => ({
                setData: jest.fn(),
                applyOptions: jest.fn(),
            })),
            applyOptions: jest.fn(),
            remove: jest.fn(),
            resize: jest.fn(),
            subscribeCrosshairMove: jest.fn(),
            unsubscribeCrosshairMove: jest.fn(),
            timeScale: jest.fn(() => ({
                fitContent: jest.fn(),
            })),
        };
        const chartFactory = jest.fn(() => chart);
        const resizeObserverInstances = [];
        const originalResizeObserver = global.ResizeObserver;

        global.ResizeObserver = class ResizeObserver {
            constructor(callback) {
                this.callback = callback;
                resizeObserverInstances.push(this);
            }

            observe() {}

            disconnect() {}
        };

        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        act(() => {
            root.render(
                <DashboardMainChart
                    range="1M"
                    timeZone="UTC"
                    width={720}
                    points={[
                        { observed_at: '2026-03-30T00:00:00+00:00', price: 70, ma5: 69, ma20: 68, ma60: 67 },
                    ]}
                    chartFactory={chartFactory}
                />,
            );
        });

        const chartRoot = container.querySelector('.dashboard-main-chart');
        expect(chartRoot).not.toBeNull();
        Object.defineProperty(chartRoot, 'getBoundingClientRect', {
            configurable: true,
            value: () => ({ width: 720, height: 412, top: 0, left: 0, right: 720, bottom: 412 }),
        });

        act(() => {
            resizeObserverInstances[0].callback();
        });

        expect(chartFactory).toHaveBeenCalledTimes(1);
        expect(chartFactory.mock.calls[0][1]).toEqual(expect.objectContaining({ width: 720, height: 412 }));

        act(() => {
            root.unmount();
        });
        container.remove();
        global.ResizeObserver = originalResizeObserver;
    });

    test('紧凑高度下应为价格线保留足够的上下边距，避免底部走势被裁切', () => {
        const chart = {
            addSeries: jest.fn(() => ({
                setData: jest.fn(),
                applyOptions: jest.fn(),
            })),
            applyOptions: jest.fn(),
            remove: jest.fn(),
            resize: jest.fn(),
            subscribeCrosshairMove: jest.fn(),
            unsubscribeCrosshairMove: jest.fn(),
            timeScale: jest.fn(() => ({
                fitContent: jest.fn(),
            })),
        };
        const chartFactory = jest.fn(() => chart);
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        act(() => {
            root.render(
                <DashboardMainChart
                    range="1M"
                    timeZone="UTC"
                    width={720}
                    height={280}
                    points={[
                        { observed_at: '2026-03-30T00:00:00+00:00', price: 70, ma5: 69, ma20: 68, ma60: 67 },
                        { observed_at: '2026-03-30T00:01:00+00:00', price: 71, ma5: 70, ma20: 69, ma60: 68 },
                    ]}
                    chartFactory={chartFactory}
                />,
            );
        });

        expect(chartFactory.mock.calls[0][1]).toEqual(expect.objectContaining({
            rightPriceScale: expect.objectContaining({
                scaleMargins: expect.objectContaining({
                    top: 0.16,
                    bottom: 0.16,
                }),
            }),
        }));

        act(() => {
            root.unmount();
        });
        container.remove();
    });

    test('findNearestTooltipPoint 会跳过 gap marker 并吸附到最近真实点', () => {
        const pointLookup = new Map([
            [1774828800, { observed_at: '2026-03-30T00:00:00+00:00', price: 70, ma5: 69, ma20: 68, ma60: 67 }],
            [1774828860, { observed_at: '2026-03-30T00:01:00+00:00', price: null, ma5: null, ma20: null, ma60: null }],
            [1774828920, { observed_at: '2026-03-30T00:02:00+00:00', price: 72, ma5: 71, ma20: 70, ma60: 69 }],
        ]);

        expect(findNearestTooltipPoint(pointLookup, [1774828800, 1774828860, 1774828920], 1774828860)).toEqual({
            observed_at: '2026-03-30T00:00:00+00:00',
            price: 70,
            ma5: 69,
            ma20: 68,
            ma60: 67,
        });
    });

    test('resolveTooltipState 对同一有效点返回稳定 tooltip 内容', () => {
        const pointLookup = new Map([
            [1774828800, { observed_at: '2026-03-30T00:00:00+00:00', price: 70, ma5: 69, ma20: 68, ma60: 67 }],
            [1774828860, { observed_at: '2026-03-30T00:01:00+00:00', price: null, ma5: null, ma20: null, ma60: null }],
            [1774828920, { observed_at: '2026-03-30T00:02:00+00:00', price: 72, ma5: 71, ma20: 70, ma60: 69 }],
        ]);

        const tooltipState = resolveTooltipState(
            { point: { x: 10, y: 10 }, time: 1774828860 },
            pointLookup,
            [1774828800, 1774828860, 1774828920],
            '1D',
            'UTC',
        );

        expect(tooltipState).toEqual({
            title: '03/30 UTC 00:00',
            rows: [
                { label: 'WTI Price', value: 70 },
                { label: 'MA 5', value: 69 },
                { label: 'MA 20', value: 68 },
                { label: 'MA 60', value: 67 },
            ],
        });
    });
});
