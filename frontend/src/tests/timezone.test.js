import { formatNewsPublishedTime, getNewsPublishedCalendarParts } from '../utils/formatters';

describe('timezone formatting', () => {
    test('formatNewsPublishedTime 按指定 IANA 时区输出并带时区缩写', () => {
        expect(formatNewsPublishedTime('2026-03-30T23:10:00+00:00', '', 'America/New_York')).toBe('2026/03/30 19:10 EDT');
    });

    test('getNewsPublishedCalendarParts 按指定 IANA 时区拆出年月日', () => {
        expect(getNewsPublishedCalendarParts('2026-03-30T23:10:00+00:00', '', 'Asia/Shanghai')).toEqual({
            year: 2026,
            month: 3,
            day: 31,
        });
    });
});
