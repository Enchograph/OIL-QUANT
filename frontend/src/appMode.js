export function resolveAppEntryMode(pathname = '/') {
    const normalized = String(pathname || '/').trim() || '/';
    return normalized === '/admin' || normalized.startsWith('/admin/') ? 'admin' : 'main';
}
