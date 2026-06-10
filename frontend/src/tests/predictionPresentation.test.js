describe('prediction presentation helpers', () => {
    test('在 summary 已有真实描述时优先展示真实描述', () => {
        const { resolvePredictionDescription } = require('../views/prediction/presentation');

        expect(resolvePredictionDescription({
            data: {
                description: '以原生分位数价格输出未来 10 个交易日价格区间与风险提示。',
            },
            loading: false,
            error: '',
        })).toBe('以原生分位数价格输出未来 10 个交易日价格区间与风险提示。');
    });

    test('在 AI 详情已存在时不再把 AI 分析误判为不可用', () => {
        const { resolveAiAvailability } = require('../views/prediction/presentation');

        expect(resolveAiAvailability(
            {
                aiAnalysisAvailable: false,
                aiInsightPreview: '',
                insight: '',
            },
            {
                predictionSummary: '未来10个交易日预测承压近7%，趋势明确转跌。',
            },
        )).toBe(true);
    });

    test('在首页摘要缺失时回退到 AI 详情 previewSummary', () => {
        const { resolveAiPreviewSummary } = require('../views/prediction/presentation');

        expect(resolveAiPreviewSummary(
            {
                aiInsightPreview: '',
                aiPreviewSummary: '',
                aiInsightSummary: '',
            },
            {
                previewSummary: '建议企业客户立即为未来3-6个月敞口建立40%-60%的空头套保头寸。',
            },
        )).toBe('建议企业客户立即为未来3-6个月敞口建立40%-60%的空头套保头寸。');
    });

    test('featureImportance 为空时从 topMovers 生成回退展示数据', () => {
        const { resolveFeatureImportance } = require('../views/prediction/presentation');

        expect(resolveFeatureImportance({
            featureImportance: [],
            topMovers: [
                { factor: 'WTI_Crude_Oil' },
                { factor: 'WTI_MA_5' },
                { factor: 'Japan_con' },
            ],
        })).toEqual([
            { feature: 'WTI_Crude_Oil', value: 100 },
            { feature: 'WTI_MA_5', value: 88 },
            { feature: 'Japan_con', value: 76 },
        ]);
    });

    test('图表在首批数据到达后应更新 render key 以强制重建', () => {
        const { buildPredictionChartRenderKey } = require('../views/prediction/presentation');

        expect(buildPredictionChartRenderKey('1M', [])).toBe('1M-empty');
        expect(buildPredictionChartRenderKey('1M', [{ dateMs: 1 }, { dateMs: 2 }])).toBe('1M-ready-2-2');
    });

    test('可将结构化预测摘要拆成四张指标卡数据', () => {
        const { resolvePredictionSummaryMetrics } = require('../views/prediction/presentation');

        expect(resolvePredictionSummaryMetrics('WTI $95.05 | Brent $99.33 | 10日预测变动 -6.92% | 风险等级 高风险')).toEqual({
            metrics: [
                { label: 'WTI', value: '$95.05', tone: 'neutral' },
                { label: 'Brent', value: '$99.33', tone: 'neutral' },
                { label: '10日预测变动', value: '-6.92%', tone: 'down' },
                { label: '风险等级', value: '高风险', tone: 'down' },
            ],
            fallbackText: '',
        });
    });

    test('旧版结构化预测摘要仍可拆成指标卡数据', () => {
        const { resolvePredictionSummaryMetrics } = require('../views/prediction/presentation');

        expect(resolvePredictionSummaryMetrics('WTI $95.05 | Brent $99.33 | 变化 -6.92% | 风险等级 高风险')).toEqual({
            metrics: [
                { label: 'WTI', value: '$95.05', tone: 'neutral' },
                { label: 'Brent', value: '$99.33', tone: 'neutral' },
                { label: '变化', value: '-6.92%', tone: 'down' },
                { label: '风险等级', value: '高风险', tone: 'down' },
            ],
            fallbackText: '',
        });
    });

    test('预测摘要格式异常时回退为原始整串文案', () => {
        const { resolvePredictionSummaryMetrics } = require('../views/prediction/presentation');

        expect(resolvePredictionSummaryMetrics('预测摘要生成中')).toEqual({
            metrics: [],
            fallbackText: '预测摘要生成中',
        });
    });

    test('风险信号等级映射为红黄绿色调', () => {
        const { resolveRiskSignalTone } = require('../views/prediction/presentation');

        expect(resolveRiskSignalTone('高风险')).toBe('down');
        expect(resolveRiskSignalTone('中风险')).toBe('warning');
        expect(resolveRiskSignalTone('低风险')).toBe('up');
        expect(resolveRiskSignalTone('--')).toBe('warning');
    });
});
