import React, { useEffect, useMemo, useState } from 'react';
import { adminActionDefinitions } from '../../config/adminActions';
import { ADMIN_SESSION_STORAGE_KEY } from '../../config/settings';
import { createAdminFormState, createAdminRunState, fetchAdminOverview, fetchAdminPrograms, loginAdmin, runAdminAction } from '../../services/adminService';

const asArray = (value) => (Array.isArray(value) ? value : []);

function readStoredSession() {
    if (typeof window === 'undefined') return null;
    try {
        const payload = JSON.parse(window.localStorage.getItem(ADMIN_SESSION_STORAGE_KEY) || 'null');
        if (!payload?.token || !payload?.expiresAt || Date.parse(payload.expiresAt) <= Date.now()) {
            window.localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY);
            return null;
        }
        return payload;
    } catch {
        return null;
    }
}

function persistSession(session) {
    if (typeof window !== 'undefined') window.localStorage.setItem(ADMIN_SESSION_STORAGE_KEY, JSON.stringify(session));
}

function clearSession() {
    if (typeof window !== 'undefined') window.localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY);
}

function formatDateTime(value) {
    if (!value) return '未记录';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'medium' }).format(date);
}

function formatJson(value) {
    if (value == null || value === '') return '';
    if (typeof value === 'string') return value;
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}

function statusClassName(status) {
    if (status === 'success') return 'up';
    if (status === 'failed') return 'down';
    return '';
}

function isSessionError(error) {
    return String(error?.message || '').includes('403');
}

function ResultPanel({ state }) {
    return (
        <div className="settings-result">
            <div className="settings-result__status">
                <span>最近结果</span>
                <strong className={state?.error ? 'down' : statusClassName(state?.result?.status)}>
                    {state?.loading ? '执行中' : state?.error ? '执行失败' : state?.result ? '执行完成' : '未执行'}
                </strong>
            </div>
            {state?.error ? <p className="settings-error">{state.error}</p> : null}
            <pre>{formatJson(state?.result)}</pre>
        </div>
    );
}

