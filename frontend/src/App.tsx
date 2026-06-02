import { DisambiguationList } from './components/DisambiguationList';
import { RiskSummary } from './components/RiskSummary';
import { SearchBar } from './components/SearchBar';
import { SourceCard } from './components/SourceCard';
import { useAssessment } from './hooks/useAssessment';
import type { CompanyQuery, EntityCandidate } from './types';

export default function App() {
  const { state, run, reset } = useAssessment();

  function handleSubmit(query: CompanyQuery) {
    reset();
    void run(query);
  }

  // Disambiguation: user picks a candidate → re-submit by registration number
  // (the unambiguous path that bypasses search entirely).
  function handleDisambiguate(candidate: EntityCandidate) {
    void run({ registration_number: candidate.registration_number });
  }

  const busy = state.phase === 'resolving' || state.phase === 'fetching';
  const sourcesTotal = state.sourceNames.length;
  const sourcesComplete = state.sourceNames.filter(
    (n) => state.sources[n]?.status !== 'pending',
  ).length;

  // The orchestrator emits an error event with this exact message when search
  // returns nothing. Distinguish it from a real runtime error.
  const isNoMatch =
    state.phase === 'error' && state.error === 'No matching company found.';

  return (
    <div
      style={{
        maxWidth: 740,
        margin: '2rem auto',
        padding: '0 1rem 4rem',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}
    >
      {/* Header */}
      <h1 style={{ margin: '0 0 0.25rem', fontSize: '1.35rem', fontWeight: 700 }}>
        Company Risk Assessment
      </h1>
      <p style={{ margin: '0 0 1.5rem', color: '#888', fontSize: '0.88rem' }}>
        Enter a company name or Companies House registration number.
      </p>

      <SearchBar onSubmit={handleSubmit} disabled={busy} />

      {state.phase !== 'idle' && (
        <div style={{ marginTop: '1.5rem' }}>

          {/* ── Resolving spinner ───────────────────────────────────── */}
          {state.phase === 'resolving' && (
            <div style={{ color: '#666', fontSize: '0.88rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span className="spinning">⟳</span> Searching for company…
            </div>
          )}

          {/* ── Disambiguation — multiple matches ───────────────────── */}
          {state.phase === 'needs_disambiguation' && (
            <DisambiguationList
              candidates={state.candidates}
              onSelect={handleDisambiguate}
            />
          )}

          {/* ── No match ─────────────────────────────────────────────── */}
          {isNoMatch && (
            <div
              style={{
                padding: '1rem',
                background: '#f5f5f5',
                border: '1px solid #ddd',
                borderRadius: 6,
                color: '#555',
              }}
            >
              <strong>No company found.</strong>
              <p style={{ margin: '0.4rem 0 0', fontSize: '0.88rem' }}>
                No companies matched your query. Try a registration number directly
                (e.g. <code>14999001</code> or <code>SC987654</code>).
              </p>
            </div>
          )}

          {/* ── Runtime error ─────────────────────────────────────────── */}
          {state.phase === 'error' && !isNoMatch && (
            <div
              style={{
                padding: '0.75rem 1rem',
                background: '#fff5f5',
                border: '1px solid #fca5a5',
                borderRadius: 6,
                color: '#dc2626',
                fontSize: '0.88rem',
              }}
            >
              <strong>Error:</strong> {state.error}
            </div>
          )}

          {/* ── Resolved entity banner (while fetching or complete) ──── */}
          {state.resolvedEntity &&
            (state.phase === 'fetching' || state.phase === 'complete') && (
              <div
                style={{
                  padding: '0.45rem 0.75rem',
                  background: '#eff6ff',
                  border: '1px solid #bfdbfe',
                  borderRadius: 5,
                  fontSize: '0.85rem',
                  color: '#1e40af',
                  marginBottom: '0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                }}
              >
                <span style={{ fontWeight: 600 }}>{state.resolvedEntity.name}</span>
                <code style={{ fontSize: '0.8rem', color: '#6b7280' }}>
                  {state.resolvedEntity.registration_number}
                </code>
              </div>
            )}

          {/* ── Progress while fetching ───────────────────────────────── */}
          {state.phase === 'fetching' && sourcesTotal > 0 && (
            <div
              style={{
                fontSize: '0.83rem',
                color: '#888',
                marginBottom: '0.6rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
              }}
            >
              <span className="spinning" style={{ fontSize: '0.75rem' }}>⟳</span>
              {sourcesComplete} of {sourcesTotal} sources complete
            </div>
          )}

          {/* ── Final assessment (above cards, so bottom-line is first) ─ */}
          {state.assessment && <RiskSummary assessment={state.assessment} />}

          {/* ── Source cards — show as they stream in ─────────────────── */}
          {state.sourceNames.map((name) => (
            <SourceCard key={name} sourceName={name} result={state.sources[name]} />
          ))}

        </div>
      )}
    </div>
  );
}
