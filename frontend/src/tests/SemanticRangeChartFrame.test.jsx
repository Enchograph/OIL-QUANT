import React from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react';
import SemanticRangeChartFrame from '../components/charts/SemanticRangeChartFrame';

describe('SemanticRangeChartFrame', () => {
    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    });

    afterAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    });

    test('animate=false 时不再输出带 framer-motion 过渡的容器', () => {
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        act(() => {
            root.render(
                <SemanticRangeChartFrame range="1M" animate={false}>
                    <div>chart</div>
                </SemanticRangeChartFrame>,
            );
        });

        const frame = container.querySelector('.semantic-chart-frame');
        expect(frame).not.toBeNull();
        expect(frame.style.transformOrigin).toBe('');

        act(() => {
            root.unmount();
        });
        container.remove();
    });
});
