import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { LivePredictionView } from '../views/prediction';

jest.mock('react-markdown', () => ({ children }) => <>{children}</>);
jest.mock('remark-gfm', () => () => undefined);

jest.mock('../api', () => ({
    apiGet: jest.fn(),
    apiGetPredictionAiAnalysis: jest.fn(),
}));

jest.mock('../audiencePreference', () => ({
    AUDIENCE_PREFERENCES: {
        BANK: 'bank',
        CORPORATE: 'corporate',
    },
    useAudiencePreference: () => ({
        audiencePreference: 'corporate',
    }),
}));

jest.mock('../timezone', () => ({
    useTimezone: () => ({
        resolvedTimezone: 'UTC',
    }),
}));

jest.mock('../components/charts/PredictionRangeChart', () => () => <div data-testid="prediction-range-chart" />);

const { apiGet, apiGetPredictionAiAnalysis } = require('../api');

function flush() {
    return act(async () => {
        await Promise.resolve();
        await Promise.resolve();
    });
}

describe('LivePredictionView', () => {
    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    });

    afterAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    });

    beforeEach(() => {
        apiGet.mockImplementation((path) => {
            if (path === '/prediction/latest') {
                return Promise.resolve({
                    headline: 'WTI 原油价格多因子量化预测',
                    description: '预测说明',
                    forecastWindowLabel: '未来10个交易日价格区间',
                    next10DayForecast: '$70 - $80',
                    riskSignal: '中等风险',
                    aiAnalysisAvailable: true,
                    aiInsightPreview: '已有 AI 摘要',
                    updatedAt: '2026-03-30T00:00:00+00:00',
                });
            }
            if (path === '/prediction/chart') {
                return Promise.resolve({
                    history: [
                        { observed_at: '2026-03-29T00:00:00+00:00', close: 70.0 },
                        { observed_at: '2026-03-30T00:00:00+00:00', close: 71.0 },
                    ],
                    projection: [
                        { date: '2026-03-31', prediction: 72.0, lowerBound: 70.0, upperBound: 74.0 },
                    ],
                    updatedAt: '2026-03-30T00:00:00+00:00',
                });
            }
            return Promise.reject(new Error(`unexpected path: ${path}`));
        });
        apiGetPredictionAiAnalysis.mockResolvedValue({
            generatedAt: '2026-03-31T10:45:26.638905+00:00',
            predictionSummary: '预测摘要',
            views: {
                corporate: {
                    title: '企业侧视角',
                    body: '企业侧正文',
                },
                bank: {
                    title: '银行侧视角',
                    body: '银行侧正文',
                },
            },
            references: [],
        });
    });

    afterEach(() => {
        jest.clearAllMocks();
    });

    test('预测页只展示精简后的日级范围按钮', async () => {
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        await act(async () => {
            root.render(<LivePredictionView />);
        });
        await flush();

        const buttonLabels = Array.from(container.querySelectorAll('button')).map((button) => button.textContent?.trim());

        expect(buttonLabels).toEqual(expect.arrayContaining(['1M', '3M', '1Y']));
        expect(buttonLabels).not.toEqual(expect.arrayContaining(['1D', '1W']));

        await act(async () => {
            root.unmount();
        });
        container.remove();
    });

    test('每次重新打开 AI 详情弹窗都会重新拉取后端结果', async () => {
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        await act(async () => {
            root.render(<LivePredictionView />);
        });
        await flush();

        const trigger = container.querySelector('.info-box--clickable');
        expect(trigger).not.toBeNull();

        await act(async () => {
            trigger.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });
        await flush();

        const closeButton = container.querySelector('button[aria-label="关闭 AI 分析详情"]');
        expect(closeButton).not.toBeNull();

        await act(async () => {
            closeButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });
        await flush();

        await act(async () => {
            trigger.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });
        await flush();

        expect(apiGetPredictionAiAnalysis).toHaveBeenCalledTimes(2);

        await act(async () => {
            root.unmount();
        });
        container.remove();
    });
});
