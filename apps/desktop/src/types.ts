export type ProjectSettings = {
  llm?: {
    provider?: string;
    base_url?: string;
    model?: string;
  };
  autopilot?: {
    loop_delay_ms?: number;
    max_actions?: number;
    max_cycles?: number;
    screenshot_width?: number;
    quality?: number;
  };
  [key: string]: unknown;
};

export type Project = {
  id: string;
  name: string;
  tags: string[];
  settings: ProjectSettings;
  created_at?: string;
  updated_at?: string;
};

export type Run = {
  id: string;
  project_id: string;
  query_text: string;
  mode: string;
  status: string;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  parent_run_id?: string | null;
  purpose?: string | null;
  meta?: Record<string, unknown>;
};

export type ActHint = {
  target: "COMPUTER" | "TEXT_ONLY";
  danger_flags: string[];
  suggested_run_mode: string;
};

export type IntentDecision = {
  intent: "CHAT" | "ACT" | "ASK_CLARIFY";
  confidence: number;
  reasons: string[];
  questions?: string[];
  act_hint?: ActHint | null;
};

export type RunIntentResponse = {
  kind: "act" | "chat" | "clarify";
  intent: IntentDecision;
  run?: Run | null;
  questions?: string[];
  chat_response?: string | null;
  plan?: PlanStep[];
};

export type PlanStep = {
  id: string;
  run_id?: string;
  step_index?: number;
  title: string;
  kind?: string;
  status?: string;
  skill_name?: string;
  inputs?: Record<string, unknown>;
  success_criteria?: string;
  success_checks?: Record<string, unknown>[];
  danger_flags?: string[];
  requires_approval?: boolean;
  artifacts_expected?: string[];
  depends_on?: string[];
};

export type Approval = {
  id: string;
  run_id?: string;
  task_id?: string;
  step_id?: string | null;
  scope?: string;
  approval_type?: string | null;
  created_at?: string;
  status: string;
  title: string;
  description?: string | null;
  proposed_actions?: Record<string, unknown>[];
  preview?: Record<string, unknown> | null;
  decided_at?: string | null;
  resolved_at?: string | null;
  decided_by?: string | null;
  decision?: Record<string, unknown> | null;
};

export type Task = {
  id: string;
  run_id?: string;
  plan_step_id?: string;
  attempt?: number;
  status?: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  duration_ms?: number | null;
};

export type EventItem = {
  id: string;
  run_id?: string;
  seq?: number;
  ts?: number;
  type: string;
  message: string;
  payload?: Record<string, unknown>;
  level?: string;
  task_id?: string | null;
  step_id?: string | null;
};

export type AutopilotStatePayload = {
  goal: string;
  plan: string[];
  step_summary: string;
  reason?: string;
  actions: Record<string, unknown>[];
  status: string;
  phase?: string;
  cycle: number;
  max_cycles: number;
  screen_hash?: string;
  action_hash?: string;
  needs_user?: boolean;
  ask_confirm?: {
    required?: boolean;
    reason?: string;
    proposed_effect?: string;
    [key: string]: unknown;
  };
};

export type AutopilotActionPayload = {
  action: Record<string, unknown>;
  index: number;
  total: number;
  step_summary?: string;
};

// UI-level представление событий (после агрегации, чтобы не спамить одинаковыми строками).
export type HudEventLine = {
  key: string;
  type: string;
  message: string;
  ts?: number;
  count: number;
  payload?: Record<string, unknown>;
};

export type AutopilotActionEvent = {
  seq?: number;
  ts?: number;
  payload: AutopilotActionPayload;
};

export type SnapshotMetrics = {
  coverage?: { done: number; total: number };
  conflicts?: number;
  freshness?: { min: string; max: string; count: number } | null;
};

export type Snapshot = {
  run: Run;
  plan: PlanStep[];
  approvals: Approval[];
  last_events: EventItem[];
  tasks?: Task[];
  sources?: Record<string, unknown>[];
  facts?: Record<string, unknown>[];
  conflicts?: Record<string, unknown>[];
  artifacts?: Record<string, unknown>[];
  metrics?: SnapshotMetrics;
};

export type StatusResponse = {
  status: string;
};

export type MemorySearchResult = {
  type: string;
  item: Record<string, unknown>;
};

export type UserMemory = {
  id: string;
  created_at?: string;
  updated_at?: string;
  title: string;
  content: string;
  tags?: string[];
  source?: string;
  is_deleted?: boolean;
  pinned?: boolean;
  last_used_at?: string | null;
};

export type Reminder = {
  id: string;
  created_at?: string;
  due_at: string;
  text: string;
  status: string;
  delivery: string;
  last_error?: string | null;
  run_id?: string | null;
  source?: string | null;
  sent_at?: string | null;
  updated_at?: string | null;
  attempts?: number;
};
