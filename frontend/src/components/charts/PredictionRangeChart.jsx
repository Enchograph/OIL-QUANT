import React from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import DashboardTooltip from './DashboardTooltip';
import SemanticRangeChartFrame from './SemanticRangeChartFrame';
import { formatChartAxisTime, formatChartTooltipTime } from '../../utils/formatters';

export function resolvePredictionTooltipRows(point) {
    if (!point) {
        return [];
    }

    const hasProjection = point.prediction !== null && point.prediction !== undefined;
    const rows = [];

    if (!hasProjection && point.historical !== null && point.historical !== undefined) {
        rows.push({ label: 'Historical', value: point.historical, valueClassName: 'historical' });
    }

    if (point.prediction !== null && point.prediction !== undefined) {
        rows.push({ label: 'Prediction', value: point.prediction, valueClassName: 'prediction' });
    }

    if (point.upperBound !== null && point.upperBound !== undefined) {
        rows.push({ label: 'Upper Bound', value: point.upperBound, valueClassName: 'upper-bound' });
    }

    if (point.lowerBound !== null && point.lowerBound !== undefined) {
        rows.push({ label: 'Lower Bound', value: point.lowerBound, valueClassName: 'lower-bound' });
    }

    return rows;
}

function PredictionTooltip({ active, payload, label, range, timeZone }) {
    return (
        <DashboardTooltip
            active={active}
            payload={payload}
            label={label}
            title={(_, __, currentLabel) => formatChartTooltipTime(currentLabel, range, timeZone)}
            rows={(point) => resolvePredictionTooltipRows(point)}
        />
    );
}

export default function PredictionRangeChart({
    renderKey,
    range,
    chartData,
    timeZone,
    historicalDataKey = 'historical',
    predictionDataKey = 'prediction',
    upperBoundDataKey = 'upperBound',
    lowerBoundDataKey = 'lowerBound',
    referenceX,
}) {
    return (
        <SemanticRangeChartFrame key={renderKey ?? range} range={range}>
            <ResponsiveContainer key={renderKey ?? range} width="100%" height="100%" minWidth={0} minHeight={280}>
                <ComposedChart key={renderKey ?? range} data={chartData} margin={{ top: 40, right: 24, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--chart-grid)" />
                    <XAxis
                        dataKey="dateMs"
                        type="number"
                        scale="time"
                        domain={['dataMin', 'dataMax']}
                        tick={{ fontSize: 10, fill: 'var(--chart-axis)' }}
                        tickLine={false}
                        minTickGap={range === '1D' ? 36 : 24}
                        tickFormatter={(value) => formatChartAxisTime(value, range, timeZone)}
                    />
                    <YAxis
                        domain={['dataMin - 5', 'dataMax + 5']}
                        tick={{ fontSize: 10, fill: 'var(--chart-axis)' }}
                        axisLine={false}
                        tickLine={false}
                    />
                    <Tooltip
                        content={<PredictionTooltip range={range} timeZone={timeZone} />}
                    />
                    <Area
                        type="monotone"
                        dataKey={upperBoundDataKey}
                        stroke="none"
                        fill="var(--chart-forecast-fill)"
                        fillOpacity={0.7}
                    />
                    <Area
                        type="monotone"
                        dataKey={lowerBoundDataKey}
                        stroke="none"
                        fill="var(--surface-panel-strong)"
                        fillOpacity={1}
                    />
                    <Line
                        type="stepAfter"
                        dataKey={historicalDataKey}
                        stroke="var(--chart-historical-line)"
                        strokeWidth={2}
                        dot={false}
                    />
                    <Line
                        type="monotone"
                        dataKey={predictionDataKey}
                        stroke="var(--chart-forecast-line)"
                        strokeWidth={2}
                        strokeDasharray="5 5"
                        dot={false}
                    />
                    {referenceX ? (
                        <ReferenceLine
                            x={new Date(referenceX).getTime()}
                            stroke="var(--chart-reference)"
                            strokeDasharray="3 3"
                            ifOverflow="extendDomain"
                            label={{ position: 'top', value: 'TODAY', fill: 'var(--chart-axis)', fontSize: 10 }}
                        />
                    ) : null}
                </ComposedChart>
            </ResponsiveContainer>
        </SemanticRangeChartFrame>
    );
}
