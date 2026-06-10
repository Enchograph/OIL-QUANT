import React, { lazy, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Activity } from 'lucide-react';
import { Bar, BarChart, Cell, Line, LineChart, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import DashboardTooltip from '../../components/charts/DashboardTooltip';
import RangeToggle from '../../components/charts/RangeToggle';
import SemanticRangeChartFrame from '../../components/charts/SemanticRangeChartFrame';
import {
    fetchBatchMarketCharts,
    fetchDashboardOverview,
    fetchMarketChart,
    getDashboardMarketChartCacheEntry,
    getDashboardOverviewSessionCache,
    getInitialDashboardChartState,
    getInitialDashboardOverviewState,
    prefetchMarketCharts,
    resolvePendingChartState,
} from '../../services/dashboardService';
import { formatChartTooltipTime, formatMetricDisplay, formatSignedPercent } from '../../utils/formatters';
import { getActiveFlowId, markEvent, markFlow, measurePromise } from '../../utils/devDiagnostics';
import { buildTimelineChartPoints, calculateSparklineDomain, chartRanges, createResizeObserverWidthUpdater, formatSystemClock, mergeMetricsWithRangeSparklines, toMetricSparklinePoints, useSystemClock } from '../../dashboardLive';
import { useTimezone } from '../../timezone';

const EMPTY_CHART_DATA = [];
const DashboardMainChart = lazy(() => import('../../components/charts/DashboardMainChart'));
const TICKER_TOOLTIP_PROPS = {
    cursor: false,
    allowEscapeViewBox: { x: true, y: true },
    offset: 12,
    wrapperStyle: {
        pointerEvents: 'none',
        zIndex: 12,
        translate: '0 8px',
    },
};

function DashboardSystemClock() {
    const clock = useSystemClock();
    const { resolvedTimezone } = useTimezone();

    return <div className="dashboard-terminal__clock">SYS_TIME: {formatSystemClock(clock, resolvedTimezone)}</div>;
}

function CountryRiskMiniChart({ item }) {
    const chartData = useMemo(
        () => [{ name: item.country, value: item.value, remainder: item.max - item.value }],
        [item.country, item.max, item.value],
    );

    return (
        <ResponsiveContainer width="100%" height={12} minWidth={0} minHeight={12}>
            <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 0, left: 0, bottom: 0 }} barCategoryGap={0}>
                <XAxis type="number" domain={[0, item.max]} hide />
                <YAxis type="category" dataKey="name" hide />
                <Bar dataKey="value" stackId="risk" radius={[0, 0, 0, 0]} isAnimationActive animationDuration={360} animationEasing="ease-out"><Cell fill={item.color} /></Bar>
                <Bar dataKey="remainder" stackId="risk" radius={[0, 0, 0, 0]} isAnimationActive={false}><Cell fill="var(--dashboard-chart-fill)" /></Bar>
            </BarChart>
        </ResponsiveContainer>
    );
}

