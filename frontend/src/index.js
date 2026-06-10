import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { AudiencePreferenceProvider } from './audiencePreference';
import { ThemeProvider } from './theme';
import { TimezoneProvider } from './timezone';

const root = ReactDOM.createRoot(document.getElementById('root'));

root.render(
  <ThemeProvider>
    <TimezoneProvider>
      <AudiencePreferenceProvider>
        <App />
      </AudiencePreferenceProvider>
    </TimezoneProvider>
  </ThemeProvider>,
);
