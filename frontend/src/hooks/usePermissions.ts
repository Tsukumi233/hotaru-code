import { useState } from "react";
import type { Permission, Question } from "../types";
import * as api from "../api";

export function usePermissions() {
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);

  async function loadPending(sessionId?: string): Promise<void> {
    const [perms, asks] = await Promise.all([api.permissions.list(), api.questions.list()]);
    if (!sessionId) {
      setPermissions(perms);
      setQuestions(asks);
      return;
    }
    setPermissions(perms.filter((item) => String(item.session_id ?? "") === sessionId));
    setQuestions(asks.filter((item) => String(item.session_id ?? "") === sessionId));
  }

  async function replyPermission(id: string, reply: string, sessionId?: string): Promise<void> {
    await api.permissions.reply(id, reply);
    await loadPending(sessionId);
  }

  async function replyQuestion(id: string, answers: string[][], sessionId?: string): Promise<void> {
    await api.questions.reply(id, answers);
    await loadPending(sessionId);
  }

  async function rejectQuestion(id: string, sessionId?: string): Promise<void> {
    await api.questions.reject(id);
    await loadPending(sessionId);
  }

  return { permissions, questions, loadPending, replyPermission, replyQuestion, rejectQuestion };
}
