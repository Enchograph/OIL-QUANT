export const DEFAULT_TIMEZONE = 'UTC';

const FALLBACK_TIMEZONES = [
    'UTC',
    'Asia/Shanghai',
    'Asia/Tokyo',
    'Asia/Singapore',
    'Asia/Dubai',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'America/Sao_Paulo',
    'Australia/Sydney',
];

function pad2(value) {
    return String(value).padStart(2, '0');
}

export function getBrowserTimeZone() {
    try {
        const value = Intl.DateTimeFormat().resolvedOptions().timeZone;
        return typeof value === 'string' && value.trim() ? value : DEFAULT_TIMEZONE;
    } catch {
        return DEFAULT_TIMEZONE;
    }
}

export function getAvailableTimezones() {
    if (typeof Intl.supportedValuesOf === 'function') {
        const values = Intl.supportedValuesOf('timeZone');
        return Array.from(new Set([DEFAULT_TIMEZONE, ...values]));
    }
    return Array.from(new Set([DEFAULT_TIMEZONE, getBrowserTimeZone(), ...FALLBACK_TIMEZONES]));
}

export function isValidTimeZone(value) {
    if (!value || typeof value !== 'string') {
        return false;
    }
    try {
        new Intl.DateTimeFormat('zh-CN', { timeZone: value }).format(new Date());
        return true;
    } catch {
        return false;
    }
}

export function resolveTimeZone(preference) {
    if (preference === 'browser') {
        const browserTimeZone = getBrowserTimeZone();
        return isValidTimeZone(browserTimeZone) ? browserTimeZone : DEFAULT_TIMEZONE;
    }
    return isValidTimeZone(preference) ? preference : DEFAULT_TIMEZONE;
}

export function formatDatePartsToKey(parts) {
    if (!parts?.year || !parts?.month || !parts?.day) {
        return '';
    }
    return `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`;
}

export function getTimeZoneDateParts(value, timeZone = DEFAULT_TIMEZONE) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) {
        return {
            year: null,
            month: null,
            day: null,
        };
    }

    const formatter = new Intl.DateTimeFormat('en-CA', {
        timeZone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    });
    const parts = formatter.formatToParts(date);
    const getPart = (type) => Number(parts.find((item) => item.type === type)?.value ?? NaN);

    return {
        year: getPart('year'),
        month: getPart('month'),
        day: getPart('day'),
    };
}

export function getDateKeyInTimeZone(value, timeZone = DEFAULT_TIMEZONE) {
    return formatDatePartsToKey(getTimeZoneDateParts(value, timeZone));
}

export function formatDateTimeInTimeZone(value, timeZone = DEFAULT_TIMEZONE, options = {}) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '';
    }

    return new Intl.DateTimeFormat('zh-CN', {
        timeZone,
        hour12: false,
        ...options,
    }).format(date);
}

export function getShortTimeZoneLabel(value, timeZone = DEFAULT_TIMEZONE) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '';
    }
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone,
        timeZoneName: 'short',
        hour: '2-digit',
    }).formatToParts(date);
    return parts.find((item) => item.type === 'timeZoneName')?.value ?? '';
}

export function formatDateTimeWithZone(value, timeZone = DEFAULT_TIMEZONE) {
    const base = formatDateTimeInTimeZone(value, timeZone, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    });
    const zoneLabel = getShortTimeZoneLabel(value, timeZone);
    return zoneLabel ? `${base} ${zoneLabel}` : base;
}

export function formatClockTimeInTimeZone(value, timeZone = DEFAULT_TIMEZONE) {
    const base = formatDateTimeInTimeZone(value, timeZone, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
    const zoneLabel = getShortTimeZoneLabel(value, timeZone);
    return zoneLabel ? `${base} ${zoneLabel}` : base;
}

export function parseDateKeyToPickerDate(value) {
    const [year, month, day] = String(value || '').split('-').map(Number);
    if (!year || !month || !day) {
        return new Date(Number.NaN);
    }
    return new Date(year, month - 1, day, 12, 0, 0, 0);
}

export function pickerDateToDateKey(value) {
    if (!(value instanceof Date) || Number.isNaN(value.getTime())) {
        return '';
    }
    return `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}`;
}

export function getTodayDateKey(timeZone = DEFAULT_TIMEZONE, now = new Date()) {
    return getDateKeyInTimeZone(now, timeZone);
}

export function getTodayPickerDate(timeZone = DEFAULT_TIMEZONE, now = new Date()) {
    return parseDateKeyToPickerDate(getTodayDateKey(timeZone, now));
}
