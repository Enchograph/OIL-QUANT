import React, { useMemo } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

function QaLineChart({ chart }) {
    const points = chart?.data?.points || [];
    const chartData = useMemo(
        () => points.map((item, index) => ({ ...item, index, historical: item.series === '历史' ? item.value : null, prediction: item.series === '预测' ? item.value : null })),
        [points],
    );

    if (!chartData.length) {
        return <div className="qa-chart-card__empty">当前图表数据不足</div>;
    }

    return (
        <div className="qa-line-chart">
            <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={124}>
                <ComposedChart data={chartData} margin={{ top: 10, right: 4, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--chart-grid)" />
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--chart-axis)' }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: 'var(--chart-axis)' }} tickLine={false} axisLine={false} width={34} />
                    <Tooltip
                        formatter={(value) => (typeof value === 'number' ? value.toFixed(2) : value)}
                        contentStyle={{
                            backgroundColor: 'var(--chart-tooltip-bg)',
                            border: '1px solid var(--chart-tooltip-border)',
                            borderRadius: 0,
                            fontSize: '12px',
                        }}
                    />
                    <Line type="monotone" dataKey="historical" stroke="var(--chart-historical-line)" strokeWidth={2} dot={false} connectNulls />
                    <Line type="monotone" dataKey="prediction" stroke="var(--chart-forecast-line)" strokeWidth={2} dot={false} connectNulls strokeDasharray="4 4" />
                </ComposedChart>
            </ResponsiveContainer>
        </div>
    );
}

function QaBarsChart({ chart }) {
    const items = chart?.data?.items || [];

    if (!items.length) {
        return <div className="qa-chart-card__empty">当前图表数据不足</div>;
    }

    return (
        <div className="qa-bars-chart">
            <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={124}>
                <BarChart data={items} layout="vertical" margin={{ top: 0, right: 6, left: 6, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--chart-grid)" />
                    <XAxis type="number" tick={{ fontSize: 10, fill: 'var(--chart-axis)' }} tickLine={false} axisLine={false} />
                    <YAxis
                        dataKey="label"
                        type="category"
                        tick={{ fontSize: 10, fill: 'var(--chart-axis)' }}
                        tickLine={false}
                        axisLine={false}
                        width={84}
                    />
                    <Tooltip
                        formatter={(value) => (typeof value === 'number' ? value.toFixed(2) : value)}
                        contentStyle={{
                            backgroundColor: 'var(--chart-tooltip-bg)',
                            border: '1px solid var(--chart-tooltip-border)',
                            borderRadius: 0,
                            fontSize: '12px',
                        }}
                    />
                    <Bar dataKey="value" radius={0}>
                        {items.map((item) => (
                            <Cell
                                key={`${chart.id}-${item.label}`}
                                fill={Number(item.value) >= 0 ? 'var(--brand-primary)' : 'var(--status-danger)'}
                            />
                        ))}
                    </Bar>
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
}

function QaSplitMeter({ chart }) {
    const segments = chart?.data?.segments || [];

    if (!segments.length) {
        return <div className="qa-chart-card__empty">当前图表数据不足</div>;
    }

    return (
        <div className="qa-split-meter">
            <div className="qa-split-meter__bar">
                {segments.map((segment) => (
                    <div
                        key={`${chart.id}-${segment.label}`}
                        className={`qa-split-meter__segment is-${segment.tone || 'neutral'}`}
                        style={{ width: `${Math.max(Number(segment.value) || 0, 8)}%` }}
                    />
                ))}
            </div>
            <div className="qa-split-meter__legend">
                {segments.map((segment) => (
                    <div key={`${chart.id}-${segment.label}-legend`} className="qa-split-meter__item">
                        <span>{segment.label}</span>
                        <strong>{Number(segment.value || 0).toFixed(1)}%</strong>
                    </div>
                ))}
            </div>
        </div>
    );
}

function QaStatStrip({ chart }) {
    const stats = chart?.data?.stats || [];

    if (!stats.length) {
        return <div className="qa-chart-card__empty">当前图表数据不足</div>;
    }

    return (
        <div className="qa-stat-strip">
            {stats.map((item) => (
                <div key={`${chart.id}-${item.label}`} className={`qa-stat-strip__item is-${item.tone || 'neutral'}`}>
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                </div>
            ))}
        </div>
    );
}

function QaContextGrid({ chart }) {
    const items = chart?.data?.items || [];

    if (!items.length) {
        return <div className="qa-chart-card__empty">当前图表数据不足</div>;
    }

    return (
        <div className="qa-context-grid">
            {items.map((item) => (
                <div key={`${chart.id}-${item.label}`} className={`qa-context-grid__item is-${item.status || 'ready'}`}>
                    <span className="qa-context-grid__label">{item.label}</span>
                    <strong className="qa-context-grid__detail">{item.detail}</strong>
                    {item.timestamp ? <span className="qa-context-grid__meta">{item.timestamp}</span> : null}
                </div>
            ))}
        </div>
    );
}

function QaChartBody({ chart }) {
    switch (chart?.kind) {
    case 'line':
        return <QaLineChart chart={chart} />;
    case 'bars':
        return <QaBarsChart chart={chart} />;
    case 'split-meter':
        return <QaSplitMeter chart={chart} />;
    case 'stat-strip':
        return <QaStatStrip chart={chart} />;
    case 'context-grid':
        return <QaContextGrid chart={chart} />;
    default:
        return <div className="qa-chart-card__empty">暂不支持的图表类型</div>;
    }
}

export function QaChartCard({ chart, className = '' }) {
    return (
        <section className={`qa-chart-card qa-chart-card--${chart.kind || 'unknown'} ${className}`.trim()}>
            <header className="qa-chart-card__header">
                <div>
                    <strong>{chart.title}</strong>
                    {chart.subtitle ? <p>{chart.subtitle}</p> : null}
                </div>
            </header>
            <div className="qa-chart-card__body">
                <QaChartBody chart={chart} />
            </div>
            {chart.footnote ? <footer className="qa-chart-card__footnote">{chart.footnote}</footer> : null}
        </section>
    );
}

export default function QaBriefingCharts({ charts }) {
    if (!charts?.length) {
        return null;
    }

    return (
        <div className={`qa-chart-grid qa-chart-grid--count-${Math.min(charts.length, 4)}`}>
            {charts.map((chart) => (
                <QaChartCard key={chart.id || chart.title} chart={chart} />
            ))}
        </div>
    );
}
