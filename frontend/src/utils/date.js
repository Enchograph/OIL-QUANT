export function formatDateKey(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

export function parseDateKey(value) {
    const [year, month, day] = value.split('-').map(Number);
    return new Date(year, month - 1, day, 12, 0, 0, 0);
}

export function formatDateLabel(value) {
    const date = parseDateKey(value);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}.${month}.${day}`;
}

export function getMonthStart(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
}

export function shiftMonth(date, offset) {
    return new Date(date.getFullYear(), date.getMonth() + offset, 1);
}

export function setMonthParts(date, year, monthIndex) {
    return new Date(year, monthIndex, 1);
}

export function normalizeDateRange(range) {
    if (range.start <= range.end) {
        return range;
    }

    return {
        start: range.end,
        end: range.start,
    };
}
