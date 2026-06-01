// TypeScript mirror of backend/app/models.py — keep in sync with Pydantic models.

export interface CompanyQuery {
  company_name?: string;
  registration_number?: string;
  jurisdiction?: string;
}

export interface EntityCandidate {
  registration_number: string;
  name: string;
  status: string;
  match_confidence: number;
  address: string | null;
}

export interface ResolvedEntity extends EntityCandidate {}

export type Severity = 'info' | 'low' | 'medium' | 'high';
export type SourceStatus = 'pending' | 'ok' | 'partial' | 'error' | 'timeout';
export type RiskBand = 'low' | 'medium' | 'high';

export interface RiskSignal {
  code: string;
  severity: Severity;
  score_contribution: number;
  explanation: string;
  source: string;
  evidence: Record<string, unknown> | null;
}

export interface SourceResult {
  source_name: string;
  status: SourceStatus;
  latency_ms: number;
  signals: RiskSignal[];
  raw: Record<string, unknown> | null;
  error: string | null;
}

export interface CompanyRiskAssessment {
  query: CompanyQuery;
  resolved_entity: ResolvedEntity | null;
  candidates: EntityCandidate[];
  overall_risk_score: number;
  risk_band: RiskBand;
  sources: SourceResult[];
  completeness: number;
  confidence: number;
  generated_at: string;
  prompt_version: string;
}

// SSE event payloads
export interface EntityResolvedEvent {
  type: 'entity_resolved';
  entity: ResolvedEntity;
}

export interface SourceResultEvent {
  type: 'source_result';
  result: SourceResult;
}

export interface FinalEvent {
  type: 'final';
  assessment: CompanyRiskAssessment;
}

export interface NeedsDisambiguationEvent {
  type: 'needs_disambiguation';
  candidates: EntityCandidate[];
}

export interface ErrorEvent {
  type: 'error';
  message: string;
}

export type AssessmentEvent =
  | EntityResolvedEvent
  | SourceResultEvent
  | FinalEvent
  | NeedsDisambiguationEvent
  | ErrorEvent;
