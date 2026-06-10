import { useEffect, useState } from 'react';
import { formatClockTimeInTimeZone, getBrowserTimeZone } from './utils/timezone';

export const chartRanges = ['1D', '1W', '1M', '3M', '1Y'];

export const chartRangeDurations = {
    '1D': 1,
    '1W': 7,
    '1M': 30,
    '3M': 90,
    '1Y': 365,
};

export function getChartViewportBucket(viewportWidth) {
    const numericWidth = Number(viewportWidth);
    if (!Number.isFinite(numericWidth) || numericWidth <= 0) {
        return 'default';
    }
    return String(Math.max(240, Math.round(numericWidth / 120) * 120));
}

export function getDashboardMarketCacheKey(symbol, range, chartKind = 'main', options = {}) {
    const viewportBucket = chartKind === 'main' ? getChartViewportBucket(options.viewportWidth) : 'default';
    return `${symbol}::${range}::${chartKind}::${viewportBucket}`;
}

export function createResizeObserverWidthUpdater(
    commitWidth,
    requestFrame = (callback) => window.requestAnimationFrame(callback),
    cancelFrame = (frameId) => window.cancelAnimationFrame(frameId),
) {
    let frameId = null;
    let pendingWidth = null;

    return {
        schedule(width) {
            pendingWidth = width;
            if (frameId !== null) {
                return;
            }

            frameId = requestFrame(() => {
                frameId = null;
                const nextWidth = pendingWidth;
                pendingWidth = null;
                if (typeof nextWidth === 'number' && Number.isFinite(nextWidth)) {
                    commitWidth(nextWidth);
                }
            });
        },
        cancel() {
            if (frameId !== null) {
                cancelFrame(frameId);
                frameId = null;
            }
            pendingWidth = null;
        },
    };
}

const timelineExpectedStepMinutes = {
    '1D': 1,
    '1W': 1,
    '1M': 1,
    '3M': 24 * 60,
    '1Y': 24 * 60,
};

function buildGapMarkerPoint(observedAtMs, observedAtIso) {
    return {
        observed_at: observedAtIso,
        observedAtMs,
        price: null,
        ma5: null,
        ma20: null,
        ma60: null,
    };
}

export function buildTimelineChartPoints(points = [], range = '1M') {
    const expectedStepMinutes = timelineExpectedStepMinutes[range] ?? 1;
    const gapThresholdMinutes = Math.max(expectedStepMinutes + 1, Math.ceil(expectedStepMinutes * 1.5));
    const timeline = [];

    points.forEach((point, index) => {
        const observedAtMs = new Date(point.observed_at).getTime();
        if (Number.isNaN(observedAtMs)) {
            return;
        }

        timeline.push({
            ...point,
            observedAtMs,
        });

        if (index >= points.length - 1) {
            return;
        }

        const nextObservedAtMs = new Date(points[index + 1].observed_at).getTime();
        if (Number.isNaN(nextObservedAtMs)) {
            return;
        }

        const gapMinutes = Math.round((nextObservedAtMs - observedAtMs) / 60000);
        if (gapMinutes < gapThresholdMinutes) {
            return;
        }

        const markerMs = observedAtMs + expectedStepMinutes * 60000;
        timeline.push(buildGapMarkerPoint(markerMs, new Date(markerMs).toISOString().replace('Z', '+00:00')));
    });

    return timeline;
}

export function getRangeScale(fromRange, toRange) {
    const fromDuration = chartRangeDurations[fromRange];
    const toDuration = chartRangeDurations[toRange];

    if (!fromDuration || !toDuration || fromDuration === toDuration) {
        return 1;
    }

    return Math.max(Math.min(Math.min(fromDuration, toDuration) / Math.max(fromDuration, toDuration), 1), 0.12);
}

export function formatSystemClock(value, timeZone) {
    const formatted = formatClockTimeInTimeZone(value, timeZone || getBrowserTimeZone());
    return formatted || '--:--:--';
}

export function mergeMetricsWithRangeSparklines(metrics = [], sparklineMap = {}) {
    return metrics.map((metric) => ({
        ...metric,
        sparkline: sparklineMap[metric.id] ?? metric.sparkline ?? [],
    }));
}

export function calculateSparklineDomain(points = []) {
    const values = points
        .map((point) => Number(point?.value))
        .filter((value) => Number.isFinite(value));

    if (!values.length) {
        return ['auto', 'auto'];
    }

    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const range = maxValue - minValue;
    const padding = range > 0 ? range * 0.1 : Math.max(Math.abs(minValue) * 0.001, 0.1);

    return [
        Number((minValue - padding).toFixed(4)),
        Number((maxValue + padding).toFixed(4)),
    ];
}

export function toMetricSparklinePoints(points = []) {
    return points
        .map((point) => {
            const resolvedValue = point?.value ?? point?.close ?? point?.price;

            if (resolvedValue === null || resolvedValue === undefined) {
                return null;
            }

            return {
                value: Number(resolvedValue),
                observed_at: point?.observed_at ?? null,
            };
        })
        .filter(Boolean);
}

export function resolveScreenerBarStyle(zScore) {
    const numericZScore = Number(zScore);
    if (!Number.isFinite(numericZScore)) {
        return {
            left: '50%',
            width: '0%',
            hasMinimumWidth: false,
        };
    }

    const rawWidth = Math.min((Math.abs(numericZScore) / 3) * 50, 50);
    if (rawWidth === 0) {
        const minimumWidth = 1.5;
        return {
            left: `${50 - minimumWidth / 2}%`,
            width: `${minimumWidth}%`,
            hasMinimumWidth: true,
        };
    }

    return {
        left: numericZScore > 0 ? '50%' : `${(50 - rawWidth).toFixed(2)}%`,
        width: `${rawWidth.toFixed(2)}%`,
        hasMinimumWidth: false,
    };
}

export function useSystemClock() {
    const [now, setNow] = useState(() => new Date());

    useEffect(() => {
        const timer = window.setInterval(() => {
            setNow(new Date());
        }, 1000);

        return () => {
            window.clearInterval(timer);
        };
    }, []);

    return now;
}
