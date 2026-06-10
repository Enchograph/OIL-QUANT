export const predictionChartRanges = ['1M', '3M', '1Y'];

export function resolvePredictionDescription(summaryState) {
    if (summaryState?.data?.description) {
        return summaryState.data.description;
    }
    if (summaryState?.loading) {
        return '模型结果加载中...';
    }
    if (summaryState?.error) {
        return `模型结果加载失败：${summaryState.error}`;
    }
    return '暂无模型结果说明。';
}

export function resolveAiPreviewSummary(summary, aiAnalysis) {
    const candidates = [
        summary?.aiInsightPreview,
        summary?.aiPreviewSummary,
        summary?.aiInsightSummary,
        aiAnalysis?.previewSummary,
    ];
    return candidates.find((item) => typeof item === 'string' && item.trim()) ?? '';
}

export function resolveAiAvailability(summary, aiAnalysis) {
    if (summary?.aiAnalysisAvailable === true) {
        return true;
    }
    return Boolean(
        resolveAiPreviewSummary(summary, aiAnalysis) ||
        summary?.insight ||
        aiAnalysis?.predictionSummary ||
        ((aiAnalysis?.views?.corporate ?? aiAnalysis?.views?.bank)?.body),
    );
}

export function resolvePredictionSummaryMetrics(summaryText) {
    if (typeof summaryText !== 'string') {
        return { metrics: [], fallbackText: '' };
    }

    const normalized = summaryText.trim();
    if (!normalized) {
        return { metrics: [], fallbackText: '' };
    }

    const segments = normalized
        .split('|')
        .map((segment) => segment.trim())
        .filter(Boolean);

    if (!segments.length) {
        return { metrics: [], fallbackText: normalized };
    }

    const metrics = segments.map((segment) => {
        const match = segment.match(/^(.+?)\s+(.+)$/);
        if (!match) {
            return null;
        }

        const label = match[1].trim();
        const value = match[2].trim();

        return {
            label,
            value,
            tone: resolvePredictionMetricTone(label, value),
        };
    });

    if (metrics.some((metric) => !metric)) {
        return { metrics: [], fallbackText: normalized };
    }

    return { metrics, fallbackText: '' };
}

function resolvePredictionMetricTone(label, value) {
    if (label === '变化' || label.includes('预测变动')) {
        const change = Number.parseFloat(value.replace('%', ''));
        if (Number.isFinite(change)) {
            if (change > 0) {
                return 'up';
            }
            if (change < 0) {
                return 'down';
            }
        }
        return 'neutral';
    }

    if (label === '风险等级') {
        if (value.includes('高')) {
            return 'down';
        }
        if (value.includes('中')) {
            return 'warning';
        }
        if (value.includes('低')) {
            return 'up';
        }
    }

    return 'neutral';
}

export function resolveRiskSignalTone(value) {
    if (typeof value !== 'string') {
        return 'warning';
    }

    if (value.includes('高')) {
        return 'down';
    }
    if (value.includes('低')) {
        return 'up';
    }
    return 'warning';
}

export function resolveFeatureImportance(summary) {
    const primary = Array.isArray(summary?.featureImportance)
        ? summary.featureImportance.filter((item) => item?.feature && Number.isFinite(Number(item?.value)))
        : [];
    if (primary.length) {
        return primary.map((item) => ({
            feature: item.feature,
            value: Number(item.value),
        }));
    }

    const topMovers = Array.isArray(summary?.topMovers) ? summary.topMovers.filter((item) => item?.factor) : [];
    return topMovers.slice(0, 5).map((item, index) => ({
        feature: item.factor,
        value: Math.max(5, 100 - index * 12),
    }));
}

export function buildPredictionChartRenderKey(range, chartData) {
    if (!Array.isArray(chartData) || !chartData.length) {
        return `${range}-empty`;
    }
    const lastPoint = chartData.at(-1);
    return `${range}-ready-${chartData.length}-${lastPoint?.dateMs ?? 'na'}`;
}
