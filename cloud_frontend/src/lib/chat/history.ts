import type { Answer } from "@/lib/api/types";

export interface ChatTurn {
  id: string;
  question: string;
  createdAt: string;
  status: "pending" | "ok" | "error";
  answer?: Answer;
  error?: string;
}

function key(userId: string, documentId: string): string {
  return `bookrag.chat.${userId}.${documentId}`;
}

export function loadHistory(userId: string, documentId: string): ChatTurn[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key(userId, documentId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatTurn[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveHistory(userId: string, documentId: string, turns: ChatTurn[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key(userId, documentId), JSON.stringify(turns));
}

export function clearHistory(userId: string, documentId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(key(userId, documentId));
}
