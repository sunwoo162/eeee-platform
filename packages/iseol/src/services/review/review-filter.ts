import type { ReviewFinding, ReviewResult } from "./review-types.js";

export function changedLinesFromPatch(filePath: string, patch?: string | null): Set<string> {
  const changed = new Set<string>();
  if (!patch) return changed;
  let newLine = 0;
  for (const line of patch.split("\n")) {
    const header = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (header) {
      newLine = Number(header[1]);
      continue;
    }
    if (!newLine || line.startsWith("\\ No newline")) continue;
    if (line.startsWith("-")) continue;
    if (line.startsWith("+")) changed.add(`${filePath}:${newLine}`);
    newLine += 1;
  }
  return changed;
}

function findingKey(finding: ReviewFinding): string {
  return `${finding.filePath}:${finding.line}:${finding.category}:${finding.explanation.trim().toLowerCase()}`;
}

export function filterReviewFindings(result: ReviewResult, changedLines: Set<string>): ReviewResult {
  const seen = new Set<string>();
  const valid = result.findings
    .filter((finding) => finding.confidence >= 0.8)
    .filter((finding) => changedLines.has(`${finding.filePath}:${finding.line}`))
    .filter((finding) => {
      const key = findingKey(finding);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => {
      const rank = { critical: 0, major: 1, minor: 2 } as const;
      return rank[a.severity] - rank[b.severity] || b.confidence - a.confidence;
    });
  const critical = valid.filter((finding) => finding.severity === "critical");
  const findings = critical.length > 5 ? critical : valid.slice(0, 5);
  return { summary: result.summary.slice(0, 5), findings };
}
