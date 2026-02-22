export type SessionTime = {
  updated?: number;
};

export type Session = {
  id: string;
  title?: string;
  agent?: string;
  time?: SessionTime;
};

export type PartState = {
  status?: string;
};

export type Part = {
  id?: string;
  type?: string;
  text?: string;
  tool?: string;
  state?: PartState;
  session_id?: string;
  message_id?: string;
};

export type Message = {
  id: string;
  role: string;
  info?: Record<string, unknown>;
  parts: Part[];
};

export type ProviderModel = {
  id: string;
  name?: string;
};

export type Provider = {
  id: string;
  name?: string;
  models: ProviderModel[];
};

export type Agent = {
  name: string;
};

export type Permission = {
  id: string;
  session_id?: string;
  permission?: string;
};

export type Question = {
  id: string;
  session_id?: string;
  questions?: Array<{ question?: string }>;
};

export type EventEnvelope = {
  type: string;
  data: Record<string, unknown>;
};

export type LocalPty = {
  id: string;
  title: string;
  buffer?: string;
  cursor?: number;
  rows?: number;
  cols?: number;
};

export type Theme = "system" | "light" | "dark";
