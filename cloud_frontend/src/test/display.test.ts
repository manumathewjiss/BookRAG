import { describe, expect, it } from "vitest";
import { answerParts, evidencePreview } from "@/lib/chat/display";

describe("answer and evidence display", () => {
  it("renders bold markers without showing literal asterisks", () => {
    expect(answerParts("**Northern Arizona** is first; **Boise State** is strongest for NLP.")).toEqual([
      { text: "Northern Arizona", bold: true },
      { text: " is first; ", bold: false },
      { text: "Boise State", bold: true },
      { text: " is strongest for NLP.", bold: false },
    ]);
  });

  it("selects a short matching window from a long cited passage", () => {
    const irrelevant = "Background notes about application dates and fees. ".repeat(35);
    const passage = `${irrelevant} Northern Arizona ranks first for practical application priority. Boise State is the strongest western NLP candidate. ${irrelevant}`;
    const preview = evidencePreview(passage, "What is the best university?", "Northern Arizona ranks first; Boise State is strongest for NLP.");
    expect(preview).toContain("Northern Arizona ranks first");
    expect(preview).toContain("Boise State");
    expect(preview!.length).toBeLessThan(passage.length / 2);
  });

  it("does not present an unrelated short passage as proof", () => {
    expect(evidencePreview("Chapter contents and publishing details.", "What is the best university?", "Northern Arizona is first.")).toBeNull();
  });
});
