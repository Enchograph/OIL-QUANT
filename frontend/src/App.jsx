import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Menu, X } from 'lucide-react';
import { resolveAppEntryMode } from './appMode';
import { useTheme } from './theme';
import { useTimezone } from './timezone';
import { apiGet } from './api';
import { LiveDashboardView } from './views/dashboard';
import { LivePredictionView } from './views/prediction';
import { tabs } from './config/navigation';
import { useApiResource } from './hooks/useApiResource';
import QAView from './views/qa';
import { LiveFactorView } from './views/factors';
import { LiveNewsView } from './views/news';
import AdminView from './views/admin';
import SettingsView from './views/settings';
import {
    formatMetricDisplay,
    formatSignedPercent,
    formatSourceTime,
} from './utils/formatters';
import { beginFlow, endFlow, getActiveFlowId, markEvent, markFlow } from './utils/devDiagnostics';
import 'react-day-picker/dist/style.css';
import brandWordmarkUrl from './assets/brand/oil-quant-wordmark.svg';
import brandWordmarkLightUrl from './assets/brand/oil-quant-wordmark-light.svg';

const APP_CACHE_KEYS = {
    ticker: 'oil-quant:market-ticker',
    status: 'oil-quant:status-sources',
};

function readSessionCache(key) {
    if (typeof window === 'undefined') {
        return null;
    }

    try {
        const raw = window.sessionStorage.getItem(key);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

function writeSessionCache(key, value) {
    if (typeof window === 'undefined') {
        return;
    }

    try {
        window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
        // 忽略浏览器存储不可用的场景，继续走实时请求。
    }
}

export default function App() {
    const entryMode = typeof window === 'undefined' ? 'main' : resolveAppEntryMode(window.location.pathname);
    const [activeTab, setActiveTab] = useState('dashboard');
    const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
    const { resolvedTheme } = useTheme();
    const { resolvedTimezone } = useTimezone();
    const brandWordmarkSrc = resolvedTheme === 'light' ? brandWordmarkLightUrl : brandWordmarkUrl;
    const tickerState = useApiResource(() => apiGet('/market/ticker'), [], 60000, true, {
        initialData: readSessionCache(APP_CACHE_KEYS.ticker),
        onSuccess: (data) => writeSessionCache(APP_CACHE_KEYS.ticker, data),
    });
    const statusState = useApiResource(() => apiGet('/status/sources'), [], 60000, true, {
        initialData: readSessionCache(APP_CACHE_KEYS.status),
        onSuccess: (data) => writeSessionCache(APP_CACHE_KEYS.status, data),
    });
    const tickerItems = tickerState.data?.items ?? [];
    const tickerGroupRef = useRef(null);
    const [tickerLoopWidth, setTickerLoopWidth] = useState(0);
    const sourceEntries = Object.entries(statusState.data?.sources ?? {});
    const latestSourceTime = sourceEntries
        .map(([, value]) => value?.last_success_at)
        .filter(Boolean)
        .sort()
        .at(-1);

    useLayoutEffect(() => {
        if (!tickerItems.length) {
            setTickerLoopWidth(0);
            return undefined;
        }

        const groupElement = tickerGroupRef.current;
        if (!groupElement) {
            return undefined;
        }

        const updateTickerLoopWidth = () => {
            setTickerLoopWidth(groupElement.getBoundingClientRect().width);
        };

        updateTickerLoopWidth();

        if (typeof ResizeObserver === 'undefined') {
            window.addEventListener('resize', updateTickerLoopWidth);
            return () => window.removeEventListener('resize', updateTickerLoopWidth);
        }

        const resizeObserver = new ResizeObserver(() => {
            updateTickerLoopWidth();
        });

        resizeObserver.observe(groupElement);

        return () => {
            resizeObserver.disconnect();
        };
    }, [tickerItems]);

    const tickerDuration = tickerLoopWidth ? Math.max(18, tickerLoopWidth / 45) : 24;

    useEffect(() => {
        if (entryMode === 'admin') {
            return undefined;
        }

        markEvent('app:active-tab-changed', { activeTab });
        const predictionNavigationFlowId = getActiveFlowId('prediction-navigation');
        if (activeTab === 'prediction' && predictionNavigationFlowId) {
            markFlow(predictionNavigationFlowId, 'app:prediction-tab-active', { activeTab });
        }

        setIsMobileNavOpen(false);
    }, [activeTab]);

    useEffect(() => {
        if (entryMode === 'admin') {
            return undefined;
        }

        if (typeof window === 'undefined') {
            return undefined;
        }

        const handleResize = () => {
            if (window.innerWidth > 900) {
                setIsMobileNavOpen(false);
            }
        };

        handleResize();
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
        };
    }, []);

    if (entryMode === 'admin') {
        return <AdminView />;
    }

    const handleTabClick = (nextTabId) => {
        markEvent('app:tab-click', { from: activeTab, to: nextTabId });
        if (nextTabId === 'prediction') {
            const existingFlowId = getActiveFlowId('prediction-navigation');
            if (existingFlowId) {
                endFlow(existingFlowId, 'superseded', { from: activeTab, to: nextTabId });
            }
            beginFlow('prediction-navigation', { from: activeTab, to: nextTabId });
        }
        setActiveTab(nextTabId);
    };

    return (
        <div className={`app-shell${isMobileNavOpen ? ' is-mobile-nav-open' : ''}`} data-active-theme={resolvedTheme}>
            <aside className="sidebar">
                <div className="sidebar__brand">
                    <img className="sidebar__brand-logo" src={brandWordmarkSrc} alt="Oil Quant" />
                </div>

                <nav className="sidebar__nav">
                    {tabs.map((tab) => {
                        const Icon = tab.icon;
                        const isActive = activeTab === tab.id;

                        return (
                            <button
                                key={tab.id}
                                type="button"
                                className={`sidebar__nav-item${isActive ? ' is-active' : ''}`}
                                onClick={() => handleTabClick(tab.id)}
                            >
                                <Icon size={16} />
                                <span>{tab.label}</span>
                            </button>
                        );
                    })}
                </nav>

                <div className="sidebar__footer">
                    <p>Model Ver: 2.1.4-beta</p>
                    <p>Data synced: {formatSourceTime(latestSourceTime, resolvedTimezone)}</p>
                </div>
            </aside>

            <main className="main-panel">
                <header className="mobile-topbar">
                    <button
                        type="button"
                        className="mobile-topbar__menu"
                        onClick={() => setIsMobileNavOpen((current) => !current)}
                        aria-label={isMobileNavOpen ? '关闭导航' : '打开导航'}
                        aria-expanded={isMobileNavOpen}
                    >
                        {isMobileNavOpen ? <X size={18} /> : <Menu size={18} />}
                    </button>
                    <img className="mobile-topbar__brand" src={brandWordmarkSrc} alt="Oil Quant" />
                    <span className="mobile-topbar__status">
                        {formatSourceTime(latestSourceTime, resolvedTimezone)}
                    </span>
                </header>

                <header className="ticker">
                    <div className="ticker__titleWrap">
                        <span className="ticker__title">MARKET PULSE</span>
                    </div>
                    <div className="ticker__viewport">
                        {tickerItems.length ? (
                            <div
                                className={`ticker__track${tickerLoopWidth ? ' is-ready' : ''}`}
                                style={{
                                    '--ticker-loop-width': `${tickerLoopWidth}px`,
                                    '--ticker-duration': `${tickerDuration}s`,
                                }}
                            >
                                {[0, 1].map((groupIndex) => (
                                    <div
                                        key={groupIndex}
                                        ref={groupIndex === 0 ? tickerGroupRef : null}
                                        className="ticker__group"
                                        aria-hidden={groupIndex === 1 ? 'true' : undefined}
                                    >
                                        {tickerItems.map((item) => (
                                            <span key={`${groupIndex}-${item.id}`} className="ticker__item">
                                                {item.label}{' '}
                                                <b className={item.direction === 'up' ? 'up' : 'down'}>
                                                    {item.direction === 'up' ? '▲' : '▼'} {formatMetricDisplay(item)} ({formatSignedPercent(item.changePercent)})
                                                </b>
                                            </span>
                                        ))}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div className="ticker__empty">行情数据加载中...</div>
                        )}
                    </div>
                </header>

                <section className="content">
                    <button
                        type="button"
                        className={`mobile-nav-backdrop${isMobileNavOpen ? ' is-visible' : ''}`}
                        aria-label="关闭导航"
                        onClick={() => setIsMobileNavOpen(false)}
                    />
                    <AnimatePresence mode="wait">
                        <motion.div
                            key={activeTab}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -10 }}
                            transition={{ duration: 0.2 }}
                            className="content__inner"
                            onAnimationStart={() => {
                                markEvent('app:content-animation-start', { activeTab });
                                const predictionNavigationFlowId = getActiveFlowId('prediction-navigation');
                                if (activeTab === 'prediction' && predictionNavigationFlowId) {
                                    markFlow(predictionNavigationFlowId, 'app:prediction-enter-animation-start', { activeTab });
                                }
                            }}
                            onAnimationComplete={() => {
                                markEvent('app:content-animation-complete', { activeTab });
                                const predictionNavigationFlowId = getActiveFlowId('prediction-navigation');
                                if (activeTab === 'prediction' && predictionNavigationFlowId) {
                                    markFlow(predictionNavigationFlowId, 'app:prediction-enter-animation-complete', { activeTab });
                                }
                            }}
                        >
                            {activeTab === 'dashboard' && <LiveDashboardView />}
                            {activeTab === 'factors' && <LiveFactorView />}
                            {activeTab === 'news' && <LiveNewsView />}
                            {activeTab === 'prediction' && <LivePredictionView />}
                            {activeTab === 'qa' && <QAView />}
                            {activeTab === 'settings' && <SettingsView />}
                        </motion.div>
                    </AnimatePresence>
                </section>
            </main>
        </div>
    );
}


