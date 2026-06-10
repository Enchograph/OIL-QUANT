import { AUDIENCE_PREFERENCES, useAudiencePreference } from '../../audiencePreference';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, ChevronDown, Cpu, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { apiGet, apiGetPredictionAiAnalysis } from '../../api';
import PredictionRangeChart from '../../components/charts/PredictionRangeChart';
import RangeToggle from '../../components/charts/RangeToggle';
import { useApiResource } from '../../hooks/useApiResource';
import { useTimezone } from '../../timezone';
import { normalizeAiAnalysisView } from '../../utils/aiAnalysis';
import { endFlow, getActiveFlowId, markEvent, markFlow, measurePromise } from '../../utils/devDiagnostics';
import { formatSourceTime } from '../../utils/formatters';
import {
    buildPredictionChartRenderKey,
    predictionChartRanges,
    resolveAiAvailability,
    resolveAiPreviewSummary,
    resolveFeatureImportance,
    resolvePredictionDescription,
    resolvePredictionSummaryMetrics,
    resolveRiskSignalTone,
} from './presentation';

const EMPTY_CHART_DATA = [];
const MARKDOWN_PATTERN = /(^|\n)\s{0,3}(#{1,6}\s|[-*+]\s|\d+\.\s|>\s)|(\*\*|__|`{1,3}|\[[^\]]+\]\([^)]+\))/m;
const REFERENCE_FALLBACK_EXCERPT = '该来源片段暂不可读';

function hasMarkdownSyntax(content) {
    return typeof content === 'string' && MARKDOWN_PATTERN.test(content);
}

function normalizeReferenceExcerpt(content) {
    if (typeof content !== 'string') {
        return REFERENCE_FALLBACK_EXCERPT;
    }

    const raw = content.trim();
    if (!raw) {
        return REFERENCE_FALLBACK_EXCERPT;
    }

    const segments = raw
        .split(/(?:\\n|\n)+/)
        .map((segment) => segment
            .replace(/\\[nrt]/g, ' ')
            .replace(/[\r\n\t]+/g, ' ')
            .replace(/\b(question|answer|context|evidence|instruction|input|output)\s*[:：]\s*/gi, '')
            .replace(/\s{2,}/g, ' ')
            .replace(/(?:['"`]+[\]\}]?|[\]\}]+['"`]?)$/g, '')
            .trim()
            .replace(/^[\s'"`[\]{}()<>]+|[\s'"`[\]{}()<>]+$/g, ''))
        .filter((segment) => segment && segment.length >= 6 && !/^[\W\d_]+$/.test(segment));

    const preferredSegment = segments.find((segment) => segment.length >= 48) || segments.sort((left, right) => right.length - left.length)[0] || raw;
    const cleaned = preferredSegment
        .replace(/\\[nrt]/g, ' ')
        .replace(/[\r\n\t]+/g, ' ')
        .replace(/\s{2,}/g, ' ')
        .replace(/(?:['"`]+[\]\}]?|[\]\}]+['"`]?)$/g, '')
        .trim()
        .replace(/^[\s'"`[\]{}()<>]+|[\s'"`[\]{}()<>]+$/g, '');

    return cleaned || REFERENCE_FALLBACK_EXCERPT;
}

function PlainTextContent({ content }) {
    return (
        <>
            {content
                .split(/\n{2,}/)
                .map((paragraph) => paragraph.trim())
                .filter(Boolean)
                .map((paragraph, index) => (
                    <p key={`plain-paragraph-${index}`}>{paragraph}</p>
                ))}
        </>
    );
}

function AiDetailContent({ content }) {
    if (!content?.trim()) {
        return <p>暂无文本分析。</p>;
    }

    if (!hasMarkdownSyntax(content)) {
        return <PlainTextContent content={content} />;
    }

    return (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {content}
        </ReactMarkdown>
    );
}

export function LivePredictionView() {
    const { audiencePreference } = useAudiencePreference();
    const { resolvedTimezone } = useTimezone();
    const [range, setRange] = useState('1M');
    const [isAiDetailOpen, setIsAiDetailOpen] = useState(false);
    const [isReferencesExpanded, setIsReferencesExpanded] = useState(false);
    const [aiPerspective, setAiPerspective] = useState(
        audiencePreference === AUDIENCE_PREFERENCES.BANK ? 'bank' : 'corporate',
    );
    const [aiAnalysisState, setAiAnalysisState] = useState({ data: null, loading: false, error: '' });
    const summaryVisibleRef = useRef(false);
    const chartVisibleRef = useRef(false);
    const aiDetailVisibleRef = useRef(false);
    const summaryState = useApiResource(
        () => measurePromise('prediction:latest', () => apiGet('/prediction/latest'), { flowId: getActiveFlowId('prediction-navigation') }),
        [],
        60000,
    );
    const chartState = useApiResource(
        () => measurePromise('prediction:chart', () => apiGet('/prediction/chart', { range }), { range, flowId: getActiveFlowId('prediction-navigation') }),
        [range],
        60000,
    );
    const summary = summaryState.data;
    const aiPreviewSummary = resolveAiPreviewSummary(summary, aiAnalysisState.data);
    const aiSummary = typeof aiPreviewSummary === 'string' && aiPreviewSummary.trim()
        ? aiPreviewSummary
        : '独立概览摘要暂未生成。';
    const aiSummaryUpdatedAt = summary?.aiAnalysisUpdatedAt ?? summary?.updatedAt ?? null;
    const isAiAnalysisAvailable = resolveAiAvailability(summary, aiAnalysisState.data);
    const history = chartState.data?.history ?? EMPTY_CHART_DATA;
    const projection = chartState.data?.projection ?? EMPTY_CHART_DATA;
    const activeAiView = normalizeAiAnalysisView(aiAnalysisState.data, aiPerspective);
    const aiDetailUpdatedAt = aiAnalysisState.data?.generatedAt ?? aiAnalysisState.data?.updatedAt ?? aiSummaryUpdatedAt;
    const aiReferences = useMemo(
        () => (Array.isArray(aiAnalysisState.data?.references) ? aiAnalysisState.data.references : []).map((reference) => ({
            ...reference,
            excerpt: normalizeReferenceExcerpt(reference?.excerpt),
        })),
        [aiAnalysisState.data?.references],
    );
    const aiDrivers = aiAnalysisState.data?.drivers ?? summary?.topMovers?.map((item) => item.factor) ?? [];
    const aiPredictionSummary = aiAnalysisState.data?.predictionSummary ?? '暂无预测摘要。';
    const aiPredictionSummaryMetrics = useMemo(
        () => resolvePredictionSummaryMetrics(aiPredictionSummary),
        [aiPredictionSummary],
    );
    const metricToneStyles = {
        up: { color: 'var(--status-success)' },
        down: { color: 'var(--status-danger)' },
        warning: { color: 'var(--status-warning)' },
    };
    const featureImportance = resolveFeatureImportance(summary);
    const predictionDescription = resolvePredictionDescription(summaryState);
    const aiReferenceCount = aiReferences.length;
    const aiStatusItems = [
        { label: '当前视角', value: aiPerspective === 'corporate' ? '企业侧' : '银行侧' },
        { label: '更新时间', value: formatSourceTime(aiDetailUpdatedAt, resolvedTimezone) },
        { label: '来源条数', value: String(aiReferenceCount) },
        { label: '状态', value: aiAnalysisState.data?.stale ? '待刷新' : '最新结果' },
    ];
    const riskSignalTone = resolveRiskSignalTone(summary?.riskSignal);
    const chartData = useMemo(() => {
        const historyPoints = history.map((point) => ({
            date: point.observed_at,
            dateMs: new Date(point.observed_at).getTime(),
            historical: point.close,
            prediction: null,
            upperBound: null,
            lowerBound: null,
        }));
        const historyTail = history.at(-1);
        const bridgePoint = historyTail ? {
            date: historyTail.observed_at,
            dateMs: new Date(historyTail.observed_at).getTime(),
            historical: historyTail.close,
            prediction: historyTail.close,
            upperBound: historyTail.close,
            lowerBound: historyTail.close,
        } : null;
        const projectionPoints = projection.map((point) => ({
            date: point.date,
            dateMs: new Date(point.date).getTime(),
            historical: null,
            prediction: point.prediction,
            upperBound: point.upperBound,
            lowerBound: point.lowerBound,
        }));
        return bridgePoint ? [...historyPoints, bridgePoint, ...projectionPoints] : [...historyPoints, ...projectionPoints];
    }, [history, projection]);
    const chartRenderKey = buildPredictionChartRenderKey(range, chartData);

    useEffect(() => {
        const predictionNavigationFlowId = getActiveFlowId('prediction-navigation');
        markEvent('prediction:view-mounted', { range, flowId: predictionNavigationFlowId });
        if (predictionNavigationFlowId) {
            markFlow(predictionNavigationFlowId, 'prediction:view-mounted', { range });
        }
        return () => {
            markEvent('prediction:view-unmounted', { range, flowId: predictionNavigationFlowId });
        };
    }, []);

    useEffect(() => {
        if (!summaryState.data || summaryVisibleRef.current) {
            return;
        }
        summaryVisibleRef.current = true;
        const predictionNavigationFlowId = getActiveFlowId('prediction-navigation');
        markEvent('prediction:summary-visible', { flowId: predictionNavigationFlowId });
        if (predictionNavigationFlowId) {
            markFlow(predictionNavigationFlowId, 'prediction:summary-visible', {
                aiAvailable: resolveAiAvailability(summaryState.data, aiAnalysisState.data),
                featureImportanceCount: resolveFeatureImportance(summaryState.data).length,
            });
        }
    }, [aiAnalysisState.data, summaryState.data, summaryVisibleRef]);

    useEffect(() => {
        if (!chartState.data || chartVisibleRef.current) {
            return;
        }
        chartVisibleRef.current = true;
        const predictionNavigationFlowId = getActiveFlowId('prediction-navigation');
        markEvent('prediction:chart-visible', {
            flowId: predictionNavigationFlowId,
            historyCount: chartState.data.history?.length ?? 0,
            projectionCount: chartState.data.projection?.length ?? 0,
        });
        if (predictionNavigationFlowId) {
            markFlow(predictionNavigationFlowId, 'prediction:chart-visible', {
                range,
                historyCount: chartState.data.history?.length ?? 0,
                projectionCount: chartState.data.projection?.length ?? 0,
            });
            endFlow(predictionNavigationFlowId, 'prediction:first-screen-ready', {
                range,
                summaryReady: Boolean(summaryState.data),
                chartReady: true,
            });
        }
    }, [chartState.data, range, summaryState.data, chartVisibleRef]);

    useEffect(() => {
        setAiPerspective(audiencePreference === AUDIENCE_PREFERENCES.BANK ? 'bank' : 'corporate');
    }, [audiencePreference]);

    useEffect(() => {
        if (!isAiDetailOpen) {
            return undefined;
        }

        let cancelled = false;
        setAiAnalysisState({ data: null, loading: true, error: '' });
        measurePromise('prediction:ai-analysis', () => apiGetPredictionAiAnalysis(), { flowId: getActiveFlowId('prediction-navigation') })
            .then((data) => {
                if (!cancelled) {
                    setAiAnalysisState({ data, loading: false, error: '' });
                }
            })
            .catch((error) => {
                if (!cancelled) {
                    setAiAnalysisState({ data: null, loading: false, error: error instanceof Error ? error.message : '获取 AI 分析失败' });
                }
            });

        return () => {
            cancelled = true;
        };
    }, [isAiDetailOpen]);

    useEffect(() => {
        if (!isAiDetailOpen || !aiAnalysisState.data || aiDetailVisibleRef.current) {
            return;
        }
        aiDetailVisibleRef.current = true;
        markEvent('prediction:ai-detail-visible', {
            referenceCount: aiAnalysisState.data.references?.length ?? 0,
        });
    }, [aiAnalysisState.data, isAiDetailOpen, aiDetailVisibleRef]);

    useEffect(() => {
        if (!isAiDetailOpen) {
            setIsReferencesExpanded(false);
        }
    }, [isAiDetailOpen]);

    useEffect(() => {
        if (!isAiDetailOpen) {
            return undefined;
        }
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = previousOverflow;
        };
    }, [isAiDetailOpen]);

    return (
        <div className="panel panel--page">
            <div className="prediction-header">
                <div>
                    <h2>{summary?.headline ?? 'WTI 原油价格多因子量化预测'}<span className="badge">LIVE COMPUTING</span></h2>
                    <p>{predictionDescription}</p>
                </div>
                <div className="prediction-stats">
                    <div>
                        <span>{summary?.forecastWindowLabel ?? '未来10个交易日价格区间'}</span>
                        <strong>{summary?.next10DayForecast ?? '--'}</strong>
                    </div>
                    <div>
                        <span>Risk Signal</span>
                        <strong className="risk" style={metricToneStyles[riskSignalTone] ?? undefined}><AlertTriangle size={18} />{summary?.riskSignal ?? '--'}</strong>
                    </div>
                </div>
            </div>

            <div className="chart-box">
                <div className="chart-box__title" style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
                    <span>WTI Crude Oil Spot Price ({range})</span>
                    <RangeToggle value={range} onChange={setRange} ranges={predictionChartRanges} />
                </div>
                <PredictionRangeChart
                    renderKey={chartRenderKey}
                    range={range}
                    chartData={chartData}
                    timeZone={resolvedTimezone}
                    referenceX={history.at(-1)?.observed_at}
                />
            </div>

            <div className="insight-grid">
                <section
                    className={`info-box info-box--clickable${!isAiAnalysisAvailable ? ' is-disabled' : ''}`}
                    role={isAiAnalysisAvailable ? 'button' : undefined}
                    tabIndex={isAiAnalysisAvailable ? 0 : -1}
                    onClick={() => isAiAnalysisAvailable && setIsAiDetailOpen(true)}
                    onKeyDown={(event) => {
                        if (!isAiAnalysisAvailable) {
                            return;
                        }
                        if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            setIsAiDetailOpen(true);
                        }
                    }}
                >
                    <div className="info-box__title info-box__title--preview">
                        <span className="info-box__title-main">
                            <Cpu size={16} />
                            Model Insights (Natural Language Generation)
                        </span>
                        <span className="info-box__hint">{isAiAnalysisAvailable ? '点击查看详情' : '详情暂不可用'}</span>
                    </div>
                    <div className="info-box__body info-box__body--preview">
                        <span className="insight-preview__eyebrow">AI PREVIEW</span>
                        <p className="insight-preview__summary">{aiSummary}</p>
                        <div className="insight-preview__meta">
                            <span>模型结果更新时间：{formatSourceTime(aiSummaryUpdatedAt, resolvedTimezone)}</span>
                            <span>{aiPreviewSummary ? '概览文案已特化生成' : '等待后端生成独立概览摘要'}</span>
                        </div>
                    </div>
                </section>

                <section className="info-box">
                    <div className="info-box__title">Top Feature Importance</div>
                    <div className="info-box__body">
                        {featureImportance.map((feature) => (
                            <div key={feature.feature} className="feature-row">
                                <span>{feature.feature}</span>
                                <div className="feature-row__bar"><div style={{ width: `${feature.value}%` }} /></div>
                            </div>
                        ))}
                        {!featureImportance.length ? <p className="info-box__empty">暂无关键特征重要性数据。</p> : null}
                    </div>
                </section>
            </div>

            {isAiDetailOpen ? (
                <div className="prediction-detail-modal" role="dialog" aria-modal="true" aria-label="AI 分析详情">
                    <div className="prediction-detail-modal__backdrop" onClick={() => setIsAiDetailOpen(false)} />
                    <section className="prediction-detail-modal__panel">
                        <header className="prediction-detail-modal__header">
                            <div className="prediction-detail-modal__titleBlock">
                                <span className="prediction-detail-modal__eyebrow">AI ADVISORY DETAIL</span>
                                <h3><Cpu size={18} />AI 分析详情</h3>
                                <p>按新闻正文式阅读布局呈现双视角 AI 分析，左侧聚焦正文结论，右侧集中展示预测摘要、模型状态、关键驱动与引用来源。</p>
                            </div>
                            <div className="prediction-detail-modal__controls">
                                <div className="ai-detail-switch">
                                    <button type="button" className={`ai-detail-switch__item${aiPerspective === 'corporate' ? ' is-active' : ''}`} onClick={() => setAiPerspective('corporate')}>企业侧</button>
                                    <button type="button" className={`ai-detail-switch__item${aiPerspective === 'bank' ? ' is-active' : ''}`} onClick={() => setAiPerspective('bank')}>银行侧</button>
                                </div>
                                <button
                                    type="button"
                                    className="prediction-detail-modal__close"
                                    onClick={() => setIsAiDetailOpen(false)}
                                    aria-label="关闭 AI 分析详情"
                                >
                                    <X size={18} />
                                </button>
                            </div>
                        </header>

                        <div className="prediction-detail-modal__content">
                            <div className="prediction-detail-modal__body">
                                {aiAnalysisState.loading ? <p>AI 分析加载中...</p> : null}
                                {!aiAnalysisState.loading && aiAnalysisState.error ? <p>{aiAnalysisState.error}</p> : null}
                                {!aiAnalysisState.loading && !aiAnalysisState.error && !activeAiView ? <p>暂无 AI 分析详情数据。</p> : null}
                                {!aiAnalysisState.loading && !aiAnalysisState.error && activeAiView ? (
                                    <>
                                        <div className="prediction-detail-modal__articleHeader">
                                            <span className="prediction-detail-modal__articleEyebrow">{aiPerspective === 'corporate' ? 'CORPORATE VIEW' : 'BANK VIEW'}</span>
                                            {activeAiView.title ? <h4 className="prediction-detail-modal__sectionTitle">{activeAiView.title}</h4> : null}
                                        </div>
                                        <article className="ai-detail-body">
                                            <AiDetailContent content={activeAiView.summary} />
                                        </article>
                                        {activeAiView.highlights.length ? <ul className="ai-detail-list">{activeAiView.highlights.map((item, index) => <li key={`${aiPerspective}-highlight-${index}`}>{item}</li>)}</ul> : null}
                                    </>
                                ) : null}
                            </div>

                            <aside className="prediction-detail-modal__sidebar">
                                <div className="prediction-detail-modal__metaCard prediction-detail-modal__statusCard">
                                    <span>模型状态</span>
                                    <div className="prediction-detail-modal__statusList">
                                        {aiStatusItems.map((item) => (
                                            <div key={item.label} className="prediction-detail-modal__statusRow">
                                                <span>{item.label}</span>
                                                <strong>{item.value}</strong>
                                            </div>
                                        ))}
                                    </div>
                                    {aiAnalysisState.data?.lastError ? <p className="prediction-detail-modal__errorText">最近一次重生成失败：{aiAnalysisState.data.lastError}</p> : null}
                                </div>

                                {aiPredictionSummaryMetrics.metrics.length ? (
                                    <div className="prediction-detail-modal__metricsGrid">
                                        {aiPredictionSummaryMetrics.metrics.map((metric) => (
                                            <div
                                                key={metric.label}
                                                className="prediction-detail-modal__metaCard prediction-detail-modal__metricCard"
                                            >
                                                <span>{metric.label}</span>
                                                <strong style={metricToneStyles[metric.tone] ?? undefined}>{metric.value}</strong>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="prediction-detail-modal__metaCard prediction-detail-modal__summaryCard">
                                        <span>预测摘要</span>
                                        <strong>{aiPredictionSummaryMetrics.fallbackText || aiPredictionSummary}</strong>
                                    </div>
                                )}

                                <div className="prediction-detail-modal__metaCard">
                                    <span>关键驱动因子</span>
                                    {aiDrivers.length ? (
                                        <div className="prediction-detail-modal__tagList">
                                            {aiDrivers.map((driver) => <span key={driver} className="prediction-detail-modal__tag">#{driver}</span>)}
                                        </div>
                                    ) : (
                                        <strong>暂无关键驱动数据</strong>
                                    )}
                                </div>

                                <div className="prediction-detail-modal__metaCard prediction-detail-modal__referencesCard">
                                    <button
                                        type="button"
                                        className={`prediction-detail-modal__referencesHeader${isReferencesExpanded ? ' is-expanded' : ''}`}
                                        onClick={() => setIsReferencesExpanded((current) => !current)}
                                        aria-expanded={isReferencesExpanded}
                                        aria-label={isReferencesExpanded ? '收起来源详情' : '展开来源详情'}
                                    >
                                        <span>来源概览</span>
                                        <div className="prediction-detail-modal__referencesSummary">
                                            <strong>{aiReferenceCount}</strong>
                                            <ChevronDown size={16} className="prediction-detail-modal__referencesChevron" />
                                        </div>
                                    </button>
                                    {isReferencesExpanded && aiReferences.length ? (
                                        <ul className="prediction-detail-modal__referenceList">
                                            {aiReferences.map((reference, index) => (
                                                <li key={`${reference.source}-${index}`} className="prediction-detail-modal__referenceItem">
                                                    <strong>[{reference.category}] {reference.source}</strong>
                                                    <span>{reference.excerpt}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    ) : null}
                                    {isReferencesExpanded && !aiReferences.length ? (
                                        <strong>暂无检索来源</strong>
                                    ) : null}
                                </div>
                            </aside>
                        </div>
                    </section>
                </div>
            ) : null}
        </div>
    );
}
