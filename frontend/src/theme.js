import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

export const THEME_STORAGE_KEY = 'citi-oil-platform-theme-preference';
export const DASHBOARD_THEME_STORAGE_KEY = 'citi-oil-platform-dashboard-theme-preference';

export const THEME_PREFERENCES = {
    SYSTEM: 'system',
    LIGHT: 'light',
    DARK: 'dark',
};

export const DASHBOARD_THEME_PREFERENCES = {
    APP: 'app',
    LIGHT: 'light',
    DARK: 'dark',
};

const globalThemes = {
    light: {
        'color-scheme': 'light',
        'app-bg': '#dde6f2',
        'app-bg-gradient':
            'radial-gradient(circle at top left, rgba(15, 76, 168, 0.12), transparent 28%), linear-gradient(180deg, #ecf2f9 0%, #dbe6f1 100%)',
        'shell-shadow': '0 18px 48px rgba(15, 23, 42, 0.08)',
        'surface-sidebar': 'rgba(241, 246, 252, 0.92)',
        'surface-header': 'rgba(249, 251, 254, 0.9)',
        'surface-panel': 'rgba(248, 251, 255, 0.92)',
        'surface-panel-strong': '#ffffff',
        'surface-muted': '#edf3f9',
        'surface-input': '#ffffff',
        'surface-button': '#173f73',
        'surface-button-hover': '#0f315b',
        'surface-accent-soft': 'rgba(18, 87, 191, 0.1)',
        'border-subtle': '#d3dde9',
        'border-strong': '#bccbdb',
        'border-accent': '#1257bf',
        'text-primary': '#122033',
        'text-secondary': '#4f647d',
        'text-muted': '#6d8097',
        'text-inverse': '#f8fbff',
        'brand-primary': '#1257bf',
        'brand-primary-strong': '#0d47a1',
        'brand-primary-contrast': '#f8fbff',
        'brand-primary-soft': '#d9e7ff',
        'button-secondary-bg': 'transparent',
        'button-secondary-bg-hover': '#d9e7ff',
        'button-secondary-bg-active': '#1257bf',
        'button-secondary-border': '#bccbdb',
        'button-secondary-border-hover': '#1257bf',
        'button-secondary-border-active': '#1257bf',
        'button-secondary-text': '#122033',
        'button-secondary-text-hover': '#0d47a1',
        'button-secondary-text-active': '#f8fbff',
        'status-success': '#0d8a60',
        'status-success-soft': '#dff7ed',
        'status-danger': '#c24a3a',
        'status-danger-soft': '#fde8e5',
        'status-warning': '#b86a17',
        'status-warning-soft': '#fff0dd',
        'status-neutral': '#60748c',
        'table-row-hover': '#e9f1fb',
        'chat-user-avatar-bg': '#173f73',
        'chat-user-avatar-border': '#173f73',
        'chat-ai-avatar-bg': '#e7f0ff',
        'chat-ai-avatar-border': '#bfd2f6',
        'chat-ai-avatar-text': '#1257bf',
        'chart-grid': '#d5deea',
        'chart-axis': '#61758d',
        'chart-tooltip-bg': '#ffffff',
        'chart-tooltip-border': '#c7d4e4',
        'chart-forecast-fill': '#d8e8ff',
        'chart-forecast-line': '#1257bf',
        'chart-historical-line': '#122033',
        'chart-reference': '#8799ad',
        'tag-high-bg': '#fde8e5',
        'tag-high-border': '#f2c3bc',
        'tag-high-text': '#a53c2d',
        'tag-neutral-bg': '#fff0dd',
        'tag-neutral-border': '#f4d3a4',
        'tag-neutral-text': '#9b5a12',
    },
    dark: {
        'color-scheme': 'dark',
        'app-bg': '#07111d',
        'app-bg-gradient':
            'radial-gradient(circle at top left, rgba(38, 102, 204, 0.22), transparent 28%), linear-gradient(180deg, #09121f 0%, #07111d 100%)',
        'shell-shadow': '0 18px 48px rgba(0, 0, 0, 0.3)',
        'surface-sidebar': 'rgba(10, 20, 34, 0.92)',
        'surface-header': 'rgba(8, 16, 30, 0.9)',
        'surface-panel': 'rgba(9, 18, 31, 0.92)',
        'surface-panel-strong': '#0d1827',
        'surface-muted': '#132235',
        'surface-input': '#0e1928',
        'surface-button': '#2d6cdf',
        'surface-button-hover': '#3b7bf0',
        'surface-accent-soft': 'rgba(45, 108, 223, 0.16)',
        'border-subtle': '#223449',
        'border-strong': '#2f465f',
        'border-accent': '#5d94ff',
        'text-primary': '#e7edf6',
        'text-secondary': '#a5b4c7',
        'text-muted': '#7f92aa',
        'text-inverse': '#07111d',
        'brand-primary': '#5d94ff',
        'brand-primary-strong': '#8db5ff',
        'brand-primary-contrast': '#07111d',
        'brand-primary-soft': 'rgba(93, 148, 255, 0.16)',
        'button-secondary-bg': 'rgba(19, 34, 53, 0.6)',
        'button-secondary-bg-hover': 'rgba(34, 52, 73, 0.92)',
        'button-secondary-bg-active': '#5d94ff',
        'button-secondary-border': '#2f465f',
        'button-secondary-border-hover': '#5d94ff',
        'button-secondary-border-active': '#5d94ff',
        'button-secondary-text': '#e7edf6',
        'button-secondary-text-hover': '#f4f8ff',
        'button-secondary-text-active': '#07111d',
        'status-success': '#3dc58f',
        'status-success-soft': 'rgba(15, 114, 78, 0.18)',
        'status-danger': '#ff7b6d',
        'status-danger-soft': 'rgba(138, 38, 28, 0.22)',
        'status-warning': '#f0ad4e',
        'status-warning-soft': 'rgba(145, 94, 23, 0.2)',
        'status-neutral': '#91a4bc',
        'table-row-hover': '#13253a',
        'chat-user-avatar-bg': '#5d94ff',
        'chat-user-avatar-border': '#5d94ff',
        'chat-ai-avatar-bg': '#13253a',
        'chat-ai-avatar-border': '#2f465f',
        'chat-ai-avatar-text': '#8db5ff',
        'chart-grid': '#25384f',
        'chart-axis': '#8ca0b8',
        'chart-tooltip-bg': '#08111d',
        'chart-tooltip-border': '#33485f',
        'chart-forecast-fill': 'rgba(27, 71, 148, 0.35)',
        'chart-forecast-line': '#6fa4ff',
        'chart-historical-line': '#edf4ff',
        'chart-reference': '#6f849b',
        'tag-high-bg': 'rgba(138, 38, 28, 0.22)',
        'tag-high-border': 'rgba(255, 123, 109, 0.34)',
        'tag-high-text': '#ff9b90',
        'tag-neutral-bg': 'rgba(145, 94, 23, 0.2)',
        'tag-neutral-border': 'rgba(240, 173, 78, 0.32)',
        'tag-neutral-text': '#f4bf74',
    },
};

