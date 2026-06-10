import React from 'react';
import { formatDashboardTooltipValue } from '../../utils/formatters';

export default function DashboardTooltip({ active, payload, label, title, rows }) {
    if (!active || !payload?.length) {
        return null;
    }

    const point = payload[0]?.payload ?? {};
    const resolvedRows = rows(point, payload, label).filter((row) => row.value !== null && row.value !== undefined);

    if (!resolvedRows.length) {
        return null;
    }

    const resolvedTitle = typeof title === 'function' ? title(point, payload, label) : title;

    return (
        <div className="dashboard-tooltip">
            {resolvedTitle ? <div className="dashboard-tooltip__title">{resolvedTitle}</div> : null}
            <div className="dashboard-tooltip__rows">
                {resolvedRows.map((row) => (
                    <div key={row.label} className="dashboard-tooltip__row">
                        <span>{row.label}</span>
                        <strong className={row.valueClassName ?? ''}>{formatDashboardTooltipValue(row.value)}</strong>
                    </div>
                ))}
            </div>
        </div>
    );
}
