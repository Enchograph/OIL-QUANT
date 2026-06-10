import { resolveScreenerBarStyle } from '../dashboardLive';

describe('dashboard screener helpers', () => {
    test('zScore 为 0 时仍保留最小可见宽度', () => {
        expect(resolveScreenerBarStyle(0)).toEqual({
            left: '49.25%',
            width: '1.5%',
            hasMinimumWidth: true,
        });
    });

    test('正负 zScore 继续围绕中轴展开', () => {
        expect(resolveScreenerBarStyle(2)).toEqual({
            left: '50%',
            width: '33.33%',
            hasMinimumWidth: false,
        });
        expect(resolveScreenerBarStyle(-2)).toEqual({
            left: '16.67%',
            width: '33.33%',
            hasMinimumWidth: false,
        });
    });
});
