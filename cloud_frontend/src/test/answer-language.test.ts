import { beforeEach, describe, expect, it } from "vitest";
import { isAnswerLanguage, loadAnswerLanguage, saveAnswerLanguage } from "@/lib/chat/answer-language";

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

  it.each(["ta", "te", "ml", "bn"] as const)("accepts and remembers %s", (language) => {
    expect(isAnswerLanguage(language)).toBe(true);
    saveAnswerLanguage("person-a", language);
    expect(loadAnswerLanguage("person-a")).toBe(language);
  });
});
