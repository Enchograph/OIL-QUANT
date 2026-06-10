import { useEffect, useRef, useState } from 'react';

export function useApiResource(loader, deps, intervalMs = 0, enabled = true, options = {}) {
    const resolvedInitialData = options.initialData ?? null;
    const [state, setState] = useState({
        data: resolvedInitialData,
        loading: resolvedInitialData == null,
        error: '',
    });
    const inFlightRef = useRef(false);
    const pauseWhenHidden = options.pauseWhenHidden !== false;
    const onSuccess = options.onSuccess;

    useEffect(() => {
        if (!enabled) {
            setState({
                data: null,
                loading: false,
                error: '',
            });
            return undefined;
        }

        let cancelled = false;

        const run = async () => {
            if (inFlightRef.current) {
                return;
            }
            if (pauseWhenHidden && typeof document !== 'undefined' && document.visibilityState === 'hidden') {
                return;
            }

            inFlightRef.current = true;
            try {
                const data = await loader();
                if (!cancelled) {
                    setState({ data, loading: false, error: '' });
                    if (typeof onSuccess === 'function') {
                        onSuccess(data);
                    }
                }
            } catch (error) {
                if (!cancelled) {
                    setState((current) => ({
                        data: current.data,
                        loading: false,
                        error: error instanceof Error ? error.message : '请求失败',
                    }));
                }
            } finally {
                inFlightRef.current = false;
            }
        };

        const handleVisibilityChange = () => {
            if (!pauseWhenHidden || typeof document === 'undefined') {
                return;
            }
            if (document.visibilityState !== 'visible') {
                return;
            }
            run();
        };

        run();
        if (pauseWhenHidden && typeof document !== 'undefined') {
            document.addEventListener('visibilitychange', handleVisibilityChange);
        }
        if (!intervalMs) {
            return () => {
                cancelled = true;
                if (pauseWhenHidden && typeof document !== 'undefined') {
                    document.removeEventListener('visibilitychange', handleVisibilityChange);
                }
            };
        }

        const timer = window.setInterval(run, intervalMs);
        return () => {
            cancelled = true;
            window.clearInterval(timer);
            if (pauseWhenHidden && typeof document !== 'undefined') {
                document.removeEventListener('visibilitychange', handleVisibilityChange);
            }
        };
    }, [enabled, ...deps]);

    return state;
}
