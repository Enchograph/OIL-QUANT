import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Building2, ChevronDown, Database, Landmark, RefreshCw, Send, Sparkles, TerminalSquare, User } from 'lucide-react';
import { AUDIENCE_PREFERENCES, useAudiencePreference } from '../../audiencePreference';
import { useTimezone } from '../../timezone';
import { formatSourceTime } from '../../utils/formatters';
import { QaChartCard } from '../../components/charts/QaBriefingCharts';
import {
    clearStoredQaSession,
    fetchQaBootstrap,
    isCompatibleQaSession,
    loadStoredQaSession,
    persistQaSession,
    sendQaQuestion,
} from '../../services/qaService';

function buildAudienceMeta(audience) {
    return {
        label: audience === AUDIENCE_PREFERENCES.BANK ? '银行侧' : '企业侧',
        icon: audience === AUDIENCE_PREFERENCES.BANK ? Landmark : Building2,
    };
}

function groupPrompts(items) {
    return items.reduce((groups, item) => {
        const key = item.group || '推荐问题';
        if (!groups[key]) groups[key] = [];
        groups[key].push(item);
        return groups;
    }, {});
}

function normalizeMessageCharts(answer) {
    if (Array.isArray(answer?.charts) && answer.charts.length > 0) {
        return answer.charts
            .filter((chart) => chart && typeof chart === 'object' && typeof chart.kind === 'string' && chart.kind.trim())
            .sort((left, right) => Number(left?.priority || 0) - Number(right?.priority || 0));
    }
    if (answer?.chart) {
        const chart = answer.chart;
        const normalizedCharts = [
            {
                id: chart.id || 'legacy-chart',
                kind: chart.kind,
                title: chart.title,
                subtitle: chart.subtitle || '',
                priority: chart.priority || 1,
                data: chart.data || {
                    points: chart.points || [],
                    items: chart.items || [],
                    stats: chart.stats || [],
                    segments: chart.segments || [],
                },
                footnote: chart.footnote || '',
            },
        ];
        return normalizedCharts.filter((item) => item.kind);
    }
    return [];
}

function normalizeMessageSections(answer) {
    if (!Array.isArray(answer?.sections)) {
        return [];
    }
    return answer.sections
        .filter((section) => section && typeof section === 'object')
        .map((section, index) => {
            const items = Array.isArray(section.items)
                ? section.items.filter((item) => typeof item === 'string' && item.trim())
                : [];
            const content = typeof section.content === 'string'
                ? section.content.trim()
                : Array.isArray(section.content)
                    ? section.content
                        .filter((item) => typeof item === 'string' && item.trim())
                        .join(' ')
                        .trim()
                    : '';
            const title = typeof section.title === 'string' && section.title.trim() ? section.title.trim() : `分析要点 ${index + 1}`;

            if (items.length > 0) {
                return {
                    id: `section-${index}`,
                    type: 'section',
                    title,
                    bodyType: 'list',
                    items,
                    content: '',
                };
            }
            if (content) {
                return {
                    id: `section-${index}`,
                    type: 'section',
                    title,
                    bodyType: 'text',
                    items: [],
                    content,
                };
            }
            return null;
        })
        .filter(Boolean);
}

function buildContentBlocks(answer) {
    const sections = normalizeMessageSections(answer);
    const charts = normalizeMessageCharts(answer);
    const blocks = [...sections];

    if (!sections.length) {
        return charts.map((chart, index) => ({
            type: 'chart',
            chart,
            id: chart.id || `chart-${index}`,
        }));
    }

    charts.forEach((chart, index) => {
        const insertIndex = Math.min((index * 2) + 1, blocks.length);
        blocks.splice(insertIndex, 0, {
            type: 'chart',
            chart,
            id: chart.id || `chart-${index}`,
        });
    });

    return blocks;
}

