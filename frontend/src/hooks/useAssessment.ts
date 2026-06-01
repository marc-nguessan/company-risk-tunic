import { useCallback, useReducer, useRef } from 'react';
import type {
  AssessmentEvent,
  CompanyQuery,
  CompanyRiskAssessment,
  EntityCandidate,
  ResolvedEntity,
  SourceResult,
} from '../types';
import { ssePost } from '../utils/ssePost';

// ---------------------------------------------------------------------------
// State shape
// ---------------------------------------------------------------------------

export type AssessmentPhase =
  | 'idle'
  | 'resolving'
  | 'fetching'
  | 'needs_disambiguation'
  | 'complete'
  | 'error';

export interface AssessmentState {
  phase: AssessmentPhase;
  resolvedEntity: ResolvedEntity | null;
  candidates: EntityCandidate[];
  sources: Record<string, SourceResult>;
  sourceNames: string[];
  assessment: CompanyRiskAssessment | null;
  error: string | null;
}

const INITIAL: AssessmentState = {
  phase: 'idle',
  resolvedEntity: null,
  candidates: [],
  sources: {},
  sourceNames: [],
  assessment: null,
  error: null,
};

// ---------------------------------------------------------------------------
// Reducer — fold SSE events into state
// ---------------------------------------------------------------------------

type Action =
  | { type: 'RESET' }
  | { type: 'RESOLVING' }
  | { type: 'ENTITY_RESOLVED'; entity: ResolvedEntity }
  | { type: 'SOURCE_PENDING'; name: string }
  | { type: 'SOURCE_RESULT'; result: SourceResult }
  | { type: 'FINAL'; assessment: CompanyRiskAssessment }
  | { type: 'NEEDS_DISAMBIGUATION'; candidates: EntityCandidate[] }
  | { type: 'ERROR'; message: string };

function reducer(state: AssessmentState, action: Action): AssessmentState {
  switch (action.type) {
    case 'RESET':
      return INITIAL;
    case 'RESOLVING':
      return { ...INITIAL, phase: 'resolving' };
    case 'ENTITY_RESOLVED':
      return { ...state, phase: 'fetching', resolvedEntity: action.entity };
    case 'SOURCE_PENDING': {
      const key = action.name;
      const pending: SourceResult = {
        source_name: key,
        status: 'pending',
        latency_ms: 0,
        signals: [],
        raw: null,
        error: null,
      };
      return {
        ...state,
        sourceNames: state.sourceNames.includes(key)
          ? state.sourceNames
          : [...state.sourceNames, key],
        sources: { ...state.sources, [key]: pending },
      };
    }
    case 'SOURCE_RESULT': {
      const key = action.result.source_name;
      return {
        ...state,
        sources: { ...state.sources, [key]: action.result },
        sourceNames: state.sourceNames.includes(key)
          ? state.sourceNames
          : [...state.sourceNames, key],
      };
    }
    case 'FINAL':
      return { ...state, phase: 'complete', assessment: action.assessment };
    case 'NEEDS_DISAMBIGUATION':
      return { ...state, phase: 'needs_disambiguation', candidates: action.candidates };
    case 'ERROR':
      return { ...state, phase: 'error', error: action.message };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAssessment() {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async (query: CompanyQuery) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    dispatch({ type: 'RESOLVING' });

    try {
      const stream = ssePost<AssessmentEvent>('/assess', query, controller.signal);
      for await (const { data } of stream) {
        switch (data.type) {
          case 'entity_resolved':
            dispatch({ type: 'ENTITY_RESOLVED', entity: data.entity });
            break;
          case 'source_result':
            dispatch({ type: 'SOURCE_RESULT', result: data.result });
            break;
          case 'final':
            dispatch({ type: 'FINAL', assessment: data.assessment });
            break;
          case 'needs_disambiguation':
            dispatch({ type: 'NEEDS_DISAMBIGUATION', candidates: data.candidates });
            break;
          case 'error':
            dispatch({ type: 'ERROR', message: data.message });
            break;
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name !== 'AbortError') {
        dispatch({ type: 'ERROR', message: err.message });
      }
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    dispatch({ type: 'RESET' });
  }, []);

  return { state, run, reset };
}
