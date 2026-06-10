import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, AlertTriangle, Calendar, ChevronLeft, ChevronRight, Database, FileText, Hash, RefreshCw, Search, TrendingDown, TrendingUp, X } from 'lucide-react';
import { DayPicker } from 'react-day-picker';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import DashboardTooltip from '../../components/charts/DashboardTooltip';
import {
    fetchNewsFeed,
    fetchNewsDetail,
    getInitialNewsDetailState,
    getInitialNewsFeedState,
    getNewsDetailCacheEntry,
    getNewsFeedCacheEntry,
} from '../../services/newsService';
import { formatDateKey, formatDateLabel, getMonthStart, normalizeDateRange, parseDateKey, setMonthParts, shiftMonth } from '../../utils/date';
import { getTodayDateKey } from '../../utils/timezone';
import { formatNewsPublishedTime, getNewsPublishedCalendarParts } from '../../utils/formatters';
import { useTimezone } from '../../timezone';

const EMPTY_CHART_DATA = [];
const NEWS_REFRESH_INTERVAL_MS = 60000;
const monthLabels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function LiveNewsView() {
    const { resolvedTimezone } = useTimezone();
    const clampDateKeyToBounds = (value, minKey, maxKey) => {
        if (!value) {
            return value;
        }

        if (minKey && value < minKey) {
            return minKey;
        }

        if (maxKey && value > maxKey) {
            return maxKey;
        }

        return value;
    };

    const clampMonthToBounds = (month, minKey, maxKey) => {
        const monthStart = getMonthStart(month);
        if (minKey) {
            const minMonth = getMonthStart(parseDateKey(minKey));
            if (monthStart < minMonth) {
                return minMonth;
            }
        }

        if (maxKey) {
            const maxMonth = getMonthStart(parseDateKey(maxKey));
            if (monthStart > maxMonth) {
                return maxMonth;
            }
        }

        return monthStart;
    };

    const clampRangeToBounds = (range, minKey, maxKey) =>
        normalizeDateRange({
            start: clampDateKeyToBounds(range.start, minKey, maxKey),
            end: clampDateKeyToBounds(range.end, minKey, maxKey),
        });

    const getMonthOptionsForYear = (year, minKey, maxKey) =>
        monthLabels
            .map((label, index) => ({ label, value: index }))
            .filter(({ value }) => {
                if (minKey) {
                    const minDate = parseDateKey(minKey);
                    if (year === minDate.getFullYear() && value < minDate.getMonth()) {
                        return false;
                    }
                }

                if (maxKey) {
                    const maxDate = parseDateKey(maxKey);
                    if (year === maxDate.getFullYear() && value > maxDate.getMonth()) {
                        return false;
                    }
                }

                return true;
            });

    const getThisWeek = () => {
        const today = parseDateKey(getTodayDateKey(resolvedTimezone));
        const dayOfWeek = today.getDay();
        const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
        const start = new Date(today);
        start.setDate(today.getDate() + mondayOffset);
        start.setHours(0, 0, 0, 0);

        const end = new Date(start);
        end.setDate(start.getDate() + 6);

        return {
            start: formatDateKey(start),
            end: formatDateKey(end),
        };
    };

    const getThisMonth = () => {
        const today = parseDateKey(getTodayDateKey(resolvedTimezone));
        const start = new Date(today.getFullYear(), today.getMonth(), 1);
        const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);

        return {
            start: formatDateKey(start),
            end: formatDateKey(end),
        };
    };

    const getRecentDays = (days) => {
        const end = parseDateKey(getTodayDateKey(resolvedTimezone));

        const start = new Date(end);
        start.setDate(end.getDate() - (days - 1));

        return {
            start: formatDateKey(start),
            end: formatDateKey(end),
        };
    };

    const getToday = () => {
        const today = parseDateKey(getTodayDateKey(resolvedTimezone));

        return {
            start: formatDateKey(today),
            end: formatDateKey(today),
        };
    };

    const [dateRange, setDateRange] = useState(() => getRecentDays(7));
    const [draftDateRange, setDraftDateRange] = useState(() => getRecentDays(7));
    const [isDatePickerOpen, setIsDatePickerOpen] = useState(false);
    const [pickerMonth, setPickerMonth] = useState(() => getMonthStart(parseDateKey(getRecentDays(7).start)));
    const [draftPickerRange, setDraftPickerRange] = useState(() => ({
        from: parseDateKey(getRecentDays(7).start),
        to: parseDateKey(getRecentDays(7).end),
    }));
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedNewsId, setSelectedNewsId] = useState('');
    const [isNewsDetailOpen, setIsNewsDetailOpen] = useState(false);
    const datePickerRef = useRef(null);
    const feedParams = useMemo(
        () => ({
            start: dateRange.start,
            end: dateRange.end,
            query: searchQuery,
            listLimit: 80,
            overviewLimit: 120,
            timezone: resolvedTimezone,
        }),
        [dateRange.end, dateRange.start, resolvedTimezone, searchQuery],
    );
    const [feedState, setFeedState] = useState(() => getInitialNewsFeedState(feedParams));
    const [newsDetailState, setNewsDetailState] = useState(() => getInitialNewsDetailState(''));
    const [refreshTick, setRefreshTick] = useState(0);
    const todayDateKey = getTodayDateKey(resolvedTimezone);
    const newsListData = feedState.data?.list;
    const newsOverviewData = feedState.data?.overview;
    const newsDateBoundsData = feedState.data?.dateBounds;
    const minDateKey = newsDateBoundsData?.minDate ?? '';
    const maxDateKey = todayDateKey;
    const minDate = minDateKey ? parseDateKey(minDateKey) : undefined;
    const maxDate = maxDateKey ? parseDateKey(maxDateKey) : undefined;
    const disabledDays = useMemo(() => {
        const rules = [];
        if (minDate) {
            rules.push({ before: minDate });
        }
        if (maxDate) {
            rules.push({ after: maxDate });
        }
        return rules;
    }, [maxDate, minDate]);

    const filteredNews = useMemo(() => {
        const items = newsListData?.items ?? [];
        return [...items]
            .map((item) => ({
                ...item,
                calendarParts: getNewsPublishedCalendarParts(item.publishedAt, item.publishedDate, resolvedTimezone),
            }))
            .sort((left, right) => {
                const leftTime = Date.parse(left.publishedAt ?? left.publishedDate ?? '');
                const rightTime = Date.parse(right.publishedAt ?? right.publishedDate ?? '');

                if (Number.isNaN(leftTime) && Number.isNaN(rightTime)) {
                    return String(right.publishedDate ?? '').localeCompare(String(left.publishedDate ?? ''));
                }
                if (Number.isNaN(leftTime)) {
                    return 1;
                }
                if (Number.isNaN(rightTime)) {
                    return -1;
                }
                return rightTime - leftTime;
            });
    }, [newsListData?.items, resolvedTimezone]);
    const summary = newsOverviewData?.summary ?? {
        articleCount: 0,
        averageSentiment: '0.00',
        positiveCount: 0,
        negativeCount: 0,
        averageRisk: 0,
        averageMentions: 0,
        primaryTopic: '',
        primaryRegion: '',
    };
    const insightText =
        newsOverviewData?.insightText ??
        '当前筛选窗口内新闻样本不足，情绪与主题信号暂未形成有效共振，建议适当放宽时间范围以获取更稳定的事件脉冲。';
    const sentimentChartData = useMemo(
        () =>
            (newsOverviewData?.sentimentSeries ?? EMPTY_CHART_DATA).map((item) => ({
                ...item,
                label:
                    item?.publishedAt
                        ? (() => {
                            const parts = getNewsPublishedCalendarParts(item.publishedAt, item.date, resolvedTimezone);
                            return parts.month && parts.day ? `${parts.month}/${parts.day}` : item.date;
                        })()
                        : item.label,
            })),
        [newsOverviewData?.sentimentSeries, resolvedTimezone],
    );
    const regionalRiskData = newsOverviewData?.regionalRiskData ?? EMPTY_CHART_DATA;
    const entityTags = newsOverviewData?.entityTags ?? EMPTY_CHART_DATA;
    const topicDistribution = newsOverviewData?.topicDistribution ?? EMPTY_CHART_DATA;
    const newsYearOptions = useMemo(() => {
        if (!minDateKey || !maxDateKey) {
            return [parseDateKey(todayDateKey).getFullYear()];
        }
        const startYear = parseDateKey(minDateKey).getFullYear();
        const endYear = parseDateKey(maxDateKey).getFullYear();
        return Array.from({ length: endYear - startYear + 1 }, (_, index) => startYear + index);
    }, [maxDateKey, minDateKey, todayDateKey]);
    const selectedNewsPreview = useMemo(
        () => filteredNews.find((item) => item.id === selectedNewsId) ?? null,
        [filteredNews, selectedNewsId],
    );
    const selectedNewsDetail = newsDetailState.data;
    const selectedNewsAnalysis = selectedNewsDetail?.analysis ?? null;
    const selectedNewsSummary =
        selectedNewsDetail?.summary ??
        selectedNewsPreview?.summary ??
        '当前正文来自后端新闻库，右侧保留该篇新闻的文章级分析结果。';
    const selectedNewsRiskLevel = selectedNewsAnalysis?.riskLevel ?? selectedNewsPreview?.impact ?? '--';
    const selectedNewsRiskColor =
        selectedNewsRiskLevel === 'High'
            ? 'var(--status-danger)'
            : selectedNewsRiskLevel === 'Medium'
                ? 'var(--status-warning)'
                : 'var(--status-success)';
    const selectedNewsTopicTags = (selectedNewsAnalysis?.topicTags ?? [])
        .map((item) => (typeof item === 'string' ? item : item?.label ?? item?.name ?? ''))
        .filter(Boolean);
    const selectedNewsGeoEntities = (selectedNewsAnalysis?.geoEntities ?? [])
        .map((item) => (typeof item === 'string' ? item : item?.name ?? item?.label ?? item?.value ?? ''))
        .filter(Boolean);
    const selectedNewsMacroEntities = (selectedNewsAnalysis?.macroEntities ?? [])
        .map((item) => (typeof item === 'string' ? item : item?.name ?? item?.label ?? item?.value ?? ''))
        .filter(Boolean);
    const draftRangeLabel = useMemo(() => {
        const from = draftPickerRange.from ? formatDateLabel(formatDateKey(draftPickerRange.from)) : '--';
        const to = draftPickerRange.to ? formatDateLabel(formatDateKey(draftPickerRange.to)) : '...';
        return `${from} ~ ${to}`;
    }, [draftPickerRange.from, draftPickerRange.to]);

    const syncDraftState = (nextRange) => {
        const boundedRange = clampRangeToBounds(nextRange, minDateKey, maxDateKey);
        setDraftDateRange(boundedRange);
        setPickerMonth(clampMonthToBounds(parseDateKey(boundedRange.start), minDateKey, maxDateKey));
        setDraftPickerRange({
            from: parseDateKey(boundedRange.start),
            to: parseDateKey(boundedRange.end),
        });
    };

    const openDatePicker = () => {
        syncDraftState(dateRange);
        setIsDatePickerOpen(true);
    };

    const closeDatePicker = () => {
        setIsDatePickerOpen(false);
    };

    useEffect(() => {
        if (!minDateKey && !maxDateKey) {
            return;
        }

        setDateRange((currentRange) => clampRangeToBounds(currentRange, minDateKey, maxDateKey));
        setDraftDateRange((currentRange) => clampRangeToBounds(currentRange, minDateKey, maxDateKey));
        setPickerMonth((currentMonth) => clampMonthToBounds(currentMonth, minDateKey, maxDateKey));
    }, [maxDateKey, minDateKey]);

    useEffect(() => {
        if (!isDatePickerOpen) {
            return undefined;
        }

        const handlePointerDown = (event) => {
            if (datePickerRef.current?.contains(event.target)) {
                return;
            }

            closeDatePicker();
        };

        const handleKeyDown = (event) => {
            if (event.key === 'Escape') {
                closeDatePicker();
            }
        };

        document.addEventListener('mousedown', handlePointerDown);
        document.addEventListener('keydown', handleKeyDown);

        return () => {
            document.removeEventListener('mousedown', handlePointerDown);
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [isDatePickerOpen]);

    const handleRangePreset = (presetRange) => {
        const boundedRange = clampRangeToBounds(presetRange, minDateKey, maxDateKey);
        setDateRange(boundedRange);
        if (isDatePickerOpen) {
            syncDraftState(boundedRange);
        }
    };

    const handleDraftRangeSelect = (nextRange, selectedDate) => {
        if (!nextRange?.from) {
            return;
        }

        if (selectedDate) {
            setPickerMonth(clampMonthToBounds(selectedDate, minDateKey, maxDateKey));
        }

        setDraftPickerRange(nextRange);

        const start = formatDateKey(nextRange.from);
        const end = formatDateKey(nextRange.to ?? nextRange.from);
        setDraftDateRange(normalizeDateRange({ start, end }));
    };

    const handlePanelMonthChange = (nextMonthIndex) => {
        const numericMonthIndex = Number(nextMonthIndex);
        setPickerMonth((currentMonth) =>
            clampMonthToBounds(
                setMonthParts(currentMonth, currentMonth.getFullYear(), numericMonthIndex),
                minDateKey,
                maxDateKey,
            ),
        );
    };

    const handlePanelYearChange = (nextYear) => {
        const numericYear = Number(nextYear);
        setPickerMonth((currentMonth) => {
            const monthOptions = getMonthOptionsForYear(numericYear, minDateKey, maxDateKey);
            const currentMonthIndex = currentMonth.getMonth();
            const nextMonthIndex = monthOptions.some((option) => option.value === currentMonthIndex)
                ? currentMonthIndex
                : monthOptions[0]?.value ?? currentMonthIndex;
            return clampMonthToBounds(setMonthParts(currentMonth, numericYear, nextMonthIndex), minDateKey, maxDateKey);
        });
    };

    const applyDraftDateRange = () => {
        setDateRange(clampRangeToBounds(draftDateRange, minDateKey, maxDateKey));
        closeDatePicker();
    };

    const pickerMonthOptions = useMemo(
        () => getMonthOptionsForYear(pickerMonth.getFullYear(), minDateKey, maxDateKey),
        [maxDateKey, minDateKey, pickerMonth],
    );
    const canShiftPickerMonthBackward = !minDateKey || getMonthStart(pickerMonth) > getMonthStart(parseDateKey(minDateKey));
    const canShiftPickerMonthForward = !maxDateKey || getMonthStart(pickerMonth) < getMonthStart(parseDateKey(maxDateKey));

    useEffect(() => {
        const timer = window.setInterval(() => {
            if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
                return;
            }
            setRefreshTick((current) => current + 1);
        }, NEWS_REFRESH_INTERVAL_MS);

        return () => {
            window.clearInterval(timer);
        };
    }, []);

    useEffect(() => {
        let cancelled = false;
        const cacheEntry = getNewsFeedCacheEntry(feedParams);
        const forceRefresh = refreshTick > 0;
        const run = (force = false) =>
            fetchNewsFeed(feedParams, force)
                .then((data) => {
                    if (!cancelled) {
                        setFeedState({ data, loading: false, error: '' });
                    }
                })
                .catch((error) => {
                    if (!cancelled) {
                        setFeedState({
                            data: cacheEntry.data,
                            loading: false,
                            error: error instanceof Error ? error.message : '请求失败',
                        });
                    }
                });

        if (cacheEntry.data || cacheEntry.error) {
            setFeedState({ data: cacheEntry.data, loading: false, error: cacheEntry.error });
        } else {
            setFeedState({ data: null, loading: true, error: '' });
        }

        run(forceRefresh);

        return () => {
            cancelled = true;
        };
    }, [feedParams, refreshTick]);

    const closeNewsDetail = () => {
        setIsNewsDetailOpen(false);
    };

    const openNewsDetail = (articleId) => {
        if (!articleId) {
            return;
        }

        setSelectedNewsId(articleId);
        setIsNewsDetailOpen(true);
    };

    useEffect(() => {
        if (!isNewsDetailOpen || !selectedNewsId) {
            return undefined;
        }

        const cacheEntry = getNewsDetailCacheEntry(selectedNewsId);
        if (cacheEntry.data || cacheEntry.error) {
            setNewsDetailState({
                data: cacheEntry.data,
                loading: false,
                error: cacheEntry.error,
            });
        } else {
            setNewsDetailState({
                data: null,
                loading: true,
                error: '',
            });
        }

        let cancelled = false;
        fetchNewsDetail(selectedNewsId)
            .then((detail) => {
                if (cancelled) {
                    return;
                }

                setNewsDetailState({
                    data: detail,
                    loading: false,
                    error: '',
                });
            })
            .catch((error) => {
                if (cancelled) {
                    return;
                }

                setNewsDetailState({
                    data: cacheEntry.data,
                    loading: false,
                    error: error instanceof Error ? error.message : '新闻正文加载失败',
                });
            });

        return () => {
            cancelled = true;
        };
    }, [isNewsDetailOpen, selectedNewsId]);

    useEffect(() => {
        if (!isNewsDetailOpen) {
            return undefined;
        }

        const handleKeyDown = (event) => {
            if (event.key === 'Escape') {
                closeNewsDetail();
            }
        };

        document.addEventListener('keydown', handleKeyDown);

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [isNewsDetailOpen]);

    return (
        <div className="panel panel--fill">
            <div className="panel__header sticky">
                <div>
                    <h2>市场资讯时间轴 (News Intelligence)</h2>
                    <p>世界实时新闻与其逐篇分析</p>
                </div>
                <label className="search-box">
                    <Search size={16} />
                    <input
                        type="text"
                        placeholder="检索新闻实体/标题..."
                        value={searchQuery}
                        onChange={(event) => setSearchQuery(event.target.value)}
                    />
                </label>
            </div>

            <div className="news-page-container">
                <header className="news-nav-strip">
                    <div className="news-nav-strip__left">
                        <div ref={datePickerRef} className="date-range-picker">
                            <button
                                type="button"
                                className={`nav-date-range${isDatePickerOpen ? ' is-open' : ''}`}
                                onClick={() => {
                                    if (isDatePickerOpen) {
                                        closeDatePicker();
                                        return;
                                    }

                                    openDatePicker();
                                }}
                                aria-expanded={isDatePickerOpen}
                                aria-label="打开时间范围选择器"
                            >
                                <Calendar size={15} />
                                <span className="nav-date-range__label">
                                    <span>{formatDateLabel(dateRange.start)}</span>
                                    <span className="separator">~</span>
                                    <span>{formatDateLabel(dateRange.end)}</span>
                                </span>
                            </button>

                            {isDatePickerOpen ? (
                                <div className="date-range-popover">
                                    <div className="date-range-popover__header">
                                        <span>新闻时间范围</span>
                                        <strong>{draftRangeLabel}</strong>
                                    </div>

                                    <section className="date-range-panel date-range-panel--single">
                                        <div className="date-range-panel__toolbar">
                                            <button
                                                type="button"
                                                className="date-range-panel__arrow"
                                                aria-label="上个月"
                                                onClick={() =>
                                                    setPickerMonth((month) =>
                                                        clampMonthToBounds(shiftMonth(month, -1), minDateKey, maxDateKey),
                                                    )
                                                }
                                                disabled={!canShiftPickerMonthBackward}
                                            >
                                                <ChevronLeft size={14} />
                                            </button>
                                            <span className="date-range-panel__title">当前：</span>
                                            <select
                                                className="date-range-panel__select"
                                                value={pickerMonth.getFullYear()}
                                                onChange={(event) => handlePanelYearChange(event.target.value)}
                                            >
                                                {newsYearOptions.map((year) => (
                                                    <option key={year} value={year}>
                                                        {year}
                                                    </option>
                                                ))}
                                            </select>
                                            <select
                                                className="date-range-panel__select"
                                                value={pickerMonth.getMonth()}
                                                onChange={(event) => handlePanelMonthChange(event.target.value)}
                                            >
                                                {pickerMonthOptions.map(({ label, value }) => (
                                                    <option key={label} value={value}>
                                                        {label}
                                                    </option>
                                                ))}
                                            </select>
                                            <button
                                                type="button"
                                                className="date-range-panel__arrow"
                                                aria-label="下个月"
                                                onClick={() =>
                                                    setPickerMonth((month) =>
                                                        clampMonthToBounds(shiftMonth(month, 1), minDateKey, maxDateKey),
                                                    )
                                                }
                                                disabled={!canShiftPickerMonthForward}
                                            >
                                                <ChevronRight size={14} />
                                            </button>
                                        </div>

                                        <DayPicker
                                            animate
                                            mode="range"
                                            month={pickerMonth}
                                            onMonthChange={(month) => setPickerMonth(clampMonthToBounds(month, minDateKey, maxDateKey))}
                                            showOutsideDays
                                            fixedWeeks
                                            hideNavigation
                                            selected={draftPickerRange}
                                            disabled={disabledDays}
                                            onSelect={handleDraftRangeSelect}
                                        />
                                    </section>

                                    <div className="date-range-popover__actions">
                                        <button type="button" className="date-range-action date-range-action--ghost" onClick={closeDatePicker}>
                                            取消
                                        </button>
                                        <button type="button" className="date-range-action date-range-action--primary" onClick={applyDraftDateRange}>
                                            确定
                                        </button>
                                    </div>
                                </div>
                            ) : null}
                        </div>
                        <button type="button" className="btn-this-week" onClick={() => handleRangePreset(getThisMonth())}>
                            本月
                        </button>
                        <button type="button" className="btn-this-week" onClick={() => handleRangePreset(getThisWeek())}>
                            本周
                        </button>
                        <button type="button" className="btn-this-week" onClick={() => handleRangePreset(getRecentDays(7))}>
                            最近七天
                        </button>
                        <button type="button" className="btn-this-week" onClick={() => handleRangePreset(getToday())}>
                            今日
                        </button>
                    </div>

                    <div className="news-nav-strip__right" />
                </header>

                <div className="news-main-layout">
                    <section className="news-stream">
                        {feedState.loading ? (
                            <div className="news-empty-state">正在加载真实新闻数据</div>
                        ) : feedState.error ? (
                            <div className="news-empty-state">{feedState.error}</div>
                        ) : filteredNews.length ? (
                            filteredNews.map((news) => (
                                <article
                                    key={news.id}
                                    className="news-row-card"
                                    role="button"
                                    tabIndex={0}
                                    aria-label={`查看新闻正文：${news.title}`}
                                    aria-haspopup="dialog"
                                    onClick={() => openNewsDetail(news.id)}
                                    onKeyDown={(event) => {
                                        if (event.key === 'Enter' || event.key === ' ') {
                                            event.preventDefault();
                                            openNewsDetail(news.id);
                                        }
                                    }}
                                >
                                    <div className="news-row-card__date">
                                        <span className="day">{String(news.calendarParts?.day ?? '--').padStart(2, '0')}</span>
                                        <span className="month">{news.calendarParts?.month ?? '--'}月</span>
                                    </div>

                                    <div className="news-row-card__content">
                                        <div className="meta">
                                            <span className="source">{news.source}</span>
                                            <span className={`impact-tag ${news.impact.toLowerCase()}`}>
                                                {news.impact} Impact
                                            </span>
                                            <span className="date">{formatNewsPublishedTime(news.publishedAt, news.publishedDate, resolvedTimezone)}</span>
                                        </div>
                                        <h3 className="title">{news.title}</h3>
                                        <div className="tags">
                                            <span className="category-tag">
                                                <Hash size={10} />
                                                {news.category}
                                            </span>
                                            <span className="sentiment-tag">
                                                {news.sentiment >= 0 ? (
                                                    <TrendingUp size={12} className="up" />
                                                ) : (
                                                    <TrendingDown size={12} className="down" />
                                                )}
                                                Tone: {news.sentiment > 0 ? '+' : ''}
                                                {news.sentiment.toFixed(2)}
                                            </span>
                                            <span className="sentiment-tag">
                                                <Activity size={12} />
                                                Risk: {news.risk}
                                            </span>
                                        </div>
                                    </div>

                                    <div className="news-row-card__action">
                                        <ChevronRight size={16} />
                                    </div>
                                </article>
                            ))
                        ) : (
                            <div className="news-empty-state">该时间段内无匹配数据</div>
                        )}
                    </section>

                    <aside className="news-analysis-sidebar">
                        <section className="analysis-block">
                            <div className="block-header">NLP 情绪分布</div>
                            <div className="block-chart-mini">
                                <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={120}>
                                    <BarChart data={sentimentChartData}>
                                        <XAxis dataKey="label" hide />
                                        <YAxis hide domain={[-1, 1]} />
                                        <Tooltip
                                            cursor={false}
                                            content={
                                                <DashboardTooltip
                                                    title="Sentiment Snapshot"
                                                    rows={(point) => [
                                                        { label: 'Date', value: point.label },
                                                        { label: 'Tone', value: point.sentiment },
                                                    ]}
                                                />
                                            }
                                        />
                                        <Bar dataKey="sentiment" radius={[0, 0, 0, 0]}>
                                            {sentimentChartData.map((entry) => (
                                                <Cell key={entry.title} fill={entry.sentiment >= 0 ? '#3dc58f' : '#ff7b6d'} />
                                            ))}
                                        </Bar>
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </section>

                        <section className="analysis-block">
                            <div className="block-header">地缘政治热度矩阵</div>
                            <div className="gpr-grid">
                                {regionalRiskData.map((item) => (
                                    <div key={item.label} className="gpr-item">
                                        <span>{item.label}</span>
                                        <div className="gpr-bar">
                                            <div className="fill" style={{ width: `${item.value}%` }} />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </section>

                        <section className="analysis-block">
                            <div className="block-header">宏观实体提及频率</div>
                            <div className="entity-cloud-dense">
                                {entityTags.length ? entityTags.map((tag) => (
                                    <span key={tag} className="entity-tag-mini">{tag}</span>
                                )) : <span className="entity-tag-mini">暂无实体数据</span>}
                            </div>
                        </section>

                        <section className="analysis-block summary-statement">
                            <div className="summary-box__row">
                                <span>tone_mean</span>
                                <strong className={Number(summary.averageSentiment) >= 0 ? 'up' : 'down'}>
                                    {summary.averageSentiment}
                                </strong>
                            </div>
                            <div className="summary-box__row">
                                <span>conflict_count</span>
                                <strong>{summary.averageRisk}</strong>
                            </div>
                            <div className="summary-box__row">
                                <span>mentions_mean</span>
                                <strong>{summary.averageMentions}</strong>
                            </div>
                            <p>{insightText}</p>
                        </section>

                        <section className="analysis-block">
                            <div className="block-header">主题分布</div>
                            <div className="gpr-grid">
                                {topicDistribution.length ? topicDistribution.map((item) => (
                                    <div key={item.label} className="gpr-item">
                                        <span>{item.label}</span>
                                        <div className="gpr-bar">
                                            <div className="fill" style={{ width: `${item.value ?? 0}%` }} />
                                        </div>
                                    </div>
                                )) : <div className="gpr-item"><span>暂无</span><div className="gpr-bar"><div className="fill" style={{ width: '0%' }} /></div></div>}
                            </div>
                        </section>
                    </aside>
                </div>
            </div>

            {isNewsDetailOpen ? (
                <div className="news-detail-modal" role="dialog" aria-modal="true" aria-label="新闻正文详情">
                    <div className="news-detail-modal__backdrop" onClick={closeNewsDetail} />
                    <section className="news-detail-modal__panel">
                        <header className="news-detail-modal__header">
                            <div className="news-detail-modal__titleBlock">
                                <span className="news-detail-modal__eyebrow">NEWS DETAIL</span>
                                <h3 style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                                    <FileText size={28} style={{ color: 'var(--brand-primary)', flexShrink: 0, marginTop: '2px' }} />
                                    <span>{selectedNewsDetail?.title ?? selectedNewsPreview?.title ?? '新闻正文详情'}</span>
                                </h3>
                            </div>
                            <div className="ai-analysis-modal__controls" style={{ display: 'flex', alignItems: 'flex-start' }}>
                                <button
                                    type="button"
                                    className="news-detail-modal__close"
                                    onClick={closeNewsDetail}
                                    aria-label="关闭新闻详情"
                                >
                                    <X size={18} />
                                </button>
                            </div>
                        </header>

                        <div className="news-detail-modal__content">
                            <div className="news-detail-modal__body">
                                <div className="news-detail-modal__meta" style={{ paddingBottom: '16px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '24px' }}>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        <Database size={14} />
                                        {selectedNewsDetail?.source ?? selectedNewsPreview?.source ?? '未知来源'}
                                    </span>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        <Calendar size={14} />
                                        {formatNewsPublishedTime(
                                            selectedNewsDetail?.publishedAt ?? selectedNewsPreview?.publishedAt,
                                            selectedNewsDetail?.publishedDate ?? selectedNewsPreview?.publishedDate,
                                            resolvedTimezone,
                                        )}
                                    </span>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        <Hash size={14} />
                                        {selectedNewsDetail?.category ?? selectedNewsPreview?.category ?? 'World News'}
                                    </span>
                                    {selectedNewsDetail?.url ? (
                                        <a
                                            href={selectedNewsDetail.url}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="news-detail-modal__link"
                                            style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', marginLeft: 'auto' }}
                                        >
                                            查看原文
                                            <ChevronRight size={14} />
                                        </a>
                                    ) : null}
                                </div>

                                {newsDetailState.loading ? (
                                    <div className="news-detail-modal__empty">
                                        <RefreshCw className="is-spinning" size={24} style={{ marginBottom: '12px', color: 'var(--brand-primary)' }} />
                                        正在加载正文内容...
                                    </div>
                                ) : null}
                                {!newsDetailState.loading && newsDetailState.error ? (
                                    <div className="news-detail-modal__empty" style={{ color: 'var(--status-danger)' }}>
                                        <AlertTriangle size={24} style={{ marginBottom: '12px' }} />
                                        {newsDetailState.error}
                                    </div>
                                ) : null}
                                {!newsDetailState.loading &&
                                    !newsDetailState.error &&
                                    !(selectedNewsDetail?.contentText || '').trim() ? (
                                    <div className="news-detail-modal__empty">
                                        <FileText size={24} style={{ marginBottom: '12px', opacity: 0.5 }} />
                                        当前文章暂无可展示的正文内容，请使用原文链接查看。
                                    </div>
                                ) : null}
                                {!newsDetailState.loading &&
                                    !newsDetailState.error &&
                                    (selectedNewsDetail?.contentText || '').trim() ? (
                                    <article className="news-detail-modal__article" style={{ fontSize: '16px', lineHeight: '1.8', color: 'var(--text-primary)' }}>
                                        {(selectedNewsDetail.contentText || '').split('\n').filter(p => p.trim()).map((p, i) => (
                                            <p key={i} style={{ marginBottom: '1.4em', textAlign: 'justify' }}>
                                                {p}
                                            </p>
                                        ))}
                                    </article>
                                ) : null}
                            </div>

                            <aside className="news-detail-modal__sidebar">
                                <div className="news-detail-modal__metaCard news-detail-modal__summaryCard">
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        <FileText size={14} />
                                        概要分析
                                    </span>
                                    <strong>{selectedNewsSummary}</strong>
                                </div>

                                <div className="news-detail-modal__metricsGrid">
                                    <div className="news-detail-modal__metaCard news-detail-modal__metricCard">
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Activity size={14} /> 情绪得分</span>
                                        <strong className={(selectedNewsAnalysis?.sentimentScore ?? 0) >= 0 ? 'up' : 'down'} style={{ fontSize: '20px' }}>
                                            {Number(selectedNewsAnalysis?.sentimentScore ?? 0).toFixed(2)}
                                        </strong>
                                    </div>
                                    <div className="news-detail-modal__metaCard news-detail-modal__metricCard">
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><AlertTriangle size={14} /> 风险等级</span>
                                        <strong style={{ fontSize: '18px', color: selectedNewsRiskColor }}>
                                            {selectedNewsRiskLevel}
                                        </strong>
                                    </div>
                                    <div className="news-detail-modal__metaCard news-detail-modal__metricCard">
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><TrendingUp size={14} /> 风险分值</span>
                                        <strong style={{ fontSize: '20px' }}>{selectedNewsAnalysis?.riskScore ?? selectedNewsPreview?.risk ?? 0}</strong>
                                    </div>
                                    <div className="news-detail-modal__metaCard news-detail-modal__metricCard">
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Hash size={14} /> 提及次数</span>
                                        <strong style={{ fontSize: '20px' }}>{selectedNewsAnalysis?.mentionCount ?? selectedNewsPreview?.mentionCount ?? 0}</strong>
                                    </div>
                                </div>

                                <div className="news-detail-modal__metaCard">
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><FileText size={14} /> 主题标签</span>
                                    <div className="news-detail-modal__tagList" style={{ marginTop: '8px' }}>
                                        {selectedNewsTopicTags.length ? (
                                            selectedNewsTopicTags.map((tag) => (
                                                <span key={tag} className="news-detail-modal__tag" style={{ background: 'var(--surface-accent-soft)', borderColor: 'var(--border-accent)', color: 'var(--brand-primary)', fontWeight: 600 }}>
                                                    #{tag}
                                                </span>
                                            ))
                                        ) : (
                                            <strong style={{ fontSize: '13px', color: 'var(--text-muted)' }}>暂无主题标签</strong>
                                        )}
                                    </div>
                                </div>
                                <div className="news-detail-modal__metaCard">
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Database size={14} /> 地缘实体</span>
                                    <div className="news-detail-modal__tagList" style={{ marginTop: '8px' }}>
                                        {selectedNewsGeoEntities.length ? (
                                            selectedNewsGeoEntities.map((entity) => (
                                                <span key={entity} className="news-detail-modal__tag">
                                                    {entity}
                                                </span>
                                            ))
                                        ) : (
                                            <strong style={{ fontSize: '13px', color: 'var(--text-muted)' }}>暂无地缘实体</strong>
                                        )}
                                    </div>
                                </div>
                                <div className="news-detail-modal__metaCard">
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Database size={14} /> 宏观实体</span>
                                    <div className="news-detail-modal__tagList" style={{ marginTop: '8px' }}>
                                        {selectedNewsMacroEntities.length ? (
                                            selectedNewsMacroEntities.map((entity) => (
                                                <span key={entity} className="news-detail-modal__tag">
                                                    {entity}
                                                </span>
                                            ))
                                        ) : (
                                            <strong style={{ fontSize: '13px', color: 'var(--text-muted)' }}>暂无宏观实体</strong>
                                        )}
                                    </div>
                                </div>
                            </aside>
                        </div>
                    </section>
                </div>
            ) : null}
        </div>
    );
}

