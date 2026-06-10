import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import SettingsView from '../views/settings';
import { AudiencePreferenceProvider } from '../audiencePreference';
import {
    DASHBOARD_THEME_PREFERENCES,
    THEME_PREFERENCES,
    ThemeProvider,
    useTheme,
} from '../theme';
import { TimezoneProvider } from '../timezone';

function ThemeSwitchProbe() {
    const { setDashboardThemePreference, setThemePreference } = useTheme();

    return (
        <div>
            <button type="button" onClick={() => setThemePreference(THEME_PREFERENCES.LIGHT)}>
                切到浅色
            </button>
            <button type="button" onClick={() => setThemePreference(THEME_PREFERENCES.DARK)}>
                切到深色
            </button>
            <button type="button" onClick={() => setDashboardThemePreference(DASHBOARD_THEME_PREFERENCES.LIGHT)}>
                仪表盘切浅色
            </button>
            <button type="button" onClick={() => setDashboardThemePreference(DASHBOARD_THEME_PREFERENCES.APP)}>
                仪表盘跟随全站
            </button>
        </div>
    );
}

function renderWithProviders(element) {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
        root.render(element);
    });

    return {
        container,
        root,
        cleanup() {
            act(() => {
                root.unmount();
            });
            container.remove();
        },
    };
}

describe('dashboard theme', () => {
    const originalMatchMedia = window.matchMedia;

    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    });

    beforeEach(() => {
        window.localStorage.clear();
        window.matchMedia = jest.fn().mockImplementation(() => ({
            matches: false,
            addEventListener: jest.fn(),
            removeEventListener: jest.fn(),
        }));
    });

    afterEach(() => {
        document.documentElement.removeAttribute('data-theme');
        document.documentElement.removeAttribute('style');
        window.matchMedia = originalMatchMedia;
    });

    afterAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    });

    test('ThemeProvider 默认让仪表盘保持深色，并允许单独切换', () => {
        const view = renderWithProviders(
            <ThemeProvider>
                <ThemeSwitchProbe />
            </ThemeProvider>,
        );

        const buttons = view.container.querySelectorAll('button');

        act(() => {
            buttons[0].dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });

        expect(document.documentElement.dataset.theme).toBe('light');
        expect(document.documentElement.dataset.dashboardTheme).toBe('dark');
        expect(document.documentElement.style.getPropertyValue('--dashboard-chart-tooltip-bg')).toBe('#020617');
        expect(document.documentElement.style.getPropertyValue('--dashboard-bg')).toBe(
            'linear-gradient(180deg, #07111f 0%, #0c1728 100%)',
        );

        act(() => {
            buttons[2].dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });

        expect(document.documentElement.dataset.dashboardTheme).toBe('light');
        expect(document.documentElement.style.getPropertyValue('--dashboard-bg')).toBe(
            'linear-gradient(180deg, #f7f9fc 0%, #edf2f7 100%)',
        );
        expect(document.documentElement.style.getPropertyValue('--dashboard-chart-tooltip-bg')).toBe('#f8fbff');

        act(() => {
            buttons[3].dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });

        expect(document.documentElement.dataset.dashboardTheme).toBe('light');

        act(() => {
            buttons[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });

        expect(document.documentElement.dataset.theme).toBe('dark');
        expect(document.documentElement.dataset.dashboardTheme).toBe('dark');
        expect(document.documentElement.style.getPropertyValue('--dashboard-bg')).toBe(
            'linear-gradient(180deg, #07111f 0%, #0c1728 100%)',
        );

        view.cleanup();
    });

    test('设置页展示独立的仪表盘主题配置且默认深色', () => {
        const view = renderWithProviders(
            <AudiencePreferenceProvider>
                <ThemeProvider>
                    <TimezoneProvider>
                        <SettingsView />
                    </TimezoneProvider>
                </ThemeProvider>
            </AudiencePreferenceProvider>,
        );

        expect(view.container.textContent).toContain('仪表盘模式');
        expect(view.container.textContent).toContain('默认深色');
        expect(view.container.textContent).toContain('跟随全站');
        expect(view.container.textContent).toContain('浅色');
        expect(view.container.textContent).toContain('深色');

        view.cleanup();
    });
});
