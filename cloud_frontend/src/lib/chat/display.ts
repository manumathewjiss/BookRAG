const COMMON = new Set([
  "about", "after", "again", "also", "answer", "best", "book", "could", "does", "from",
  "have", "here", "into", "most", "only", "page", "passage", "question", "said", "says",
  "some", "that", "their", "there", "these", "this", "those", "what", "when", "where",
  "which", "with", "would", "your",
]);

function terms(text: string): Set<string> {
  return new Set((text.toLowerCase().match(/[\p{L}\p{N}]{4,}/gu) || []).filter((word) => !COMMON.has(word)));
}

/** A display-only preview. The original passage remains available for inspection. */
export function evidencePreview(passage: string, question: string, answer: string): string | null {
  const words = passage.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  const sought = new Set([...terms(question), ...terms(answer)]);
  if (!sought.size) return null;
  const windowSize = 52;
  let bestStart = 0;
  let bestScore = 0;
  for (let start = 0; start < words.length; start += 1) {
    const found = new Set<string>();
    for (const word of words.slice(start, start + windowSize)) {
      const normalized = word.toLowerCase().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
      if (sought.has(normalized)) found.add(normalized);
    }
    if (found.size > bestScore) {
      bestScore = found.size;
      bestStart = start;
    }
  }
  if (bestScore < 2) return null;
  const preview = words.slice(bestStart, bestStart + windowSize).join(" ");
  return `${bestStart ? "…" : ""}${preview}${bestStart + windowSize < words.length ? "…" : ""}`;
}

/** Clean model formatting for display without changing saved answers or cited passages. */
export function displayAnswerText(text: string): string {
  return text
    .replace(/\*\*([^*\n]+)\*\*/g, "$1")
    .replace(/(^|[^\w*])\*([^*\n]+)\*(?=$|[^\w*])/g, "$1$2")
    .replace(/^(\s*)\*\s+/gm, "$1• ")
    .replace(/\s*—\s*/g, ", ");
}
