import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ErrorBoundary, RootErrorFallback } from './shared/ErrorBoundary'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary fallback={error => <RootErrorFallback error={error} />}>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
