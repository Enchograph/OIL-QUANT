const DEV_TRACE_KEY = '__oilQuantDevTrace';

function isEnabled() {
    return process.env.NODE_ENV !== 'production' && typeof window !== 'undefined';
}

function nowMs() {
    if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
        return performance.now();
    }
    return Date.now();
}

function getStore() {
    if (!isEnabled()) {
        return null;
    }

    if (!window[DEV_TRACE_KEY]) {
        window[DEV_TRACE_KEY] = {
            sequence: 0,
            activeFlows: {},
            events: [],
        };
    }

    return window[DEV_TRACE_KEY];
}

function appendEvent(kind, payload) {
    const store = getStore();
    if (!store) {
        return null;
    }

    const event = {
        index: store.events.length + 1,
        atMs: Number(nowMs().toFixed(2)),
        kind,
        ...payload,
    };
    store.events.push(event);
    const flowLabel = event.flowId ? ` [${event.flowId}]` : '';
    const detail = event.label ? ` ${event.label}` : '';
    const meta = event.meta ? ` ${JSON.stringify(event.meta)}` : '';
    console.info(`[开发态诊断 ${event.atMs}ms] ${kind}${flowLabel}${detail}${meta}`);
    return event;
}

export function beginFlow(flowName, meta = {}) {
    const store = getStore();
    if (!store) {
        return '';
    }
    store.sequence += 1;
    const flowId = `${flowName}-${store.sequence}`;
    store.activeFlows[flowName] = flowId;
    appendEvent('flow:start', { flowId, label: flowName, meta });
    return flowId;
}

export function getActiveFlowId(flowName) {
    return getStore()?.activeFlows?.[flowName] ?? '';
}

export function markFlow(flowId, label, meta = {}) {
    if (!flowId) {
        return null;
    }
    return appendEvent('flow:mark', { flowId, label, meta });
}

export function endFlow(flowId, label = 'complete', meta = {}) {
    if (!flowId) {
        return null;
    }
    const store = getStore();
    if (store) {
        Object.keys(store.activeFlows).forEach((flowName) => {
            if (store.activeFlows[flowName] === flowId) {
                delete store.activeFlows[flowName];
            }
        });
    }
    return appendEvent('flow:end', { flowId, label, meta });
}

export function markEvent(label, meta = {}) {
    return appendEvent('event', { label, meta });
}

export function measurePromise(label, factory, meta = {}) {
    if (!isEnabled()) {
        return factory();
    }

    const startedAt = nowMs();
    appendEvent('request:start', { label, meta });
    return factory()
        .then((value) => {
            appendEvent('request:end', {
                label,
                meta: {
                    ...meta,
                    status: 'success',
                    durationMs: Number((nowMs() - startedAt).toFixed(2)),
                },
            });
            return value;
        })
        .catch((error) => {
            appendEvent('request:end', {
                label,
                meta: {
                    ...meta,
                    status: 'error',
                    durationMs: Number((nowMs() - startedAt).toFixed(2)),
                    message: error instanceof Error ? error.message : String(error),
                },
            });
            throw error;
        });
}

export function markDuration(label, action, meta = {}) {
    if (!isEnabled()) {
        return action();
    }

    const startedAt = nowMs();
    appendEvent('duration:start', { label, meta });
    try {
        const result = action();
        appendEvent('duration:end', {
            label,
            meta: {
                ...meta,
                durationMs: Number((nowMs() - startedAt).toFixed(2)),
            },
        });
        return result;
    } catch (error) {
        appendEvent('duration:end', {
            label,
            meta: {
                ...meta,
                durationMs: Number((nowMs() - startedAt).toFixed(2)),
                status: 'error',
                message: error instanceof Error ? error.message : String(error),
            },
        });
        throw error;
    }
}