const dashboardThemes = {
    light: {
        'dashboard-bg': 'linear-gradient(180deg, #f7f9fc 0%, #edf2f7 100%)',
        'dashboard-surface': 'rgba(250, 252, 255, 0.92)',
        'dashboard-surface-strong': '#f3f6fa',
        'dashboard-surface-elevated': 'linear-gradient(180deg, rgba(249, 251, 254, 0.98), rgba(241, 246, 251, 0.98))',
        'dashboard-glow': 'radial-gradient(circle at top right, rgba(18, 87, 191, 0.08), transparent 22%), radial-gradient(circle at left top, rgba(184, 106, 23, 0.06), transparent 28%)',
        'dashboard-border': '#d5dfeb',
        'dashboard-grid-axis': '#d2dce8',
        'dashboard-text-primary': '#112033',
        'dashboard-text-secondary': '#52657d',
        'dashboard-text-muted': '#7a8a9d',
        'dashboard-text-accent': '#1257bf',
        'dashboard-shell-shadow': '0 16px 40px rgba(15, 23, 42, 0.06)',
        'dashboard-control-bg': 'rgba(255, 255, 255, 0.82)',
        'dashboard-control-bg-hover': '#e3ebf7',
        'dashboard-control-bg-active': '#1257bf',
        'dashboard-control-border': '#c7d4e4',
        'dashboard-control-border-hover': '#8baccf',
        'dashboard-control-border-active': '#1257bf',
        'dashboard-control-text': '#213247',
        'dashboard-control-text-hover': '#0d47a1',
        'dashboard-control-text-active': '#f8fbff',
        'dashboard-chart-fill': '#e7edf4',
        'dashboard-chart-ma60-top': 'rgba(0, 0, 0, 0)',
        'dashboard-chart-ma60-bottom': 'rgba(0, 0, 0, 0)',
        'dashboard-chart-ma60-line': 'rgba(0, 0, 0, 0)',
        'dashboard-chart-line-primary': '#17314d',
        'dashboard-chart-line-primary-width': '1',
        'dashboard-chart-line-brand': '#1257bf',
        'dashboard-chart-line-warning': '#b8772b',
        'dashboard-chart-tooltip-bg': '#f8fbff',
        'dashboard-chart-tooltip-border': '#ced9e8',
        'dashboard-tooltip-shadow': '0 10px 24px rgba(15, 23, 42, 0.1)',
        'dashboard-signal-danger-bg': 'rgba(194, 74, 58, 0.08)',
        'dashboard-signal-danger-border': 'rgba(194, 74, 58, 0.24)',
        'dashboard-signal-danger-text': '#a53c2d',
        'dashboard-signal-warning-bg': 'rgba(184, 106, 23, 0.09)',
        'dashboard-signal-warning-border': 'rgba(184, 106, 23, 0.26)',
        'dashboard-signal-warning-text': '#9b5a12',
        'dashboard-signal-positive-bg': 'rgba(13, 138, 96, 0.08)',
        'dashboard-signal-positive-border': 'rgba(13, 138, 96, 0.24)',
        'dashboard-signal-positive-text': '#0b7a55',
    },
    dark: {
        'dashboard-bg': 'linear-gradient(180deg, #07111f 0%, #0c1728 100%)',
        'dashboard-surface': 'rgba(8, 16, 30, 0.88)',
        'dashboard-surface-strong': '#050b16',
        'dashboard-surface-elevated': 'linear-gradient(180deg, rgba(7, 34, 53, 0.96), rgba(3, 11, 22, 0.96))',
        'dashboard-glow': 'radial-gradient(circle at top right, rgba(93, 148, 255, 0.12), transparent 24%)',
        'dashboard-border': '#243246',
        'dashboard-grid-axis': '#334155',
        'dashboard-text-primary': '#e2e8f0',
        'dashboard-text-secondary': '#94a3b8',
        'dashboard-text-muted': '#64748b',
        'dashboard-text-accent': '#5eead4',
        'dashboard-shell-shadow': '0 16px 40px rgba(2, 6, 23, 0.28)',
        'dashboard-control-bg': 'rgba(10, 20, 34, 0.84)',
        'dashboard-control-bg-hover': '#17314d',
        'dashboard-control-bg-active': '#5d94ff',
        'dashboard-control-border': '#334155',
        'dashboard-control-border-hover': '#5d94ff',
        'dashboard-control-border-active': '#8db5ff',
        'dashboard-control-text': '#dbe7f5',
        'dashboard-control-text-hover': '#f8fbff',
        'dashboard-control-text-active': '#07111d',
        'dashboard-chart-fill': '#1e293b',
        'dashboard-chart-line-primary': '#f8fafc',
        'dashboard-chart-line-primary-width': '2',
        'dashboard-chart-line-brand': '#5d94ff',
        'dashboard-chart-line-warning': '#f0ad4e',
        'dashboard-chart-tooltip-bg': '#020617',
        'dashboard-chart-tooltip-border': '#334155',
        'dashboard-tooltip-shadow': '0 8px 18px rgba(2, 6, 23, 0.32)',
        'dashboard-signal-danger-bg': 'rgba(127, 29, 29, 0.35)',
        'dashboard-signal-danger-border': 'rgba(255, 123, 109, 0.35)',
        'dashboard-signal-danger-text': '#ff9b90',
        'dashboard-signal-warning-bg': 'rgba(120, 53, 15, 0.35)',
        'dashboard-signal-warning-border': 'rgba(240, 173, 78, 0.35)',
        'dashboard-signal-warning-text': '#f4bf74',
        'dashboard-signal-positive-bg': 'rgba(6, 78, 59, 0.35)',
        'dashboard-signal-positive-border': 'rgba(61, 197, 143, 0.35)',
        'dashboard-signal-positive-text': '#76e0b0',
    },
};

