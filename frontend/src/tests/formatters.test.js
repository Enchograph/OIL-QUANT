import { getNewsPublishedCalendarParts } from '../utils/formatters';

describe('formatters', () => {
    test('getNewsPublishedCalendarParts 使用与前端时间展示一致的本地时区日期', () => {
        const publishedAt = '2026-03-30T23:10:00+00:00';
        const localDate = new Date(publishedAt);

        expect(getNewsPublishedCalendarParts(publishedAt)).toEqual({
            year: localDate.getFullYear(),
            month: localDate.getMonth() + 1,
            day: localDate.getDate(),
        });
    });
});
