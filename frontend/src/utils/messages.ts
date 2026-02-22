import type { Message, Part } from "../types";

export function normalizeMessage(item: Record<string, unknown>): Message {
  const info = (item.info as Record<string, unknown> | undefined) ?? {};
  const id = String(item.id ?? info.id ?? "");
  const role = String(item.role ?? info.role ?? "assistant");
  const parts = Array.isArray(item.parts) ? (item.parts as Part[]) : [];
  return { id, role, info, parts };
}

export function upsertMessage(list: Message[], next: Message): Message[] {
  const idx = list.findIndex((item) => item.id === next.id);
  if (idx < 0) return [...list, next];
  const out = [...list];
  out[idx] = { ...out[idx], ...next, parts: out[idx].parts.length ? out[idx].parts : next.parts };
  return out;
}

export function upsertPart(msg: Message, part: Part): Message {
  const id = String(part.id ?? "");
  if (!id) return { ...msg, parts: [...msg.parts, part] };
  const idx = msg.parts.findIndex((item) => String(item.id ?? "") === id);
  if (idx < 0) return { ...msg, parts: [...msg.parts, part] };
  const out = [...msg.parts];
  out[idx] = { ...out[idx], ...part };
  return { ...msg, parts: out };
}
