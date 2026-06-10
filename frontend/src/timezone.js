import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { DEFAULT_TIMEZONE, getAvailableTimezones, getBrowserTimeZone, resolveTimeZone } from './utils/timezone';

export const TIMEZONE_STORAGE_KEY = 'citi-oil-platform-timezone-preference';

export const TIMEZONE_PREFERENCES = {
    BROWSER: 'browser',
};

const TimezoneContext = createContext(null);

function getStoredTimezonePreference() {
    if (typeof window === 'undefined') {
        return TIMEZONE_PREFERENCES.BROWSER;
    }
    const stored = window.localStorage.getItem(TIMEZONE_STORAGE_KEY);
    return stored || TIMEZONE_PREFERENCES.BROWSER;
}

function buildTimezoneLabel(preference, resolvedTimezone) {
    if (preference === TIMEZONE_PREFERENCES.BROWSER) {
        return `跟随浏览器 (${resolvedTimezone})`;
    }
    return resolvedTimezone || DEFAULT_TIMEZONE;
}

export function TimezoneProvider({ children }) {
    const [timezonePreference, setTimezonePreference] = useState(getStoredTimezonePreference);
    const availableTimezones = useMemo(() => getAvailableTimezones(), []);
    const browserTimezone = useMemo(() => getBrowserTimeZone(), []);
    const resolvedTimezone = useMemo(() => resolveTimeZone(timezonePreference), [timezonePreference]);

    useEffect(() => {
        if (typeof window === 'undefined') {
            return;
        }
        if (timezonePreference === TIMEZONE_PREFERENCES.BROWSER) {
            window.localStorage.removeItem(TIMEZONE_STORAGE_KEY);
            return;
        }
        window.localStorage.setItem(TIMEZONE_STORAGE_KEY, timezonePreference);
    }, [timezonePreference]);

    const value = useMemo(
        () => ({
            timezonePreference,
            resolvedTimezone,
            timezoneLabel: buildTimezoneLabel(timezonePreference, resolvedTimezone),
            browserTimezone,
            availableTimezones,
            setTimezonePreference,
        }),
        [availableTimezones, browserTimezone, resolvedTimezone, timezonePreference],
    );

    return <TimezoneContext.Provider value={value}>{children}</TimezoneContext.Provider>;
}

export function useTimezone() {
    const context = useContext(TimezoneContext);
    if (!context) {
        throw new Error('useTimezone must be used within TimezoneProvider');
    }
    return context;
}