const ThemeContext = createContext(null);

function resolveTheme(preference, systemTheme) {
    if (preference === THEME_PREFERENCES.LIGHT) {
        return 'light';
    }

    if (preference === THEME_PREFERENCES.DARK) {
        return 'dark';
    }

    return systemTheme;
}

function getSystemTheme() {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
        return 'light';
    }

    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function getStoredPreference() {
    if (typeof window === 'undefined') {
        return THEME_PREFERENCES.SYSTEM;
    }

    const storedPreference = window.localStorage.getItem(THEME_STORAGE_KEY);

    if (storedPreference === THEME_PREFERENCES.LIGHT || storedPreference === THEME_PREFERENCES.DARK) {
        return storedPreference;
    }

    return THEME_PREFERENCES.SYSTEM;
}

function resolveDashboardTheme(preference, appTheme) {
    if (preference === DASHBOARD_THEME_PREFERENCES.LIGHT) {
        return 'light';
    }

    if (preference === DASHBOARD_THEME_PREFERENCES.APP) {
        return appTheme;
    }

    return 'dark';
}

function getStoredDashboardPreference() {
    if (typeof window === 'undefined') {
        return DASHBOARD_THEME_PREFERENCES.DARK;
    }

    const storedPreference = window.localStorage.getItem(DASHBOARD_THEME_STORAGE_KEY);

    if (
        storedPreference === DASHBOARD_THEME_PREFERENCES.APP
        || storedPreference === DASHBOARD_THEME_PREFERENCES.LIGHT
        || storedPreference === DASHBOARD_THEME_PREFERENCES.DARK
    ) {
        return storedPreference;
    }

    return DASHBOARD_THEME_PREFERENCES.DARK;
}

