export const ANSWER_LANGUAGES = {
  en: "English",
  hi: "Hindi",
  sa: "Sanskrit",
  es: "Spanish",
  ta: "Tamil",
  te: "Telugu",
  ml: "Malayalam",
  bn: "Bengali",
  fr: "French",
  it: "Italian",
  gu: "Gujarati",
  kn: "Kannada",
  zh: "Chinese (Simplified)",
  pt: "Portuguese",
  ja: "Japanese",
} as const;

export type AnswerLanguage = keyof typeof ANSWER_LANGUAGES;

export function isAnswerLanguage(value: unknown): value is AnswerLanguage {
  return typeof value === "string" && Object.hasOwn(ANSWER_LANGUAGES, value);
}

export function loadAnswerLanguage(userId: string): AnswerLanguage {
  if (typeof window === "undefined") return "en";
  try {
    const value = window.localStorage.getItem(`bookrag.answer-language.${userId}`);
    return isAnswerLanguage(value) ? value : "en";
  } catch {
    return "en";
  }
}

export function saveAnswerLanguage(userId: string, language: AnswerLanguage): void {
  try {
    window.localStorage.setItem(`bookrag.answer-language.${userId}`, language);
  } catch {
    // A disabled browser store should not prevent asking a question.
  }
}

export function loadQuestionLanguage(userId: string): AnswerLanguage {
  if (typeof window === "undefined") return "en";
  try {
    const value = window.localStorage.getItem(`bookrag.question-language.${userId}`);
    return isAnswerLanguage(value) ? value : "en";
  } catch {
    return "en";
  }
}

export function saveQuestionLanguage(userId: string, language: AnswerLanguage): void {
  try {
    window.localStorage.setItem(`bookrag.question-language.${userId}`, language);
  } catch {
    // A disabled browser store should not prevent asking a question.
  }
}
