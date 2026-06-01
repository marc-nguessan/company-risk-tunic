import type { CompanyRiskAssessment } from '../types';

interface Props {
  assessment: CompanyRiskAssessment;
}

const BAND_COLORS = { low: '#2a7', medium: '#b80', high: '#c33' };

export function RiskSummary({ assessment }: Props) {
  const bandColor = BAND_COLORS[assessment.risk_band];

  return (
    <div
      style={{
        border: `2px solid ${bandColor}`,
        borderRadius: 8,
        padding: '1rem 1.25rem',
        marginBottom: '1rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.5rem' }}>
        <span
          style={{
            background: bandColor,
            color: '#fff',
            borderRadius: 4,
            padding: '0.2rem 0.75rem',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}
        >
          {assessment.risk_band} risk
        </span>
        <span style={{ fontSize: '1.5rem', fontWeight: 700 }}>
          {assessment.overall_risk_score.toFixed(1)} / 100
        </span>
      </div>

      <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.9rem', color: '#555' }}>
        <span>
          Confidence: <strong>{pct(assessment.confidence)}</strong>
        </span>
        <span>
          Completeness: <strong>{pct(assessment.completeness)}</strong>
        </span>
      </div>

      {assessment.resolved_entity && (
        <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: '#333' }}>
          <strong>{assessment.resolved_entity.name}</strong>
          {' — '}
          {assessment.resolved_entity.registration_number}
          {' — '}
          {assessment.resolved_entity.status}
        </div>
      )}

      <div style={{ marginTop: '0.75rem', color: '#2a7', fontWeight: 600 }}>
        ✓ Assessment complete
      </div>
    </div>
  );
}

function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}
