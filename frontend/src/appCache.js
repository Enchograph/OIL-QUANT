export function readAppCache(key) {
    if (typeof window === 'undefined') {
        return null;
    }

    const sources = [window.localStorage, window.sessionStorage];
    for (const storage of sources) {
        try {
            const raw = storage.getItem(key);
            if (!raw) {
                continue;
            }
            return JSON.parse(raw);
        } catch {
            continue;
        }
    }

    return null;
}

export function writeAppCache(key, value) {
    if (typeof window === 'undefined') {
        return;
    }

    try {
        window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
        // 忽略浏览器存储不可用的场景，继续走实时请求。
    }
}
