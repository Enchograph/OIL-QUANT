export function normalizeAiAnalysisView(payload, view) {
    const viewPayload =
        payload?.views?.[view] ??
        (view === 'enterprise' || view === 'corporate'
            ? payload?.enterprise ?? payload?.corporate ?? payload?.company ?? payload?.enterpriseView
            : payload?.bank ?? payload?.banking ?? payload?.bankView) ?? null;

    if (!viewPayload) {
        return null;
    }

    const summary =
        viewPayload.body ??
        viewPayload.summary ??
        viewPayload.overview ??
        viewPayload.analysis ??
        viewPayload.insight ??
        viewPayload.content ??
        '';
    const highlights =
        viewPayload.highlights ??
        viewPayload.keyPoints ??
        viewPayload.keyMessages ??
        viewPayload.recommendations ??
        viewPayload.actions ??
        [];

    return {
        title: viewPayload.title ?? viewPayload.headline ?? '',
        summary: typeof summary === 'string' ? summary : '',
        highlights: Array.isArray(highlights)
            ? highlights.map((item) => (typeof item === 'string' ? item : item?.text ?? item?.content ?? '')).filter(Boolean)
            : [],
    };
}
