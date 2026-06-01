import { RiskSummary } from './components/RiskSummary';
import { SearchBar } from './components/SearchBar';
import { SourceCard } from './components/SourceCard';
import { useAssessment } from './hooks/useAssessment';
import type { CompanyQuery } from './types';

export default function App() {
  const { state, run, reset } = useAssessment();

  function handleSubmit(query: CompanyQuery) {
    reset();
    void run(query);
  }

  const busy = state.phase === 'resolving' || state.phase === 'fetching';
  const sourcesComplete = state.sourceNames.filter(
    (n) => state.sources[n]?.status !== 'pending',
  ).length;
  const sourcesTotal = state.sourceNames.length;

  return (
    <div style={{ maxWidth: 720, margin: '2rem auto', padding: '0 1rem', fontFamily: 'sans-serif' }}>
      <h1 style={{ marginBottom: '1.5rem' }}>Company Risk Assessment</h1>

      <SearchBar onSubmit={handleSubmit} disabled={busy} />

      {state.phase !== 'idle' && (
        <div style={{ marginTop: '1.5rem' }}>
          {/* Progress */}
          {state.phase === 'resolving' && (
            <p style={{ color: '#888' }}>Resolving entity…</p>
          )}

          {state.resolvedEntity && state.phase !== 'resolving' && (
            <div style={{ marginBottom: '0.75rem', fontSize: '0.9rem', color: '#555' }}>
              Entity: <strong>{state.resolvedEntity.name}</strong> (
              {state.resolvedEntity.registration_number})
            </div>
          )}

          {sourcesTotal > 0 && state.phase !== 'complete' && (
            <p style={{ color: '#888', fontSize: '0.9rem', marginBottom: '0.75rem' }}>
              {sourcesComplete} of {sourcesTotal} sources complete
            </p>
          )}

          {/* Final summary */}
          {state.assessment && <RiskSummary assessment={state.assessment} />}

          {/* Source cards */}
          {state.sourceNames.map((name) => (
            <SourceCard key={name} sourceName={name} result={state.sources[name]} />
          ))}

          {/* Error */}
          {state.phase === 'error' && (
            <p style={{ color: '#c33' }}>Error: {state.error}</p>
          )}
        </div>
      )}
    </div>
  );
}
