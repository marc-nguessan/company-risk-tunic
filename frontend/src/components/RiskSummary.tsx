import type { CompanyRiskAssessment } from '../types';

const BAND_STYLE: Record<string, { badge: string; border: string }> = {
  low:    { badge: '#16a34a', border: '#16a34a' },
  medium: { badge: '#d97706', border: '#d97706' },
  high:   { badge: '#dc2626', border: '#dc2626' },
};

interface Props {
  assessment: CompanyRiskAssessment;
}

export function RiskSummary({ assessment }: Props) {
  const band = BAND_STYLE[assessment.risk_band] ?? BAND_STYLE.high;

  // Compute source health counts directly from the sources list — this lets
  // us show "X of Y sources healthy" rather than just a bare percentage.
  const total     = assessment.sources.length;
  const okCount   = assessment.sources.filter((s) => s.status === 'ok').length;
  const failCount = assessment.sources.filter(
    (s) => s.status === 'error' || s.status === 'timeout',
  ).length;

  // Confidence expressed as a fraction string ("2 / 3") so the analyst can
  // immediately see which sources contributed. The percentage is a secondary label.
  const confidencePct = Math.round(assessment.confidence * 100);
  const confidenceLabel =
    total > 0 ? `${okCount} of ${total} sources healthy` : `${confidencePct}%`;

  return (
    <div
      style={{
        border: `2px solid ${band.border}`,
        borderRadius: 8,
        background: '#fff',
        marginBottom: '1rem',
        overflow: 'hidden',
      }}
    >
      {/* ── Risk section ─────────────────────────────────────────────── */}
      <div style={{ padding: '1rem 1.25rem 0.75rem' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            marginBottom: '0.5rem',
          }}
        >
          {/* Band badge */}
          <span
            style={{
              background: band.badge,
              color: '#fff',
              borderRadius: 4,
              padding: '0.25rem 0.75rem',
              fontWeight: 700,
              fontSize: '0.85rem',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              flexShrink: 0,
            }}
          >
            {assessment.risk_band} risk
          </span>

          {/* Score */}
          <span
            style={{
              fontSize: '2rem',
              fontWeight: 800,
              lineHeight: 1,
              color: band.badge,
            }}
          >
            {assessment.overall_risk_score.toFixed(1)}
          </span>
          <span style={{ color: '#aaa', fontSize: '0.9rem', alignSelf: 'flex-end', paddingBottom: '0.2rem' }}>
            / 100
          </span>
        </div>

        {/* Resolved entity */}
        {assessment.resolved_entity && (
          <div style={{ fontSize: '0.84rem', color: '#555' }}>
            <strong>{assessment.resolved_entity.name}</strong>
            {' · '}
            <code style={{ fontSize: '0.8rem' }}>
              {assessment.resolved_entity.registration_number}
            </code>
            {' · '}
            <span style={{ textTransform: 'capitalize' }}>
              {assessment.resolved_entity.status}
            </span>
          </div>
        )}
      </div>

      {/* ── Confidence section — visually separated from risk ────────── */}
      {/* This section uses a neutral palette deliberately — confidence is
          data quality, not risk level. A grey bar makes it read as metadata,
          not as an additional risk signal. */}
      <div
        style={{
          borderTop: `1px solid ${band.border}22`,
          background: '#f8f8f8',
          padding: '0.65rem 1.25rem',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '1rem',
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontSize: '0.82rem', color: '#555' }}>
            <span style={{ fontWeight: 600, color: '#333' }}>Data confidence: </span>
            {confidenceLabel}
            <span style={{ color: '#aaa', marginLeft: '0.3rem' }}>({confidencePct}%)</span>
          </span>

          <span style={{ fontSize: '0.82rem', color: '#555' }}>
            <span style={{ fontWeight: 600, color: '#333' }}>Completeness: </span>
            {Math.round(assessment.completeness * 100)}%
          </span>

          {/* Warning pill when sources failed */}
          {failCount > 0 && (
            <span
              style={{
                fontSize: '0.75rem',
                padding: '0.15rem 0.5rem',
                background: '#fff7ed',
                border: '1px solid #fed7aa',
                borderRadius: 3,
                color: '#c2410c',
              }}
            >
              {failCount} source{failCount > 1 ? 's' : ''} failed
            </span>
          )}
        </div>

        {/* Inline note — only when confidence is degraded */}
        {assessment.confidence < 1 && (
          <p
            style={{
              margin: '0.35rem 0 0',
              fontSize: '0.78rem',
              color: '#888',
              fontStyle: 'italic',
            }}
          >
            Confidence reflects source coverage, not risk level. A low-confidence result
            means less data was gathered — not that the risk is necessarily lower.
          </p>
        )}
      </div>

      {/* ── Final-state banner ────────────────────────────────────────── */}
      <div
        style={{
          background: '#f0fdf4',
          borderTop: '1px solid #bbf7d0',
          padding: '0.5rem 1.25rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.4rem',
          color: '#15803d',
          fontWeight: 700,
          fontSize: '0.88rem',
        }}
      >
        ✓ Assessment complete
      </div>
    </div>
  );
}
