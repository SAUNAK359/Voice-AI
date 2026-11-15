import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './styles.css';
import '@xyflow/react/dist/style.css';

const query = new QueryClient({
  defaultOptions: {queries: {retry: 1, refetchOnWindowFocus: true}}
});
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={query}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
