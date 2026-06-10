import React from 'react';
import { chartRanges } from '../../dashboardLive';

export default function RangeToggle({ value, onChange, ranges = chartRanges }) {
    return (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {ranges.map((range) => (
                <button
                    key={range}
                    type="button"
                    className={`btn-this-week${value === range ? ' is-active' : ''}`}
                    onClick={() => onChange(range)}
                >
                    {range}
                </button>
            ))}
        </div>
    );
}