function ActionCard({ action, formState, runState, setFormState, onRun, onReset }) {
    const form = formState[action.id];
    return (
        <>
            {asArray(action.fields).length > 0 ? (
                <div className="settings-form-grid">
                    {asArray(action.fields).map((field) => (
                        field.type === 'checkbox' ? (
                            <label key={field.name} className="settings-checkbox-row">
                                <input type="checkbox" checked={Boolean(form?.[field.name])} onChange={(event) => setFormState((current) => ({ ...current, [action.id]: { ...current[action.id], [field.name]: event.target.checked } }))} />
                                <div><span>{field.label}</span>{field.help ? <p>{field.help}</p> : null}</div>
                            </label>
                        ) : field.type === 'select' ? (
                            <label key={field.name}>
                                <span>{field.label}</span>
                                <select value={form?.[field.name] ?? ''} onChange={(event) => setFormState((current) => ({ ...current, [action.id]: { ...current[action.id], [field.name]: event.target.value } }))}>
                                    {asArray(field.options).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                                </select>
                            </label>
                        ) : (
                            <label key={field.name}>
                                <span>{field.label}</span>
                                <input type={field.type} min={field.min} value={form?.[field.name] ?? ''} placeholder={field.placeholder || ''} onChange={(event) => setFormState((current) => ({ ...current, [action.id]: { ...current[action.id], [field.name]: event.target.value } }))} />
                            </label>
                        )
                    ))}
                </div>
            ) : <p className="settings-admin-empty">该任务无额外可选项，点击即可执行。</p>}
            <div className="settings-actions">
                <button type="button" className="primary-button" onClick={() => onRun(action)} disabled={runState?.loading}>{runState?.loading ? '执行中...' : '执行任务'}</button>
                {asArray(action.fields).length > 0 ? <button type="button" className="secondary-button" onClick={onReset} disabled={runState?.loading}>恢复默认值</button> : null}
            </div>
            <ResultPanel state={runState} />
        </>
    );
}

export default function AdminView() {
    const [password, setPassword] = useState('');
    const [loginState, setLoginState] = useState({ loading: false, error: '' });
    const [session, setSession] = useState(() => readStoredSession());
    const [overview, setOverview] = useState(null);
    const [programs, setPrograms] = useState(null);
    const [consoleState, setConsoleState] = useState({ loading: false, error: '' });
    const [formState, setFormState] = useState(() => createAdminFormState());
    const [runState, setRunState] = useState(() => createAdminRunState());
    const actionLookup = useMemo(() => Object.fromEntries(adminActionDefinitions.map((action) => [action.id, action])), []);

    const loadConsole = async (sessionToken) => {
        setConsoleState({ loading: true, error: '' });
        try {
            const [overviewPayload, programPayload] = await Promise.all([
                fetchAdminOverview(sessionToken),
                fetchAdminPrograms(sessionToken),
            ]);
            setOverview(overviewPayload);
            setPrograms(programPayload);
            setConsoleState({ loading: false, error: '' });
        } catch (error) {
            if (isSessionError(error) || String(error?.message || '').includes('会话') || String(error?.message || '').includes('管理')) {
                clearSession();
                setSession(null);
            }
            setConsoleState({ loading: false, error: error.message || '管理台数据加载失败' });
        }
    };

    useEffect(() => {
        if (session?.token) loadConsole(session.token);
    }, [session]);

    const handleLogin = async (event) => {
        event.preventDefault();
        setLoginState({ loading: true, error: '' });
        try {
            const payload = await loginAdmin(password);
            const nextSession = { token: payload.token, expiresAt: payload.expiresAt };
            persistSession(nextSession);
            setSession(nextSession);
            setPassword('');
            setLoginState({ loading: false, error: '' });
        } catch (error) {
            setLoginState({ loading: false, error: error.message || '登录失败' });
        }
    };

    const handleLogout = () => {
        clearSession();
        setSession(null);
        setOverview(null);
        setPrograms(null);
        setRunState(createAdminRunState());
    };

    const handleRunAction = async (action) => {
        setRunState((current) => ({ ...current, [action.id]: { ...current[action.id], loading: true, error: '' } }));
        try {
            const result = await runAdminAction(action, formState[action.id], session?.token);
            setRunState((current) => ({ ...current, [action.id]: { loading: false, error: '', result } }));
            await loadConsole(session?.token);
        } catch (error) {
            setRunState((current) => ({ ...current, [action.id]: { ...current[action.id], loading: false, error: error.message || '执行失败' } }));
        }
    };

    if (!session?.token) {
        return (
            <div className="admin-shell">
                <div className="panel panel--page admin-page admin-page--login">
                    <div className="section-heading">
                        <h2>管理页登录</h2>
                        <p>请输入后台密码，进入独立管理页。</p>
                    </div>
                    <div className="settings-group">
                        <div className="settings-card admin-login-card">
                            <label>
                                <span>请输入后台密码</span>
                                <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="ADMIN_PAGE_PASSWORD" autoComplete="current-password" />
                            </label>
                            {loginState.error ? <p className="settings-error">{loginState.error}</p> : null}
                            <div className="settings-actions">
                                <button type="button" className="primary-button" onClick={handleLogin} disabled={loginState.loading || !password.trim()}>
                                    {loginState.loading ? '登录中...' : '进入管理台'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="admin-shell">
            <div className="panel panel--page admin-page">
                <div className="section-heading admin-page__heading">
                    <div>
                        <h2>后端管理页</h2>
                        <p>只保留健康监控和程序动作，便于快速巡检与手动触发。</p>
                    </div>
                    <div className="admin-page__toolbar">
                        <div className="settings-theme-status__item admin-page__session"><span>会话到期</span><strong>{formatDateTime(session.expiresAt)}</strong></div>
                        <button type="button" className="secondary-button" onClick={() => loadConsole(session.token)}>刷新</button>
                        <button type="button" className="secondary-button" onClick={handleLogout}>退出登录</button>
                    </div>
                </div>

                {consoleState.error ? <div className="settings-card"><p className="settings-error">{consoleState.error}</p></div> : null}
                {consoleState.loading ? <div className="settings-card"><p className="settings-admin-empty">管理台数据加载中...</p></div> : null}

                <div className="settings-group">
                    <h3>健康监控</h3>
                    <div className="settings-card">
                        <div className="settings-theme-status admin-summary-grid">
                            <div className="settings-theme-status__item"><span>数据源</span><strong>{overview?.summary?.sourceCount ?? '-'}</strong></div>
                            <div className="settings-theme-status__item"><span>视图快照</span><strong>{overview?.summary?.viewCount ?? '-'}</strong></div>
                            <div className="settings-theme-status__item"><span>运行中任务</span><strong>{overview?.summary?.runningCount ?? '-'}</strong></div>
                            <div className="settings-theme-status__item"><span>失败任务</span><strong>{overview?.summary?.failedCount ?? '-'}</strong></div>
                        </div>
                        <div className="admin-list">
                            {asArray(overview?.sources).map((source) => (
                                <div key={source.key} className="admin-list__row"><div><strong>{source.label || source.key}</strong><p>{source.description || '无描述'}</p></div><strong className={statusClassName(source.status)}>{source.status || 'unknown'}</strong></div>
                            ))}
                        </div>
                    </div>
                </div>

                <div className="settings-group">
                    <h3>Programs & Actions</h3>
                    <div className="settings-admin-grid">
                        {asArray(programs?.programs).map((program) => {
                            const action = actionLookup[program.actionId];
                            return (
                                <div key={program.id} className="settings-card settings-admin-card">
                                    <div className="settings-admin-card__header"><div><strong>{program.title}</strong><p>{program.description}</p></div><code>{program.actionPath || program.id}</code></div>
                                    <div className="admin-program-meta">
                                        <div><span>程序 ID</span><strong>{program.id}</strong></div>
                                        <div><span>运行模式</span><strong>{program.runMode}</strong></div>
                                        <div><span>启动命令</span><strong>{program.entryCommand}</strong></div>
                                        <div><span>环境变量</span><strong>{asArray(program.envKeys).join(', ') || '无'}</strong></div>
                                    </div>
                                    {action ? <ActionCard action={action} formState={formState} runState={runState[action.id]} setFormState={setFormState} onRun={handleRunAction} onReset={() => setFormState((current) => ({ ...current, [action.id]: { ...action.defaults } }))} /> : null}
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>
        </div>
    );
}
