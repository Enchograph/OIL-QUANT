import { useAudiencePreference } from '../../audiencePreference';
import React, { useMemo, useState } from 'react';
import { aiAudienceOptions, dashboardThemeOptions, themeOptions, timezoneModeOptions } from '../../config/settings';
import { useTheme } from '../../theme';
import { TIMEZONE_PREFERENCES, useTimezone } from '../../timezone';

export default function SettingsView() {
    const {
        dashboardThemePreference,
        themePreference,
        setDashboardThemePreference,
        setThemePreference,
    } = useTheme();
    const { timezonePreference, resolvedTimezone, availableTimezones, setTimezonePreference } = useTimezone();
    const { audiencePreference, setAudiencePreference } = useAudiencePreference();
    const [timezoneQuery, setTimezoneQuery] = useState('');

    const timezoneMode = timezonePreference === TIMEZONE_PREFERENCES.BROWSER ? TIMEZONE_PREFERENCES.BROWSER : 'fixed';
    const filteredTimezones = useMemo(() => {
        const keyword = timezoneQuery.trim().toLowerCase();
        if (!keyword) {
            return availableTimezones;
        }
        return availableTimezones.filter((item) => item.toLowerCase().includes(keyword));
    }, [availableTimezones, timezoneQuery]);

    return (
        <div className="panel panel--page">
            <div className="section-heading">
                <h2>系统配置 (System Settings)</h2>
            </div>

            <div className="settings-group">
                <h3>User Analytical Perspective</h3>
                <div className="settings-card">
                    <div className="settings-theme-block settings-theme-block--compact">
                        <div className="settings-card__heading">
                            <strong>用户分析视角</strong>
                        </div>
                        <div className="theme-segmented" role="group" aria-label="用户分析视角">
                            {aiAudienceOptions.map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    className={`theme-segmented__item${audiencePreference === option.value ? ' is-active' : ''}`}
                                    aria-pressed={audiencePreference === option.value}
                                    onClick={() => setAudiencePreference(option.value)}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            </div>

            <div className="settings-group">
                <h3>Timezone</h3>
                <div className="settings-card">
                    <div className="settings-theme-block settings-theme-block--compact">
                        <div className="settings-card__heading">
                            <strong>前端全局时区</strong>
                        </div>
                        <div className="theme-segmented" role="group" aria-label="时区模式">
                            {timezoneModeOptions.map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    className={`theme-segmented__item${timezoneMode === option.value ? ' is-active' : ''}`}
                                    aria-pressed={timezoneMode === option.value}
                                    onClick={() => {
                                        if (option.value === TIMEZONE_PREFERENCES.BROWSER) {
                                            setTimezonePreference(TIMEZONE_PREFERENCES.BROWSER);
                                            return;
                                        }
                                        setTimezonePreference(resolvedTimezone);
                                    }}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                    </div>
                    {timezoneMode === 'fixed' ? (
                        <>
                            <label>
                                <span>检索时区</span>
                                <input
                                    type="text"
                                    value={timezoneQuery}
                                    placeholder="例如 America/New_York"
                                    onChange={(event) => setTimezoneQuery(event.target.value)}
                                />
                            </label>
                            <label>
                                <span>固定时区</span>
                                <select value={resolvedTimezone} onChange={(event) => setTimezonePreference(event.target.value)}>
                                    {filteredTimezones.map((item) => (
                                        <option key={item} value={item}>
                                            {item}
                                        </option>
                                    ))}
                                </select>
                            </label>
                        </>
                    ) : null}
                </div>
            </div>

            <div className="settings-group">
                <h3>Appearance</h3>
                <div className="settings-card">
                    <div className="settings-theme-block settings-theme-block--compact">
                        <div className="settings-card__heading">
                            <strong>主题模式</strong>
                        </div>
                        <div className="theme-segmented" role="group" aria-label="主题模式">
                            {themeOptions.map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    className={`theme-segmented__item${themePreference === option.value ? ' is-active' : ''}`}
                                    aria-pressed={themePreference === option.value}
                                    onClick={() => setThemePreference(option.value)}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                    </div>
                    <div className="settings-theme-block settings-theme-block--compact">
                        <div className="settings-card__heading">
                            <strong>仪表盘主题</strong>
                            <span>默认独立深色，也可跟随全站。</span>
                        </div>
                        <div className="theme-segmented" role="group" aria-label="仪表盘主题">
                            {dashboardThemeOptions.map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    className={`theme-segmented__item${dashboardThemePreference === option.value ? ' is-active' : ''}`}
                                    aria-pressed={dashboardThemePreference === option.value}
                                    onClick={() => setDashboardThemePreference(option.value)}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
