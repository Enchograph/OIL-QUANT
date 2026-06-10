describe('api helpers', () => {
    beforeEach(() => {
        jest.resetModules();
        global.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ ok: true }),
        });
    });

    afterEach(() => {
        delete process.env.REACT_APP_API_BASE_URL;
        jest.resetAllMocks();
    });

    test('apiGet 默认使用当前站点的 /api/v1 前缀', async () => {
        delete process.env.REACT_APP_API_BASE_URL;

        const { apiGet } = require('../api');

        await apiGet('/prediction/latest', { range: '1M' });

        expect(global.fetch).toHaveBeenCalledWith(
            `${window.location.origin}/api/v1/prediction/latest?range=1M`,
        );
    });

    test('apiGet 支持通过相对路径环境变量覆盖 API 前缀', async () => {
        process.env.REACT_APP_API_BASE_URL = '/custom-api';

        const { apiGet } = require('../api');

        await apiGet('/prediction/latest', { range: '1M' });

        expect(global.fetch).toHaveBeenCalledWith(
            `${window.location.origin}/custom-api/prediction/latest?range=1M`,
        );
    });
});
