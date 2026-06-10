import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';

export const AUDIENCE_PREFERENCE_STORAGE_KEY = 'citi-oil-platform-ai-audience';

export const AUDIENCE_PREFERENCES = {
    ENTERPRISE: 'enterprise',
    BANK: 'bank',
};

const audienceLabels = {
    [AUDIENCE_PREFERENCES.ENTERPRISE]: '企业侧',
    [AUDIENCE_PREFERENCES.BANK]: '银行侧',
};

const AudiencePreferenceContext = createContext(null);

function getStoredAudiencePreference() {
    if (typeof window === 'undefined') {
        return AUDIENCE_PREFERENCES.ENTERPRISE;
    }

    const storedPreference = window.localStorage.getItem(AUDIENCE_PREFERENCE_STORAGE_KEY);
    return storedPreference === AUDIENCE_PREFERENCES.BANK ? AUDIENCE_PREFERENCES.BANK : AUDIENCE_PREFERENCES.ENTERPRISE;
}

export function AudiencePreferenceProvider({ children }) {
    const [audiencePreference, setAudiencePreference] = useState(getStoredAudiencePreference);

    useEffect(() => {
        if (typeof window === 'undefined') {
            return;
        }

        window.localStorage.setItem(AUDIENCE_PREFERENCE_STORAGE_KEY, audiencePreference);
    }, [audiencePreference]);

    const value = useMemo(
        () => ({
            audiencePreference,
            audiencePreferenceLabel: audienceLabels[audiencePreference],
            setAudiencePreference,
        }),
        [audiencePreference],
    );

    return <AudiencePreferenceContext.Provider value={value}>{children}</AudiencePreferenceContext.Provider>;
}

export function useAudiencePreference() {
    const context = useContext(AudiencePreferenceContext);

    if (!context) {
        throw new Error('useAudiencePreference must be used within AudiencePreferenceProvider');
    }

    return context;
}
