import type { SourceResult } from '../types';

const STATUS_LABELS: Record<string, string> = {
  pending: '⏳ Pending',
  ok: '✓ OK',
  partial: '~ Partial',
  error: '✗ Error',
  timeout: '⏱ Timeout',
};

const STATUS_COLORS: Record<string, string> = {
  pending: '#888',
  ok: '#2a7',
  partial: '#b80',
  error: '#c33',
  timeout: '#c33',
};

interface Props {
  sourceName: string;
  result: SourceResult;
}

export function SourceCard({ sourceName, result }: Props) {
  const color = STATUS_COLORS[result.status] ?? '#888';

  return (
    <div
      style={{
        border: `1px solid ${color}`,
        borderRadius: 6,
        padding: '0.75rem 1rem',
        marginBottom: '0.5rem',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong style={{ textTransform: 'capitalize' }}>{sourceName.replace(/_/g, ' ')}</strong>
        <span style={{ color, fontWeight: 600, fontSize: '0.9rem' }}>
          {STATUS_LABELS[result.status] ?? result.status}
        </span>
      </div>

      {result.status === 'pending' && (
        <div style={{ color: '#888', fontSize: '0.85rem', marginTop: '0.25rem' }}>
          Fetching…
        </div>
      )}

      {result.error && (
        <div style={{ color: '#c33', fontSize: '0.85rem', marginTop: '0.25rem' }}>
          {result.error}
        </div>
      )}

      {result.signals.length > 0 && (
        <ul style={{ margin: '0.5rem 0 0', padding: '0 0 0 1.25rem', fontSize: '0.85rem' }}>
          {result.signals.map((sig, i) => (
            <li key={i} style={{ marginBottom: '0.2rem' }}>
              <span
                style={{
                  background: severityColor(sig.severity),
                  color: '#fff',
                  borderRadius: 3,
                  padding: '0 4px',
                  marginRight: 6,
                  fontSize: '0.75rem',
                  textTransform: 'uppercase',
                }}
              >
                {sig.severity}
              </span>
              {sig.explanation}
            </li>
          ))}
        </ul>
      )}

      {result.status !== 'pending' && result.latency_ms > 0 && (
        <div style={{ color: '#888', fontSize: '0.75rem', marginTop: '0.25rem' }}>
          {result.latency_ms}ms
        </div>
      )}
    </div>
  );
}

function severityColor(sev: string): string {
  return { info: '#888', low: '#2a7', medium: '#b80', high: '#c33' }[sev] ?? '#888';
}