function applyVariables(target, variables) {
    Object.entries(variables).forEach(([name, value]) => {
        target.style.setProperty(`--${name}`, value);
    });
}

export function ThemeProvider({ children }) {
    const [themePreference, setThemePreference] = useState(getStoredPreference);
    const [dashboardThemePreference, setDashboardThemePreference] = useState(getStoredDashboardPreference);
    const [systemTheme, setSystemTheme] = useState(getSystemTheme);

    useEffect(() => {
        if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
            return undefined;
        }

        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        const handleChange = (event) => {
            setSystemTheme(event.matches ? 'dark' : 'light');
        };

        handleChange(mediaQuery);
        mediaQuery.addEventListener('change', handleChange);

        return () => mediaQuery.removeEventListener('change', handleChange);
    }, []);

    const resolvedTheme = useMemo(
        () => resolveTheme(themePreference, systemTheme),
        [themePreference, systemTheme],
    );
    const resolvedDashboardTheme = useMemo(
        () => resolveDashboardTheme(dashboardThemePreference, resolvedTheme),
        [dashboardThemePreference, resolvedTheme],
    );

    useEffect(() => {
        if (typeof window === 'undefined') {
            return;
        }

        if (themePreference === THEME_PREFERENCES.SYSTEM) {
            window.localStorage.removeItem(THEME_STORAGE_KEY);
        } else {
            window.localStorage.setItem(THEME_STORAGE_KEY, themePreference);
        }
    }, [themePreference]);

    useEffect(() => {
        if (typeof window === 'undefined') {
            return;
        }

        window.localStorage.setItem(DASHBOARD_THEME_STORAGE_KEY, dashboardThemePreference);
    }, [dashboardThemePreference]);

    useEffect(() => {
        if (typeof document === 'undefined') {
            return;
        }

        const root = document.documentElement;
        root.dataset.theme = resolvedTheme;
        root.dataset.dashboardTheme = resolvedDashboardTheme;
        root.style.colorScheme = globalThemes[resolvedTheme]['color-scheme'];
        applyVariables(root, globalThemes[resolvedTheme]);
        applyVariables(root, dashboardThemes[resolvedDashboardTheme]);
    }, [resolvedDashboardTheme, resolvedTheme]);

    const value = useMemo(
        () => ({
            dashboardThemePreference,
            themePreference,
            resolvedDashboardTheme,
            resolvedTheme,
            setDashboardThemePreference,
            setThemePreference,
        }),
        [dashboardThemePreference, resolvedDashboardTheme, resolvedTheme, themePreference],
    );

    return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
    const context = useContext(ThemeContext);

    if (!context) {
        throw new Error('useTheme must be used within ThemeProvider');
    }

    return context;
}
