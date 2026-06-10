import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AreaSeries, createChart, CrosshairMode, LineSeries, LineStyle, LineType } from 'lightweight-charts';
import { dashboardSeriesLabels } from '../../config/dashboardData';
import { getActiveFlowId, markDuration, markEvent, markFlow } from '../../utils/devDiagnostics';
import { formatChartTooltipTime, formatDashboardTooltipValue } from '../../utils/formatters';

const DEFAULT_CHART_PRIMITIVES = { AreaSeries, LineSeries };

function resolveChartColors(container) {
    const styles = getComputedStyle(container);
    const read = (name, fallback) => styles.getPropertyValue(name).trim() || fallback;

    return {
        text: read('--dashboard-text-muted', '#8c97a8'),
        price: read('--dashboard-chart-line-primary', '#d6e4ff'),
        priceWidth: Number(read('--dashboard-chart-line-primary-width', '2')) || 2,
        ma5: read('--dashboard-chart-line-brand', '#3cb0ff'),
        ma20: read('--dashboard-chart-line-warning', '#ffb347'),
        ma60Top: read('--dashboard-chart-ma60-top', read('--dashboard-chart-fill', 'rgba(60, 176, 255, 0.16)')),
        ma60Bottom: read('--dashboard-chart-ma60-bottom', 'rgba(0, 0, 0, 0)'),
        ma60Line: read('--dashboard-chart-ma60-line', 'rgba(0, 0, 0, 0)'),
        grid: read('--dashboard-grid-axis', 'rgba(140, 151, 168, 0.12)'),
        tooltipBg: read('--dashboard-chart-tooltip-bg', 'rgba(8, 13, 23, 0.96)'),
        tooltipBorder: read('--dashboard-chart-tooltip-border', 'rgba(140, 151, 168, 0.28)'),
        accent: read('--dashboard-text-accent', '#9bc3ff'),
        background: read('--dashboard-surface', '#0a0f16'),
    };
}

function toUtcSeconds(value) {
    const timestamp = new Date(value).getTime();
    if (Number.isNaN(timestamp)) {
        return null;
    }
    return Math.floor(timestamp / 1000);
}

function toSeriesData(points, key) {
    return points
        .map((point) => {
            const time = toUtcSeconds(point.observed_at);
            if (time === null) {
                return null;
            }
            const value = point[key];
            if (value === null || value === undefined) {
                return { time };
            }
            return { time, value: Number(value) };
        })
        .filter(Boolean);
}

function isRenderableTooltipPoint(point) {
    if (!point) {
        return false;
    }

    return ['price', 'ma5', 'ma20', 'ma60'].some((field) => point[field] !== null && point[field] !== undefined);
}

export function findNearestTooltipPoint(pointLookup, sortedTimes, targetTime) {
    if (!(pointLookup instanceof Map) || !sortedTimes?.length || typeof targetTime !== 'number') {
        return null;
    }

    const exactPoint = pointLookup.get(targetTime);
    if (isRenderableTooltipPoint(exactPoint)) {
        return exactPoint;
    }

    let insertionIndex = sortedTimes.findIndex((time) => time >= targetTime);
    if (insertionIndex === -1) {
        insertionIndex = sortedTimes.length;
    }

    for (let offset = 0; offset < sortedTimes.length; offset += 1) {
        const leftIndex = insertionIndex - offset - (insertionIndex < sortedTimes.length && sortedTimes[insertionIndex] === targetTime ? 0 : 1);
        const rightIndex = insertionIndex + offset;

        if (leftIndex >= 0) {
            const leftPoint = pointLookup.get(sortedTimes[leftIndex]);
            if (isRenderableTooltipPoint(leftPoint)) {
                return leftPoint;
            }
        }

        if (rightIndex < sortedTimes.length) {
            const rightPoint = pointLookup.get(sortedTimes[rightIndex]);
            if (isRenderableTooltipPoint(rightPoint)) {
                return rightPoint;
            }
        }
    }

    return null;
}

function buildTooltipRows(point) {
    return ['price', 'ma5', 'ma20', 'ma60']
        .map((field) => ({
            label: dashboardSeriesLabels[field],
            value: point[field],
        }))
        .filter((row) => row.value !== null && row.value !== undefined);
}

export function resolveTooltipState(param, pointLookup, sortedTimes, range, timeZone) {
    if (!param?.point || param.point.x < 0 || param.point.y < 0 || param.time === undefined || typeof param.time !== 'number') {
        return null;
    }

    const point = findNearestTooltipPoint(pointLookup, sortedTimes, param.time);
    if (!point) {
        return null;
    }

    const rows = buildTooltipRows(point);
    if (!rows.length) {
        return null;
    }

    return {
        title: formatChartTooltipTime(point.observed_at, range, timeZone),
        rows,
    };
}

function isSameTooltipState(current, next) {
    if (current === next) {
        return true;
    }
    if (!current || !next) {
        return false;
    }
    if (current.title !== next.title || current.rows.length !== next.rows.length) {
        return false;
    }

    return current.rows.every((row, index) => (
        row.label === next.rows[index]?.label && row.value === next.rows[index]?.value
    ));
}

