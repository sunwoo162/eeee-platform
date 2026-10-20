import type { ReviewFinding, ReviewResult } from "./review-types.js";

const LABEL = { critical: "🔴 Critical", major: "🟠 Major", minor: "🟡 Minor" } as const;

export function renderReviewBody(result: ReviewResult): string {
  const lines = ["## 🤖 이설 Code Review", ""];
  if (result.summary.length === 0 && result.findings.length === 0) {
    lines.push("변경된 코드에서 바로 수정이 필요한 문제를 찾지 못했습니다.");
    return lines.join("\n");
  }
  for (const summary of result.summary.slice(0, 5)) lines.push(`- ${summary}`);
  if (result.findings.length > 0) lines.push("", `인라인 코멘트 ${result.findings.length}개를 남겼습니다.`);
  return lines.join("\n");
}

export function renderInlineComment(finding: ReviewFinding): string {
  const lines = [`**${LABEL[finding.severity]} · ${finding.category}**`, "", finding.explanation.trim()];
  if (finding.suggestion?.trim()) lines.push("", "```suggestion", finding.suggestion.trim(), "```");
  return lines.join("\n");
}
