import { formatDateTimeInTimeZone, formatDateTimeWithZone, getBrowserTimeZone, getTimeZoneDateParts } from './timezone';

function resolveFormatterTimeZone(timeZone) {
    return timeZone || getBrowserTimeZone();
}

export function formatDashboardTooltipValue(value) {
    if (value === null || value === undefined) {
        return null;
    }

    if (typeof value === 'number') {
        return value.toFixed(2);
    }

    return value;
}

export function formatSignedPercent(value) {
    const numericValue = Number(value || 0);
    return `${numericValue >= 0 ? '+' : ''}${numericValue.toFixed(2)}%`;
}

export function formatMetricDisplay(metric) {
    const numericValue = Number(metric?.value ?? 0);
    if (['WTI_Close', 'Brent_Close', 'HenryHub_NG', 'RBOB_Gasoline', 'WTI_Brent_Spread'].includes(metric?.id)) {
        return `$${numericValue.toFixed(2)}`;
    }
    if (metric?.id === 'Treasury_10Y_Yield') {
        return `${numericValue.toFixed(2)}%`;
    }
    return metric?.displayValue ?? numericValue.toFixed(2);
}

export function formatSourceTime(value, timeZone) {
    if (!value) {
        return 'N/A';
    }

    const formatted = formatDateTimeInTimeZone(value, resolveFormatterTimeZone(timeZone), {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short',
    });
    if (!formatted) {
        return value;
    }
    return formatted;
}

function formatChartTime(value, timeZone, options) {
    if (!value) {
        return '';
    }

    return formatDateTimeInTimeZone(value, resolveFormatterTimeZone(timeZone), options) || String(value);
}

export function formatChartAxisTime(value, range, timeZone) {
    switch (range) {
        case '1D':
            return formatChartTime(value, timeZone, {
                hour: '2-digit',
                minute: '2-digit',
            });
        case '1W':
            return formatChartTime(value, timeZone, {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
            });
        case '1M':
            return formatChartTime(value, timeZone, {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
            });
        case '3M':
            return formatChartTime(value, timeZone, {
                month: '2-digit',
                day: '2-digit',
            });
        case '1Y':
            return formatChartTime(value, timeZone, {
                year: '2-digit',
                month: '2-digit',
                day: '2-digit',
            });
        default:
            return formatChartTime(value, timeZone, {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
            });
    }
}

export function formatChartTooltipTime(value, range, timeZone) {
    switch (range) {
        case '1D':
        case '1W':
        case '1M':
            return formatChartTime(value, timeZone, {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                timeZoneName: 'short',
            });
        case '3M':
            return formatChartTime(value, timeZone, {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                timeZoneName: 'short',
            });
        case '1Y':
            return formatChartTime(value, timeZone, {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                timeZoneName: 'short',
            });
        default:
            return formatSourceTime(value, timeZone);
    }
}

export function getNewsPublishedCalendarParts(value, fallbackDate = '', timeZone) {
    if (value) {
        const parts = getTimeZoneDateParts(value, resolveFormatterTimeZone(timeZone));
        if (parts.year && parts.month && parts.day) {
            return parts;
        }
    }

    const matched = /^(\d{4})-(\d{2})-(\d{2})$/.exec(fallbackDate);
    if (!matched) {
        return {
            year: null,
            month: null,
            day: null,
        };
    }

    return {
        year: Number(matched[1]),
        month: Number(matched[2]),
        day: Number(matched[3]),
    };
}

export function formatNewsPublishedTime(value, fallbackDate = '', timeZone) {
    if (!value) {
        return fallbackDate || 'N/A';
    }

    const formatted = formatDateTimeWithZone(value, resolveFormatterTimeZone(timeZone));
    if (!formatted) {
        return fallbackDate || value;
    }
    return formatted;
}

export function formatAdminResult(result) {
    if (!result) {
        return '尚未执行';
    }
    return JSON.stringify(result, null, 2);
}

export function isAdminRunSuccessful(result) {
    if (!result) {
        return false;
    }

    if (result.success === true) {
        return true;
    }

    return result.status === 'success';
}
