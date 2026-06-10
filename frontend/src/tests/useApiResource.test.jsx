import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { useApiResource } from '../hooks/useApiResource';

function ResourceProbe({ loader, intervalMs = 60000, options, onRender }) {
    const state = useApiResource(loader, [], intervalMs, true, options);
    onRender(state);
    return null;
}

describe('useApiResource', () => {
    let originalVisibilityState;

    beforeAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = true;
        originalVisibilityState = Object.getOwnPropertyDescriptor(document, 'visibilityState');
    });

    afterAll(() => {
        globalThis.IS_REACT_ACT_ENVIRONMENT = false;
        if (originalVisibilityState) {
            Object.defineProperty(document, 'visibilityState', originalVisibilityState);
        }
    });

    afterEach(() => {
        jest.useRealTimers();
        jest.clearAllMocks();
        if (originalVisibilityState) {
            Object.defineProperty(document, 'visibilityState', originalVisibilityState);
        }
    });

    test('页面初始隐藏时，在恢复可见后立即补发请求', async () => {
        jest.useFakeTimers();

        Object.defineProperty(document, 'visibilityState', {
            configurable: true,
            get: () => 'hidden',
        });

        const loader = jest.fn().mockResolvedValue({ ok: true });
        const renders = [];
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        await act(async () => {
            root.render(<ResourceProbe loader={loader} onRender={(state) => renders.push(state)} />);
        });

        expect(loader).not.toHaveBeenCalled();

        Object.defineProperty(document, 'visibilityState', {
            configurable: true,
            get: () => 'visible',
        });

        await act(async () => {
            document.dispatchEvent(new Event('visibilitychange'));
            await Promise.resolve();
        });

        expect(loader).toHaveBeenCalledTimes(1);
        expect(renders.at(-1)).toEqual(
            expect.objectContaining({
                loading: false,
                error: '',
                data: { ok: true },
            }),
        );

        await act(async () => {
            root.unmount();
        });
        container.remove();
    });

    test('提供初始数据时，首屏直接渲染缓存并在请求完成后刷新', async () => {
        const loader = jest.fn().mockResolvedValue({ ok: 'fresh' });
        const renders = [];
        const container = document.createElement('div');
        document.body.appendChild(container);
        const root = createRoot(container);

        await act(async () => {
            root.render(
                <ResourceProbe
                    loader={loader}
                    options={{ initialData: { ok: 'cached' } }}
                    onRender={(state) => renders.push(state)}
                />,
            );
        });

        expect(renders[0]).toEqual(
            expect.objectContaining({
                loading: false,
                error: '',
                data: { ok: 'cached' },
            }),
        );

        await act(async () => {
            await Promise.resolve();
        });

        expect(loader).toHaveBeenCalledTimes(1);
        expect(renders.at(-1)).toEqual(
            expect.objectContaining({
                loading: false,
                error: '',
                data: { ok: 'fresh' },
            }),
        );

        await act(async () => {
            root.unmount();
        });
        container.remove();
    });
});
