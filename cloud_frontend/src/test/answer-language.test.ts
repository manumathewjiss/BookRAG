import { beforeEach, describe, expect, it } from "vitest";
import { loadAnswerLanguage, saveAnswerLanguage } from "@/lib/chat/answer-language";

describe("answer language preference", () => {
  beforeEach(() => window.localStorage.clear());

  it("persists per user and defaults to English", () => {
    expect(loadAnswerLanguage("person-a")).toBe("en");
    saveAnswerLanguage("person-a", "es");
    expect(loadAnswerLanguage("person-a")).toBe("es");
    expect(loadAnswerLanguage("person-b")).toBe("en");
  });

  it("ignores an unsupported stored language", () => {
    window.localStorage.setItem("bookrag.answer-language.person-a", "fr");
    expect(loadAnswerLanguage("person-a")).toBe("en");
  });
});
