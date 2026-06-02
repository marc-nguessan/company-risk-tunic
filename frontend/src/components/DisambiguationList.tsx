import type { EntityCandidate } from '../types';

// Status badge colours — same palette as SourceCard / RiskSummary.
const STATUS_STYLES: Record<string, { color: string; bg: string }> = {
  active:                { color: '#1a7a3c', bg: '#e6f4ec' },
  registered:            { color: '#1a7a3c', bg: '#e6f4ec' },
  dissolved:             { color: '#b91c1c', bg: '#fee2e2' },
  liquidation:           { color: '#b91c1c', bg: '#fee2e2' },
  administration:        { color: '#92400e', bg: '#fef3c7' },
  receivership:          { color: '#92400e', bg: '#fef3c7' },
  'voluntary-arrangement': { color: '#92400e', bg: '#fef3c7' },
};
const DEFAULT_STATUS = { color: '#555', bg: '#f0f0f0' };

interface Props {
  candidates: EntityCandidate[];
  onSelect: (candidate: EntityCandidate) => void;
}

export function DisambiguationList({ candidates, onSelect }: Props) {
  return (
    <div>
      <div
        style={{
          padding: '0.65rem 1rem',
          background: '#fffbeb',
          border: '1px solid #f59e0b',
          borderRadius: 6,
          marginBottom: '0.75rem',
          fontSize: '0.9rem',
          color: '#78350f',
        }}
      >
        <strong>Multiple companies matched.</strong> Select the one you mean to assess:
      </div>

      {candidates.map((c) => {
        const pill = STATUS_STYLES[c.status] ?? DEFAULT_STATUS;
        return (
          <CandidateRow key={c.registration_number} candidate={c} pill={pill} onSelect={onSelect} />
        );
      })}
    </div>
  );
}

// Extracted so hover state is self-contained per row.
function CandidateRow({
  candidate: c,
  pill,
  onSelect,
}: {
  candidate: EntityCandidate;
  pill: { color: string; bg: string };
  onSelect: (c: EntityCandidate) => void;
}) {
  return (
    <button
      onClick={() => onSelect(c)}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        background: '#fff',
        border: '1px solid #e0e0e0',
        borderRadius: 6,
        padding: '0.75rem 1rem',
        marginBottom: '0.5rem',
        cursor: 'pointer',
        // hover handled via onMouseEnter/Leave — no CSS class needed
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = '#3b82f6';
        e.currentTarget.style.background = '#eff6ff';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = '#e0e0e0';
        e.currentTarget.style.background = '#fff';
      }}
    >
      {/* Name + registration + status */}
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: '0.6rem',
          flexWrap: 'wrap',
          marginBottom: c.address ? '0.25rem' : 0,
        }}
      >
        <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>{c.name}</span>
        <code
          style={{
            fontSize: '0.8rem',
            color: '#555',
            background: '#f5f5f5',
            padding: '0.1rem 0.35rem',
            borderRadius: 3,
          }}
        >
          {c.registration_number}
        </code>
        <span
          style={{
            fontSize: '0.72rem',
            padding: '0.1rem 0.45rem',
            borderRadius: 3,
            background: pill.bg,
            color: pill.color,
            fontWeight: 600,
            textTransform: 'capitalize',
          }}
        >
          {c.status}
        </span>
      </div>

      {/* Address */}
      {c.address && (
        <div style={{ color: '#888', fontSize: '0.82rem' }}>{c.address}</div>
      )}
    </button>
  );
}
