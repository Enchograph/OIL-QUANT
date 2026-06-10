import { readAppCache, writeAppCache } from '../appCache';

describe('appCache', () => {
    afterEach(() => {
        window.localStorage.clear();
        window.sessionStorage.clear();
    });

    test('优先从 localStorage 读取缓存数据', () => {
        window.localStorage.setItem('ticker', JSON.stringify({ source: 'local' }));
        window.sessionStorage.setItem('ticker', JSON.stringify({ source: 'session' }));

        expect(readAppCache('ticker')).toEqual({ source: 'local' });
    });

    test('当 localStorage 不存在时兼容旧的 sessionStorage 缓存', () => {
        window.sessionStorage.setItem('ticker', JSON.stringify({ source: 'session' }));

        expect(readAppCache('ticker')).toEqual({ source: 'session' });
    });

    test('写入时持久化到 localStorage', () => {
        writeAppCache('ticker', { source: 'local' });

        expect(JSON.parse(window.localStorage.getItem('ticker'))).toEqual({ source: 'local' });
    });
});
