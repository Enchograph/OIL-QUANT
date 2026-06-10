import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import DashboardTooltip from '../components/charts/DashboardTooltip';

describe('DashboardTooltip', () => {
    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    });

    afterAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    });

    test('支持按行渲染数值颜色 class 并显示时间行', () => {
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        act(() => {
            root.render(
                <DashboardTooltip
                    active
                    payload={[{ payload: { value: 72.34, observed_at: '2026-03-31T08:15:00Z' } }]}
                    title="WTI"
                    rows={() => [
                        { label: '时间', value: '03/31 08:15 UTC' },
                        { label: 'Current', value: 72.34, valueClassName: 'up' },
                    ]}
                />,
            );
        });

        const rowValues = [...container.querySelectorAll('.dashboard-tooltip__row strong')];
        expect(rowValues).toHaveLength(2);
        expect(rowValues[0].textContent).toBe('03/31 08:15 UTC');
        expect(rowValues[1].textContent).toBe('72.34');
        expect(rowValues[1].className).toContain('up');

        act(() => {
            root.unmount();
        });
        container.remove();
    });
});