function buildSeriesSignature(seriesData) {
    return ['price', 'ma5', 'ma20', 'ma60']
        .map((key) => {
            const rows = seriesData[key];
            const first = rows[0]?.time ?? 'na';
            const last = rows[rows.length - 1]?.time ?? 'na';
            return `${key}:${rows.length}:${first}:${last}`;
        })
        .join('|');
}

export default function DashboardMainChart({
    points,
    range,
    timeZone,
    status,
    width,
    height,
    chartFactory = createChart,
    chartPrimitives = DEFAULT_CHART_PRIMITIVES,
}) {
    const containerRef = useRef(null);
    const chartRef = useRef(null);
    const seriesRef = useRef(null);
    const pointLookupRef = useRef(new Map());
    const sortedTimesRef = useRef([]);
    const rangeRef = useRef(range);
    const timeZoneRef = useRef(timeZone);
    const tooltipStateRef = useRef(null);
    const lastSeriesSignatureRef = useRef('');
    const lastSizeRef = useRef({ width: null, height: null });
    const lastFitContentKeyRef = useRef('');
    const [resolvedHeight, setResolvedHeight] = useState(() => (Number.isFinite(height) && height > 0 ? height : 0));
    const pointLookup = useMemo(
        () =>
            new Map(
                points
                    .map((point) => {
                        const time = toUtcSeconds(point.observed_at);
                        if (time === null) {
                            return null;
                        }
                        return [time, point];
                    })
                .filter(Boolean),
            ),
        [points],
    );
    const sortedTimes = useMemo(() => [...pointLookup.keys()].sort((left, right) => left - right), [pointLookup]);
    const seriesData = useMemo(
        () => ({
            price: toSeriesData(points, 'price'),
            ma5: toSeriesData(points, 'ma5'),
            ma20: toSeriesData(points, 'ma20'),
            ma60: toSeriesData(points, 'ma60'),
        }),
        [points],
    );
    const seriesSignature = useMemo(() => buildSeriesSignature(seriesData), [seriesData]);
    const [tooltipState, setTooltipState] = useState(null);

    useEffect(() => {
        markEvent('dashboard:main-chart-mounted', { range });
        return () => {
            markEvent('dashboard:main-chart-unmounted', { range });
            const predictionNavigationFlowId = getActiveFlowId('prediction-navigation');
            if (predictionNavigationFlowId) {
                markFlow(predictionNavigationFlowId, 'dashboard:main-chart-unmounted', { range });
            }
        };
    }, []);

    useEffect(() => {
        pointLookupRef.current = pointLookup;
        sortedTimesRef.current = sortedTimes;
        rangeRef.current = range;
        timeZoneRef.current = timeZone;
    }, [pointLookup, sortedTimes, range, timeZone]);

    useEffect(() => {
        tooltipStateRef.current = tooltipState;
    }, [tooltipState]);

    useEffect(() => {
        if (Number.isFinite(height) && height > 0) {
            setResolvedHeight(height);
            return undefined;
        }

        const container = containerRef.current?.parentElement;
        if (!container) {
            return undefined;
        }

        const updateHeight = () => {
            const nextHeight = Math.round(container.getBoundingClientRect().height);
            if (nextHeight > 0) {
                setResolvedHeight((current) => (current === nextHeight ? current : nextHeight));
            }
        };

        updateHeight();

        if (typeof ResizeObserver === 'undefined') {
            window.addEventListener('resize', updateHeight);
            return () => {
                window.removeEventListener('resize', updateHeight);
            };
        }

        const resizeObserver = new ResizeObserver(() => {
            updateHeight();
        });
        resizeObserver.observe(container);

        return () => {
            resizeObserver.disconnect();
        };
    }, [height]);

    useEffect(() => {
        const container = containerRef.current;
        if (!container) {
            return undefined;
        }
        if (!width || !resolvedHeight) {
            return undefined;
        }

        const colors = resolveChartColors(container);
        const chart = chartFactory(container, {
            autoSize: false,
            width,
            height: resolvedHeight,
            layout: {
                background: {
                    color: colors.background,
                },
                textColor: colors.text,
                fontFamily: 'Consolas, Courier New, monospace',
                attributionLogo: true,
            },
            grid: {
                vertLines: { color: colors.grid, visible: false },
                horzLines: { color: colors.grid, visible: true },
            },
            rightPriceScale: {
                borderVisible: false,
                scaleMargins: { top: 0.16, bottom: 0.16 },
            },
            leftPriceScale: {
                visible: false,
            },
            timeScale: {
                visible: false,
                borderVisible: false,
                timeVisible: range !== '1Y',
                secondsVisible: false,
                fixRightEdge: true,
            },
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: { color: colors.grid, width: 1, style: LineStyle.Dashed, visible: true, labelVisible: false },
                horzLine: { color: colors.grid, width: 1, style: LineStyle.Dotted, visible: true, labelVisible: false },
            },
            handleScroll: {
                mouseWheel: false,
                pressedMouseMove: false,
                horzTouchDrag: false,
                vertTouchDrag: false,
            },
            handleScale: {
                mouseWheel: false,
                pinch: false,
                axisPressedMouseMove: false,
                axisDoubleClickReset: false,
            },
        });

        const ma60Series = chart.addSeries(chartPrimitives.AreaSeries, {
            topColor: colors.ma60Top,
            bottomColor: colors.ma60Bottom,
            lineColor: colors.ma60Line,
            lineWidth: 1,
            crosshairMarkerVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
        });
        const ma20Series = chart.addSeries(chartPrimitives.LineSeries, {
            color: colors.ma20,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            lineType: LineType.Curved,
            crosshairMarkerVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
        });
        const ma5Series = chart.addSeries(chartPrimitives.LineSeries, {
            color: colors.ma5,
            lineWidth: 1,
            lineType: LineType.Curved,
            crosshairMarkerVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
        });
        const priceSeries = chart.addSeries(chartPrimitives.LineSeries, {
            color: colors.price,
            lineWidth: colors.priceWidth,
            lineType: LineType.WithSteps,
            crosshairMarkerVisible: true,
            crosshairMarkerRadius: 3,
            lastValueVisible: false,
            priceLineVisible: false,
        });

        const handleCrosshairMove = (param) => {
            if (!param?.point || param.point.x < 0 || param.point.y < 0) {
                setTooltipState((current) => {
                    if (current === null) {
                        return current;
                    }
                    tooltipStateRef.current = null;
                    return null;
                });
                return;
            }

            if (param.time === undefined || typeof param.time !== 'number') {
                return;
            }

            const nextTooltipState = resolveTooltipState(
                param,
                pointLookupRef.current,
                sortedTimesRef.current,
                rangeRef.current,
                timeZoneRef.current,
            );

            if (!nextTooltipState) {
                return;
            }

            setTooltipState((current) => {
                if (isSameTooltipState(current, nextTooltipState)) {
                    return current;
                }
                tooltipStateRef.current = nextTooltipState;
                return nextTooltipState;
            });
        };

        chart.subscribeCrosshairMove(handleCrosshairMove);
        chart.timeScale().fitContent();

        chartRef.current = chart;
        seriesRef.current = {
            ma60Series,
            ma20Series,
            ma5Series,
            priceSeries,
            handleCrosshairMove,
        };

        return () => {
            chart.unsubscribeCrosshairMove(handleCrosshairMove);
            markDuration('dashboard:main-chart-remove', () => chart.remove(), { range });
            chartRef.current = null;
            seriesRef.current = null;
        };
    }, [chartFactory, chartPrimitives, resolvedHeight, width]);

    useEffect(() => {
        if (!chartRef.current) {
            return;
        }

        chartRef.current.applyOptions({
            timeScale: {
                timeVisible: range !== '1Y',
            },
        });
    }, [range]);

    useEffect(() => {
        if (!seriesRef.current || !chartRef.current) {
            return;
        }

        if (lastSeriesSignatureRef.current !== seriesSignature) {
            seriesRef.current.ma60Series.setData(seriesData.ma60);
            seriesRef.current.ma20Series.setData(seriesData.ma20);
            seriesRef.current.ma5Series.setData(seriesData.ma5);
            seriesRef.current.priceSeries.setData(seriesData.price);
            lastSeriesSignatureRef.current = seriesSignature;
        }

        if (lastSizeRef.current.width !== width || lastSizeRef.current.height !== resolvedHeight) {
            chartRef.current.resize(width, resolvedHeight, true);
            lastSizeRef.current = { width, height: resolvedHeight };
        }

        const nextFitContentKey = `${range}:${seriesSignature}`;
        if (lastFitContentKeyRef.current !== nextFitContentKey) {
            chartRef.current.timeScale().fitContent();
            lastFitContentKeyRef.current = nextFitContentKey;
        }
    }, [range, resolvedHeight, seriesData, seriesSignature, width]);

    const resolvedHeightStyle = resolvedHeight > 0 ? { height: `${resolvedHeight}px` } : undefined;

    return (
        <div className="dashboard-main-chart" style={resolvedHeightStyle}>
            <div ref={containerRef} className="dashboard-main-chart__surface" style={resolvedHeightStyle} />
            {tooltipState ? (
                <div className="dashboard-main-chart__tooltip">
                    <div className="dashboard-tooltip">
                        <div className="dashboard-tooltip__title">{tooltipState.title}</div>
                        <div className="dashboard-tooltip__rows">
                            {tooltipState.rows.map((row) => (
                                <div key={row.label} className="dashboard-tooltip__row">
                                    <span>{row.label}</span>
                                    <strong>{formatDashboardTooltipValue(row.value)}</strong>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            ) : null}
            {status ? <div className="dashboard-main-chart__status">{status}</div> : null}
        </div>
    );
}