function AssistantMessage({ message, isEvidenceOpen, onToggleEvidence, onFollowup, timeZone }) {
    const audienceMeta = buildAudienceMeta(message.answer?.audience);
    const AudienceIcon = audienceMeta.icon;
    const contentBlocks = buildContentBlocks(message.answer);
    const hasBodyContent = contentBlocks.length > 0;

    return (
        <div className="qa-turn">
            <article className="qa-message">
                <header className="qa-message__header">
                    <div className="qa-message__title">
                        <div className="chat-ai-avatar"><Bot size={14} /></div>
                        <strong>{message.answer?.title || '分析报告'}</strong>
                        <span className="qa-message__time">{formatSourceTime(message.createdAt, timeZone)}</span>
                    </div>
                    <div className="qa-message__tags">
                        <span className="qa-tag"><AudienceIcon size={12} /> {audienceMeta.label}</span>
                        {message.answer?.confidenceLabel && <span className="qa-tag">{message.answer.confidenceLabel}</span>}
                        {(message.answer?.usedDomains || []).map((item) => <span key={item} className="qa-tag tag-ghost">{item}</span>)}
                    </div>
                </header>

                {message.answer?.summary && (
                    <div className="qa-message__summary">
                        <div className="qa-message__summaryLabel">核心判断</div>
                        <p className="qa-message__summaryText">{message.answer.summary}</p>
                    </div>
                )}

                {hasBodyContent && (
                    <div className="qa-message__body">
                        <div className="qa-message__grid">
                            {contentBlocks.map((block, index) => (
                                block.type === 'section' ? (
                                    <section
                                        key={`${message.id}-${block.id}`}
                                        className="qa-section qa-grid-card"
                                    >
                                        <h3 className="qa-section__title">{block.title}</h3>
                                        {block.bodyType === 'list' ? (
                                            <ul>{block.items.map((item) => <li key={item}>{item}</li>)}</ul>
                                        ) : (
                                            <p>{block.content}</p>
                                        )}
                                    </section>
                                ) : block.chart ? (
                                    <QaChartCard
                                        key={`${message.id}-${block.id}`}
                                        chart={block.chart}
                                        className="qa-grid-card"
                                    />
                                ) : null
                            ))}
                        </div>
                    </div>
                )}

                {/* 展开下栏语义：溯源数据开关 */}
                {(message.evidence || []).length > 0 && (
                    <div className="qa-evidence-bar" onClick={() => onToggleEvidence(message.id)}>
                        <div className="qa-evidence-bar__label">
                            <Database size={14} /> 展开依据溯源详情
                        </div>
                        <ChevronDown size={14} className={`chevron ${isEvidenceOpen ? 'is-open' : ''}`} />
                    </div>
                )}

                {/* 抽屉内容 */}
                {isEvidenceOpen && (
                    <div className="qa-evidence-drawer">
                        {(message.evidence || []).map((item, index) => (
                            <div key={`${message.id}-evidence-${index}`} className="qa-evidence-card">
                                <div className="evidence-meta">
                                    <span className="evidence-kind">{item.kind}</span>
                                    {item.timestamp ? <span className="evidence-time">{formatSourceTime(item.timestamp, timeZone)}</span> : null}
                                </div>
                                <strong>{item.title}</strong>
                                <p>{item.summary}</p>
                                {item.targetTab ? <span className="evidence-target">关联页面：{item.targetTab}</span> : null}
                            </div>
                        ))}
                    </div>
                )}
            </article>

            {/* 追问独立在卡片外部 */}
            {(message.followups || []).length > 0 && (
                <div className="qa-followups-outside">
                    {(message.followups || []).map((item) => (
                        <button key={`${message.id}-${item}`} type="button" className="followup-chip" onClick={() => onFollowup(item)}>
                            {item}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

export default function QAView() {
    const { audiencePreference } = useAudiencePreference();
    const { resolvedTimezone } = useTimezone();
    const storedSession = useMemo(() => {
        const session = loadStoredQaSession();
        if (!isCompatibleQaSession(session)) {
            return null;
        }
        return session;
    }, []);
    const initialSession = storedSession;
    const [bootstrapState, setBootstrapState] = useState({
        data: null,
        loading: true,
        error: '',
    });
    const [conversationState, setConversationState] = useState(() => ({
        sessionId: initialSession?.sessionId || '',
        messages: initialSession?.messages || [],
    }));
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [sendError, setSendError] = useState('');
    const [activeEvidenceId, setActiveEvidenceId] = useState('');
    const messagesContainerRef = useRef(null);

    useEffect(() => {
        setBootstrapState((current) => ({
            data: initialSession?.bootstrap || current.data,
            loading: true,
            error: '',
        }));
        fetchQaBootstrap()
            .then((data) => setBootstrapState({ data, loading: false, error: '' }))
            .catch((error) => setBootstrapState((current) => ({
                data: initialSession?.bootstrap || current.data,
                loading: false,
                error: error.message || '真实数据源初始化失败',
            })));
    }, [initialSession?.bootstrap]);

    useEffect(() => {
        setConversationState({
            sessionId: initialSession?.sessionId || '',
            messages: initialSession?.messages || [],
        });
    }, [initialSession]);

    useEffect(() => {
        persistQaSession({
            sessionId: conversationState.sessionId,
            messages: conversationState.messages,
            bootstrap: bootstrapState.data,
        });
    }, [bootstrapState.data, conversationState]);

    useEffect(() => {
        if (messagesContainerRef.current) {
            messagesContainerRef.current.scrollTo({ top: messagesContainerRef.current.scrollHeight, behavior: 'smooth' });
        }
    }, [conversationState.messages, sending]);

    const dispatchQuestion = async (question) => {
        const trimmedQuestion = question.trim();
        if (!trimmedQuestion || sending) return;

        const userMessage = { id: `user-${Date.now()}`, role: 'user', content: trimmedQuestion, createdAt: new Date().toISOString() };
        const history = [...conversationState.messages, userMessage];
        setConversationState(prev => ({ ...prev, messages: history }));
        setInput(''); setSending(true); setSendError('');

        try {
            const result = await sendQaQuestion({
                question: trimmedQuestion,
                session: {
                    sessionId: conversationState.sessionId,
                    history: history.slice(-6).map((item) => ({
                        role: item.role,
                        content: item.role === 'user' ? item.content : item.answer?.summary,
                    })),
                },
                context: { sourcePage: 'qa', mode: 'live' },
                options: {
                    audience: audiencePreference,
                    includeEvidence: true,
                    responseMode: 'briefing',
                },
            });

            const assistantMessage = {
                id: `assistant-${Date.now()}`,
                role: 'assistant',
                answer: result.answer,
                evidence: result.evidence || [],
                followups: result.followups || [],
                createdAt: result.session?.answeredAt || new Date().toISOString(),
            };
            setConversationState({ sessionId: result.session?.sessionId || conversationState.sessionId || '', messages: [...history, assistantMessage] });
        } catch (error) {
            setSendError(error.message || '发送失败');
            setConversationState(prev => ({ ...prev, messages: prev.messages.filter(i => i.id !== userMessage.id) }));
        } finally {
            setSending(false);
        }
    };

    const audienceMeta = buildAudienceMeta(audiencePreference);

    return (
        <div className="layout-qa">
            <header className="topbar">
                <div className="topbar__brand">
                    <TerminalSquare size={18} />
                    <h1>ANALYSIS COPILOT</h1>
                    <span className="topbar__mode">LIVE</span>
                </div>
                <div className="topbar__actions">
                    <span className="topbar__audience"><audienceMeta.icon size={14} /> {audienceMeta.label}</span>
                    {conversationState.messages.length > 0 && (
                        <button className="btn-icon" onClick={() => { clearStoredQaSession(); setConversationState({ sessionId: '', messages: [] }); }}>
                            <RefreshCw size={14} /> 清空会话
                        </button>
                    )}
                </div>
            </header>

            <main ref={messagesContainerRef} className="feed">
                {!conversationState.messages.length ? (
                    <div className="welcome-panel">
                        <div className="welcome-panel__inner">
                            <div className="welcome-panel__header">
                                <Sparkles size={16} className="icon-brand" />
                                <h2>{bootstrapState.data?.welcome || '分析助手已就绪'}</h2>
                            </div>
                            {bootstrapState.loading && (
                                <div className="composer-error">正在刷新真实数据上下文...</div>
                            )}
                            {bootstrapState.error && (
                                <div className="composer-error">
                                    真实数据源暂不可用：{bootstrapState.error}
                                </div>
                            )}

                            <div className="context-bar">
                                <strong className="context-bar__label">数据上下文：</strong>
                                {(bootstrapState.data?.dataContexts || []).map(item => (
                                    <span key={item.id} className={`context-tag is-${item.status}`}>
                                        {item.label}: {item.detail}
                                    </span>
                                ))}
                            </div>

                            <div className="prompt-grid">
                                {(bootstrapState.data?.recommendedPrompts || []).map((item) => (
                                    <button key={item.id} className="prompt-card" onClick={() => dispatchQuestion(item.question)}>
                                        <div className="prompt-card__group">{item.group}</div>
                                        <div className="prompt-card__label">{item.label}</div>
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="conversation">
                        {conversationState.messages.map((message) => (
                            message.role === 'user' ? (
                                <div key={message.id} className="msg-user">
                                    <div className="chat-user-avatar"><User size={14} /></div>
                                    <div className="msg-user__bubble">{message.content}</div>
                                </div>
                            ) : (
                                <AssistantMessage
                                    key={message.id}
                                    message={message}
                                    isEvidenceOpen={activeEvidenceId === message.id}
                                    onToggleEvidence={(msgId) => setActiveEvidenceId(c => c === msgId ? '' : msgId)}
                                    onFollowup={dispatchQuestion}
                                    timeZone={resolvedTimezone}
                                />
                            )
                        ))}
                        {sending && (
                            <div className="msg-loading">
                                <Bot size={16} className="spin-slow icon-brand" />
                                <span>正在聚合模型预测与因子数据...</span>
                            </div>
                        )}
                    </div>
                )}
            </main>

            <footer className="bottombar">
                <div className="composer-wrapper">
                    <div className="composer">
                        <input
                            type="text"
                            placeholder="输入分析问题：驱动归因、策略建议、风险暴露..."
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && dispatchQuestion(input)}
                            disabled={sending}
                        />
                        <button onClick={() => dispatchQuestion(input)} disabled={sending || !input.trim()}>
                            <Send size={16} />
                        </button>
                    </div>
                    {sendError && <div className="composer-error">{sendError}</div>}
                </div>
            </footer>
        </div>
    );
}
