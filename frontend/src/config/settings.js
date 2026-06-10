import { AUDIENCE_PREFERENCES, AUDIENCE_PREFERENCE_STORAGE_KEY } from '../audiencePreference';
import { DASHBOARD_THEME_PREFERENCES, THEME_PREFERENCES } from '../theme';
import { TIMEZONE_PREFERENCES } from '../timezone';

export const themeOptions = [
    { value: THEME_PREFERENCES.SYSTEM, label: '跟随系统' },
    { value: THEME_PREFERENCES.LIGHT, label: '浅色' },
    { value: THEME_PREFERENCES.DARK, label: '深色' },
];

export const dashboardThemeOptions = [
    { value: DASHBOARD_THEME_PREFERENCES.APP, label: '跟随全站' },
    { value: DASHBOARD_THEME_PREFERENCES.LIGHT, label: '浅色' },
    { value: DASHBOARD_THEME_PREFERENCES.DARK, label: '深色' },
];

export const resolvedThemeLabels = {
    light: '浅色',
    dark: '深色',
};

export const AI_AUDIENCE_STORAGE_KEY = AUDIENCE_PREFERENCE_STORAGE_KEY;
export const ADMIN_SESSION_STORAGE_KEY = 'citi-oil-platform-admin-session';

export const aiAudienceOptions = [
    { value: AUDIENCE_PREFERENCES.ENTERPRISE, label: '企业侧' },
    { value: AUDIENCE_PREFERENCES.BANK, label: '银行侧' },
];

export const timezoneModeOptions = [
    { value: TIMEZONE_PREFERENCES.BROWSER, label: '跟随浏览器' },
    { value: 'fixed', label: '固定时区' },
];
