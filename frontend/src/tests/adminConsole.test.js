import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import SettingsView from '../views/settings';
import AdminView from '../views/admin';
import { resolveAppEntryMode } from '../appMode';
import { AudiencePreferenceProvider } from '../audiencePreference';
import { ThemeProvider } from '../theme';
import { TimezoneProvider } from '../timezone';
import { ADMIN_SESSION_STORAGE_KEY } from '../config/settings';

function renderWithProviders(element) {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    act(() => {
        root.render(
            <ThemeProvider>
                <TimezoneProvider>
                    <AudiencePreferenceProvider>
                        {element}
                    </AudiencePreferenceProvider>
                </TimezoneProvider>
            </ThemeProvider>,
        );
    });

    return {
        container,
        cleanup() {
            act(() => {
                root.unmount();
            });
            container.remove();
        },
    };
}

function createJsonResponse(payload) {
    return {
        ok: true,
        json: async () => payload,
    };
}

describe('admin console routing', () => {
    let fetchMock;

    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    });

    beforeEach(() => {
        window.localStorage.clear();
        fetchMock = jest.fn();
        global.fetch = fetchMock;
    });

    afterEach(() => {
        window.localStorage.clear();
        jest.resetAllMocks();
    });

    afterAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    });

    test('设置页不再显示管理员能力', () => {
        const view = renderWithProviders(<SettingsView />);

        expect(view.container.textContent).not.toContain('管理密钥');
        expect(view.container.textContent).not.toContain('Admin Actions');
        expect(view.container.textContent).not.toContain('刷新行情数据');
        expect(view.container.textContent).not.toContain('旧版假数据调试');
        expect(view.container.textContent).not.toContain('真实后端数据');

        view.cleanup();
    });

    test('访问 /admin 时路由进入后台模式', () => {
        expect(resolveAppEntryMode('/admin')).toBe('admin');
        expect(resolveAppEntryMode('/admin/logs')).toBe('admin');
        expect(resolveAppEntryMode('/')).toBe('main');
    });

    test('管理页默认显示密码登录入口', () => {
        const view = renderWithProviders(<AdminView />);

        expect(view.container.textContent).toContain('管理页登录');
        expect(view.container.textContent).toContain('请输入后台密码');
        expect(view.container.querySelector('input[type="password"]')).not.toBeNull();

        view.cleanup();
    });

    test('管理页登录后只显示健康监控和程序动作区', async () => {
        window.localStorage.setItem(
            ADMIN_SESSION_STORAGE_KEY,
            JSON.stringify({
                token: 'session-token',
                expiresAt: new Date(Date.now() + 60_000).toISOString(),
            }),
        );

        fetchMock.mockImplementation((url) => {
            const target = String(url);
            if (target.includes('/admin/console/overview')) {
                return Promise.resolve(createJsonResponse({
                    summary: { sourceCount: 1, viewCount: 1, runningCount: 0, failedCount: 0 },
                    sources: [{ key: 'news', label: '新闻', description: '新闻抓取', status: 'success' }],
                    recentRuns: [{ runId: 'run-1', taskName: 'news_worker', startedAt: '2026-03-30T10:00:00Z', status: 'success' }],
                }));
            }
            if (target.includes('/admin/console/programs')) {
                return Promise.resolve(createJsonResponse({
                    updatedAt: '2026-03-30T10:01:00Z',
                    programs: [{ id: 'news_worker', title: '新闻 worker', description: '抓取新闻', runMode: 'daemon', actionId: 'sync-news', actionPath: '/api/v1/admin/sync-news', envKeys: ['NEWS_SYNC_INTERVAL_SECONDS'] }],
                }));
            }
            throw new Error(`unexpected fetch: ${target}`);
        });

        const view = renderWithProviders(<AdminView />);

        await act(async () => {
            await Promise.resolve();
        });

        expect(view.container.querySelector('.settings-card')).not.toBeNull();
        expect(view.container.textContent).toContain('健康监控');
        expect(view.container.textContent).toContain('Programs & Actions');
        expect(view.container.textContent).toContain('新闻');
        expect(view.container.textContent).toContain('执行任务');
        expect(view.container.textContent).not.toContain('Configuration');
        expect(view.container.textContent).not.toContain('Logs');
        expect(view.container.querySelector('textarea[readonly]')).toBeNull();

        view.cleanup();
    });
});
