import type { RiskSignal, SourceResult } from '../types';

// Severity ordering: most serious first.
const SEVERITY_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2, info: 3 };

const SEVERITY_STYLE: Record<string, { color: string; bg: string }> = {
  high:   { color: '#fff', bg: '#dc2626' },
  medium: { color: '#fff', bg: '#d97706' },
  low:    { color: '#fff', bg: '#16a34a' },
  info:   { color: '#fff', bg: '#6b7280' },
};

// Per-status: border colour, background tint, label.
const STATUS_CFG: Record<
  string,
  { border: string; bg: string; label: string; labelColor: string }
> = {
  pending: { border: '#d4d4d8', bg: '#fafafa',  label: 'Fetching…',  labelColor: '#a1a1aa' },
  ok:      { border: '#16a34a', bg: '#f0fdf4',  label: '✓ OK',       labelColor: '#16a34a' },
  partial: { border: '#d97706', bg: '#fffbeb',  label: '~ Partial',  labelColor: '#d97706' },
  error:   { border: '#dc2626', bg: '#fff5f5',  label: '✗ Error',    labelColor: '#dc2626' },
  timeout: { border: '#dc2626', bg: '#fff5f5',  label: '⏱ Timeout', labelColor: '#dc2626' },
};

// Human-readable display names for known source identifiers.
const DISPLAY_NAMES: Record<string, string> = {
  companies_house:        'Companies House',
  director_network:       'Director Network',
  adverse_media:          'Adverse Media',
  stub_companies_info:    'Companies House (stub)',
  stub_director_network:  'Director Network (stub)',
};

interface Props {
  sourceName: string;
  result: SourceResult;
}

export function SourceCard({ sourceName, result }: Props) {
  const cfg = STATUS_CFG[result.status] ?? STATUS_CFG.ok;
  const isPending = result.status === 'pending';

  // Sort signals severity-first so high-severity flags appear at the top.
  const signals = [...result.signals].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9),
  );

  const displayName = DISPLAY_NAMES[sourceName] ?? sourceName.replace(/_/g, ' ');

  return (
    <div
      style={{
        border: `1px solid ${cfg.border}`,
        borderRadius: 6,
        padding: '0.7rem 1rem',
        marginBottom: '0.5rem',
        background: cfg.bg,
        opacity: isPending ? 0.7 : 1,
        transition: 'opacity 0.2s',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong style={{ fontSize: '0.88rem', textTransform: 'capitalize' }}>{displayName}</strong>
        <span style={{ color: cfg.labelColor, fontWeight: 600, fontSize: '0.82rem' }}>
          {isPending && <span className="spinning" style={{ marginRight: '0.3rem' }}>⟳</span>}
          {cfg.label}
        </span>
      </div>

      {/* "OK but no signals" — visually different from error, means the source
          ran cleanly but found nothing adverse. */}
      {result.status === 'ok' && signals.length === 0 && (
        <div style={{ color: '#16a34a', fontSize: '0.8rem', marginTop: '0.3rem' }}>
          No risk signals found.
        </div>
      )}

      {/* Error / timeout message */}
      {result.error && (
        <div style={{ color: cfg.labelColor, fontSize: '0.8rem', marginTop: '0.3rem' }}>
          {result.error}
        </div>
      )}

      {/* Signals — sorted high→low, with code and explanation */}
      {signals.length > 0 && (
        <ul
          style={{
            margin: '0.45rem 0 0',
            padding: 0,
            listStyle: 'none',
            borderTop: '1px solid rgba(0,0,0,0.06)',
          }}
        >
          {signals.map((sig, i) => (
            <SignalRow key={i} signal={sig} />
          ))}
        </ul>
      )}

      {/* Latency — de-emphasised, bottom-right */}
      {!isPending && result.latency_ms > 0 && (
        <div style={{ color: '#c4c4c4', fontSize: '0.72rem', marginTop: '0.4rem', textAlign: 'right' }}>
          {result.latency_ms} ms
        </div>
      )}
    </div>
  );
}

function SignalRow({ signal }: { signal: RiskSignal }) {
  const style = SEVERITY_STYLE[signal.severity] ?? SEVERITY_STYLE.info;

  return (
    <li
      style={{
        display: 'grid',
        gridTemplateColumns: 'max-content max-content 1fr',
        columnGap: '0.45rem',
        alignItems: 'start',
        padding: '0.35rem 0',
        borderTop: '1px solid rgba(0,0,0,0.05)',
        fontSize: '0.81rem',
      }}
    >
      {/* Severity badge */}
      <span
        style={{
          background: style.bg,
          color: style.color,
          borderRadius: 3,
          padding: '0.1rem 0.35rem',
          fontSize: '0.68rem',
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: '0.03em',
          whiteSpace: 'nowrap',
          alignSelf: 'center',
        }}
      >
        {signal.severity}
      </span>

      {/* Signal code */}
      <code
        style={{
          background: 'rgba(0,0,0,0.05)',
          padding: '0.1rem 0.35rem',
          borderRadius: 3,
          fontSize: '0.7rem',
          color: '#444',
          whiteSpace: 'nowrap',
          alignSelf: 'center',
        }}
      >
        {signal.code}
      </code>

      {/* Human-readable explanation */}
      <span style={{ color: '#333', lineHeight: 1.45 }}>{signal.explanation}</span>
    </li>
  );
}
