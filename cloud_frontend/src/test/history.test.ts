import { beforeEach, describe, expect, it } from "vitest";
import { clearHistory, loadHistory, saveHistory, type ChatTurn } from "@/lib/chat/history";

describe("chat history", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("round-trips turns per user and document", () => {
    const turn: ChatTurn = {
      id: "t1",
      question: "What is a high-level language?",
      createdAt: "2026-10-24T00:00:00Z",
      status: "ok",
    };
    saveHistory("user-a", "doc-a", [turn]);
    expect(loadHistory("user-a", "doc-a")).toEqual([turn]);
    expect(loadHistory("user-b", "doc-a")).toEqual([]);
    clearHistory("user-a", "doc-a");
    expect(loadHistory("user-a", "doc-a")).toEqual([]);
  });
});
