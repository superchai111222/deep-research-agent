export type TaskStatus = "pending" | "in_progress" | "retrying" | "completed" | "incomplete";
export type ReviewDecision = "accept" | "retry" | "stop";

export interface Evidence {
  evidence_id: number;
  title: string;
  url: string;
  content: string;
}

export interface SourceAssessment {
  evidence_id: number;
  relevant: boolean;
  credible: boolean;
  usable: boolean;
  reason: string;
}

export interface CoverageItem {
  aspect: string;
  covered: boolean;
  evidence_ids: number[];
  reason: string;
}

export interface ResearchTask {
  id: number;
  title: string;
  goal: string;
  query: string;
  required_aspects: string[];
  status: TaskStatus;
  attempts: number;
  evidence_count: number;
  evidence: Evidence[];
  summary: string;
  review_decision: ReviewDecision | null;
  review_reason: string;
  source_assessments: SourceAssessment[];
  review_coverage: CoverageItem[];
}

export interface ResearchRequest {
  topic: string;
  search_api?: string;
}

export type ResearchEvent =
  | { type: "research_started"; topic: string }
  | { type: "tasks_planned"; tasks: ResearchTask[] }
  | { type: "task_started" | "task_completed" | "task_incomplete"; task: ResearchTask }
  | { type: "attempt_started"; task_id: number; attempt: number; query: string }
  | { type: "search_completed"; task_id: number; evidence_count: number; evidence: Evidence[] }
  | { type: "summary_completed"; task_id: number; summary: string }
  | { type: "review_completed"; task_id: number; decision: ReviewDecision; reason: string;
      source_assessments: SourceAssessment[]; coverage: CoverageItem[] }
  | { type: "task_retrying"; task_id: number; previous_query: string; next_query: string }
  | { type: "search_failed"; task_id: number; error: string }
  | { type: "research_failed"; reason: string }
  | { type: "report_started" }
  | { type: "report_completed"; report: string }
  | { type: "error"; detail: string }
  | { type: "done" };
