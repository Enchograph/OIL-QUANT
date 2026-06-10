import { resolvePredictionTooltipRows } from '../components/charts/PredictionRangeChart';

describe('resolvePredictionTooltipRows', () => {
    test('为预测提示框稳定返回英文标签的预测值、上界、下界三行，并使用可辨识的语义色', () => {
        const rows = resolvePredictionTooltipRows({
            historical: null,
            prediction: 72.0,
            upperBound: 74.0,
            lowerBound: 70.0,
        });

        expect(rows).toEqual([
            { label: 'Prediction', value: 72.0, valueClassName: 'prediction' },
            { label: 'Upper Bound', value: 74.0, valueClassName: 'upper-bound' },
            { label: 'Lower Bound', value: 70.0, valueClassName: 'lower-bound' },
        ]);
    });
});
