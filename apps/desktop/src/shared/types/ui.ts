export type AppPage = "chat" | "history" | "memory" | "reminders" | "settings" | "permissions";

export type ConversationSummary = {
  id: string;
  title: string;
  updated_at: string;
  run_ids: string[];
  app_icons: string[];
};

export type Message = {
  id: string;
  chat_id: string;
  role: "user" | "astra";
  text: string;
  ts: string;
  run_id?: string;
  delivery_state?: "queued" | "sending" | "delivered" | "failed";
  error_detail?: string | null;
  typing?: boolean;
};

export type ActivityStepStatus = "pending" | "active" | "done" | "error";

export type OverlayBehavior = "mini" | "corner" | "hide";
export type OverlayCorner = "top-right" | "top-left" | "bottom-right" | "bottom-left";

export type ActivityStep = {
  id: string;
  title: string;
  status: ActivityStepStatus;
};

export type OverlayStep = {
  id: string;
  title: string;
  status: ActivityStepStatus;
  children?: OverlayStep[];
};

export type OverlayState = {
  statusLabel: string;
  lastUserMessage: string;
  lastAstraSnippet: string[];
  stepsTree: OverlayStep[];
  hasApprovalPending: boolean;
  updatedAt: string;
};

export type NotificationSeverity = "info" | "success" | "warning" | "error";

export type NotificationItem = {
  id: string;
  ts: string;
  title: string;
  body?: string;
  severity?: NotificationSeverity;
};

export type Activity = {
  run_id: string;
  phase: "planning" | "executing" | "review" | "waiting" | "error";
  steps: ActivityStep[];
  details?: string[];
};

export type MemoryItem = {
  id: string;
  title: string;
  detail: string;
  tags: string[];
  updated_at: string;
};

export type Reminder = {
  id: string;
  title: string;
  due_at: string;
  note?: string;
};

export type UIState = {
  sidebarWidth: number;
  activityWidth: number;
  activityOpen: boolean;
  lastSelectedPage: AppPage;
  lastSelectedChatId: string | null;
  density: "low" | "medium" | "high";
  grainEnabled: boolean;
  activityDetailed: boolean;
  defaultActivityOpen: boolean;
};