export function LiveDashboardView() {
    const { resolvedTimezone } = useTimezone();
    const [range, setRange] = useState('1M');
    const [overviewState, setOverviewState] = useState(() => getInitialDashboardOverviewState());
    const [chartViewportWidth, setChartViewportWidth] = useState(null);
    const [chartState, setChartState] = useState(() => getInitialDashboardChartState('WTI_Close', '1M', 'main'));
    const [metricSparklineMap, setMetricSparklineMap] = useState({});
    const chartBodyRef = useRef(null);
    const overview = overviewState.data ?? {};
    const baseMetrics = useMemo(
        () => (overview.metrics ?? EMPTY_CHART_DATA).filter((metric) => metric.id !== 'RBOB_Gasoline'),
        [overview.metrics],
    );
    const metrics = mergeMetricsWithRangeSparklines(baseMetrics, metricSparklineMap);
    const topMovers = overview.topMovers ?? EMPTY_CHART_DATA;
    const chartPoints = chartState.data?.points ?? EMPTY_CHART_DATA;
    const regime = overview.regime ?? EMPTY_CHART_DATA;
    const countryRisk = overview.countryRisk ?? EMPTY_CHART_DATA;
    const signalBlocks = overview.signalBlocks ?? EMPTY_CHART_DATA;
    const timelineChartPoints = useMemo(() => buildTimelineChartPoints(chartPoints, range), [chartPoints, range]);

    useEffect(() => {
        markEvent('dashboard:view-mounted', { range });
        return () => {
            markEvent('dashboard:view-unmounted', { range });
            const predictionNavigationFlowId = getActiveFlowId('prediction-navigation');
            if (predictionNavigationFlowId) {
                markFlow(predictionNavigationFlowId, 'dashboard:view-unmounted', { range });
            }
        };
    }, []);

    useLayoutEffect(() => {
        const element = chartBodyRef.current;
        if (!element) {
            return undefined;
        }

        const widthUpdater = createResizeObserverWidthUpdater((nextWidth) => {
            setChartViewportWidth((current) => (current === nextWidth ? current : nextWidth));
        });

        const updateChartViewportWidth = () => {
            const rect = element.getBoundingClientRect();
            widthUpdater.schedule(Math.round(rect.width));
        };

        updateChartViewportWidth();

        if (typeof ResizeObserver === 'undefined') {
            window.addEventListener('resize', updateChartViewportWidth);
            return () => {
                widthUpdater.cancel();
                window.removeEventListener('resize', updateChartViewportWidth);
            };
        }

        const resizeObserver = new ResizeObserver(() => {
            updateChartViewportWidth();
        });
        resizeObserver.observe(element);

        return () => {
            widthUpdater.cancel();
            resizeObserver.disconnect();
        };
    }, []);

    useEffect(() => {
        let cancelled = false;
        const overviewCache = getDashboardOverviewSessionCache();

        if (overviewCache.data || overviewCache.error) {
            setOverviewState({ data: overviewCache.data, loading: false, error: overviewCache.error });
        }

        if (!overviewCache.data) {
            setOverviewState({ data: null, loading: true, error: '' });
        }

        measurePromise('dashboard:overview', () => fetchDashboardOverview(true), { force: true })
            .then((data) => {
                if (!cancelled) {
                    setOverviewState({ data, loading: false, error: '' });
                }
            })
            .catch((error) => {
                if (!cancelled) {
                    setOverviewState({ data: overviewCache.data, loading: false, error: error instanceof Error ? error.message : '请求失败' });
                }
            });

        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        let cancelled = false;
        if (!chartViewportWidth) {
            return undefined;
        }

        const requestOptions = { viewportWidth: chartViewportWidth };
        const cacheEntry = getDashboardMarketChartCacheEntry('WTI_Close', range, 'main', requestOptions);

        if (cacheEntry.data || cacheEntry.error) {
            setChartState({ data: cacheEntry.data, loading: false, error: cacheEntry.error });
            return undefined;
        }

        setChartState((current) => resolvePendingChartState(cacheEntry, current?.data ?? null));
        measurePromise('dashboard:market-chart', () => fetchMarketChart('WTI_Close', range, 'main', requestOptions), {
            range,
            viewportWidth: chartViewportWidth,
        })
            .then((data) => {
                if (!cancelled) {
                    setChartState({ data, loading: false, error: '' });
                }
            })
            .catch((error) => {
                if (!cancelled) {
                    setChartState({ data: cacheEntry.data, loading: false, error: error instanceof Error ? error.message : '请求失败' });
                }
            });

        return () => {
            cancelled = true;
        };
    }, [chartViewportWidth, range]);

    useEffect(() => {
        if (!chartViewportWidth) {
            return undefined;
        }

        const currentCacheEntry = getDashboardMarketChartCacheEntry('WTI_Close', range, 'main', { viewportWidth: chartViewportWidth });
        if (!currentCacheEntry.data) {
            return undefined;
        }

        const rangesToPrefetch = chartRanges.filter((item) => item !== range);
        if (!rangesToPrefetch.length) {
            return undefined;
        }

        prefetchMarketCharts('WTI_Close', rangesToPrefetch, 'main', { viewportWidth: chartViewportWidth });
        return undefined;
    }, [chartViewportWidth, range]);

    useEffect(() => {
        let cancelled = false;

        if (!baseMetrics.length) {
            setMetricSparklineMap((current) => (Object.keys(current).length ? {} : current));
            return undefined;
        }

        measurePromise(
            'dashboard:batch-sparklines',
            () => fetchBatchMarketCharts(
                baseMetrics.map((metric) => metric.id),
                range,
                'sparkline',
            ),
            {
                range,
                symbolCount: baseMetrics.length,
            },
        )
            .then((items) => {
                if (cancelled) {
                    return;
                }

                setMetricSparklineMap(
                    Object.fromEntries(
                        baseMetrics.map((metric) => [
                            metric.id,
                            toMetricSparklinePoints(items?.[metric.id]?.points ?? metric.sparkline ?? []),
                        ]),
                    ),
                );
            })
            .catch(() => {
                if (!cancelled) {
                    setMetricSparklineMap(
                        Object.fromEntries(
                            baseMetrics.map((metric) => [metric.id, metric.sparkline ?? []]),
                        ),
                    );
                }
            });

        return () => {
            cancelled = true;
        };
    }, [baseMetrics, range]);

    return (
        <div className="dashboard-view">
            <div className="dashboard-terminal">
                <div className="dashboard-terminal__bar">
                    <div className="dashboard-terminal__title"><Activity size={14} /><span>GLOBAL MACRO & FACTOR TERMINAL V2.0</span></div>
                    <DashboardSystemClock />
                </div>

                <div className="dashboard-ticker-grid">
                    {metrics.map((metric) => (
                        <section key={metric.id} className="dashboard-ticker">
                            <div className="dashboard-ticker__top">
                                <span className="dashboard-ticker__label" title={metric.id}>{metric.label ?? metric.id}</span>
                                <span className={`dashboard-ticker__change ${metric.direction === 'up' ? 'up' : 'down'}`}>{formatSignedPercent(metric.changePercent)}</span>
                            </div>
                            <div className="dashboard-ticker__bottom">
                                <span className="dashboard-ticker__value">{formatMetricDisplay(metric)}</span>
                                <div className="dashboard-ticker__chart">
                                    <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={28}>
                                        <LineChart data={metric.sparkline ?? EMPTY_CHART_DATA}>
                                            <YAxis hide domain={calculateSparklineDomain(metric.sparkline ?? EMPTY_CHART_DATA)} />
                                            <Tooltip
                                                {...TICKER_TOOLTIP_PROPS}
                                                content={(
                                                    <DashboardTooltip
                                                        title={metric.label ?? metric.id}
                                                        rows={(point) => [
                                                            { label: '时间', value: point.observed_at ? formatChartTooltipTime(point.observed_at, range, resolvedTimezone) : null },
                                                            { label: 'Current', value: point.value, valueClassName: metric.direction === 'up' ? 'up' : 'down' },
                                                        ]}
                                                    />
                                                )}
                                            />
                                            <Line type="monotone" dataKey="value" stroke={metric.direction === 'up' ? 'var(--status-success)' : 'var(--status-danger)'} strokeWidth={1.2} dot={false} isAnimationActive={false} />
                                        </LineChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>
                        </section>
                    ))}
                </div>

                <div className="dashboard-dense-grid">
                    <section className="dashboard-card dashboard-card--screener">
                        <div className="dashboard-card__header"><span>Factor Z-Score Screener</span><b>RAW / Z-SCR</b></div>
                        <div className="dashboard-screener">
                            <div className="dashboard-screener__columns"><span>FACTOR CODE</span><span>RAW</span><span>Z-SCR</span></div>
                            {topMovers.map((item) => {
                                const width = Math.min((Math.abs(item.zScore) / 3) * 50, 50);
                                const left = item.zScore > 0 ? '50%' : `${50 - width}%`;
                                return (
                                    <div key={item.factor} className="dashboard-screener__item">
                                        <div className="dashboard-screener__row">
                                            <div className="dashboard-screener__factor"><strong title={item.factor}>{item.factor}</strong><span>{item.description}</span></div>
                                            <div className="dashboard-screener__raw">{item.value}</div>
                                            <div className={`dashboard-screener__zscore ${item.direction === 'up' ? 'up' : 'down'}`}>{item.zScore > 0 ? '+' : ''}{Number(item.zScore).toFixed(2)}</div>
                                        </div>
                                        <div className="dashboard-screener__bar">
                                            <div className="dashboard-screener__axis" />
                                            <div className={`dashboard-screener__fill ${item.direction === 'up' ? 'dashboard-screener__fill--up' : 'dashboard-screener__fill--down'}`} style={{ left, width: `${width}%` }} />
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </section>

                    <section className="dashboard-card dashboard-card--chart">
                        <div className="dashboard-chart-title"><span>WTI Price vs Moving Averages (5, 20, 60)</span><RangeToggle value={range} onChange={setRange} /></div>
                        <div ref={chartBodyRef} className="dashboard-card__body dashboard-card__body--chart">
                            <div className="dashboard-main-chart-shell">
                                <SemanticRangeChartFrame range={range} animate={false}>
                                    <Suspense fallback={<div className="dashboard-main-chart dashboard-main-chart--loading"><div className="dashboard-main-chart__status">LOADING CHART...</div></div>}>
                                        <DashboardMainChart
                                            width={chartViewportWidth}
                                            points={timelineChartPoints}
                                            range={range}
                                            timeZone={resolvedTimezone}
                                            status={chartState.loading ? 'SYNCING PRICE STREAM...' : chartState.error || ''}
                                        />
                                    </Suspense>
                                </SemanticRangeChartFrame>
                            </div>
                        </div>
                    </section>

                    <section className="dashboard-card dashboard-card--radar">
                        <div className="dashboard-card__header"><span>Market Regime Matrix</span></div>
                        <div className="dashboard-card__body dashboard-card__body--center">
                            <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={220}>
                                <RadarChart cx="50%" cy="50%" outerRadius="68%" data={regime}>
                                    <Tooltip content={<DashboardTooltip title={(point) => point.subject} rows={(point) => [{ label: 'Value', value: point.value }]} />} />
                                    <PolarGrid stroke="var(--dashboard-grid-axis)" />
                                    <PolarAngleAxis dataKey="subject" tick={{ fill: 'var(--dashboard-text-secondary)', fontSize: 9, fontFamily: 'Consolas, Courier New, monospace' }} />
                                    <Radar dataKey="value" stroke="var(--dashboard-chart-line-brand)" fill="var(--dashboard-chart-line-brand)" fillOpacity={0.28} isAnimationActive={false} />
                                </RadarChart>
                            </ResponsiveContainer>
                        </div>
                    </section>

                    <section className="dashboard-card dashboard-card--country">
                        <div className="dashboard-card__header"><span>GPR Country Heatmap</span></div>
                        <div className="dashboard-country-list">
                            {countryRisk.map((item) => (
                                <div key={item.country} className="dashboard-country-list__item">
                                    <div className="dashboard-country-list__row"><span>{item.country}</span><span>{item.value}</span></div>
                                    <CountryRiskMiniChart item={item} />
                                </div>
                            ))}
                        </div>
                    </section>

                    <section className="dashboard-card dashboard-card--signals">
                        {signalBlocks.map((signal) => (
                            <div key={signal.title} className="dashboard-signal-card">
                                <div className="dashboard-signal-card__title">{signal.title}</div>
                                <div className="dashboard-signal-card__headline"><strong>{signal.value}</strong><span className={`dashboard-signal-card__badge ${signal.badgeClass}`}>{signal.badge}</span></div>
                                {typeof signal.progress === 'number' && (
                                    <div className="dashboard-signal-card__progress">
                                        <div
                                            className={`dashboard-signal-card__progress-fill dashboard-signal-card__progress-fill--${signal.progressDirection === 'negative' ? 'negative' : 'positive'}`}
                                            style={{ width: `${signal.progress}%` }}
                                        />
                                    </div>
                                )}
                                <p>{signal.note}</p>
                            </div>
                        ))}
                    </section>
                </div>
            </div>
        </div>
    );
}
