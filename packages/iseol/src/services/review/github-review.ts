import { Octokit } from "@octokit/rest";
import { aggregateCiFindings } from "./ci-review-aggregate.js";
import type { CiReviewArtifact } from "./ci-review-types.js";
import { parseGitHubRepository } from "../github.js";
import { changedLinesFromPatch, filterReviewFindings } from "./review-filter.js";
import { renderInlineComment, renderReviewBody } from "./review-render.js";
import { ReviewStateStore } from "./review-state.js";
import type { ReviewProvider } from "./gemini-review-provider.js";
import type { ReviewResult } from "./review-types.js";

export type PullFile = { filename: string; patch?: string | null };

export function isReviewablePath(path: string): boolean {
  const normalized = path.replace(/\\/g, "/").toLowerCase();
  if (normalized.endsWith("package-lock.json") || normalized.endsWith("pnpm-lock.yaml") || normalized.endsWith("yarn.lock")) return false;
  if (normalized.includes("/node_modules/") || normalized.startsWith("node_modules/")) return false;
  if (normalized.includes("/dist/") || normalized.startsWith("dist/")) return false;
  if (normalized.includes("/build/") || normalized.startsWith("build/")) return false;
  if (normalized.endsWith(".min.js") || normalized.endsWith(".map")) return false;
  return true;
}

export function buildReviewContext(files: PullFile[], maxChars = 50_000): string {
  const chunks: string[] = [];
  let size = 0;
  for (const file of files) {
    if (!isReviewablePath(file.filename) || !file.patch) continue;
    const chunk = `FILE: ${file.filename}\n${file.patch}`;
    if (size + chunk.length > maxChars) break;
    chunks.push(chunk);
    size += chunk.length;
  }
  return chunks.join("\n\n");
}

export function parseReviewRepository(repository: string): { owner: string; repo: string } {
  const parsed = parseGitHubRepository(repository);
  return { owner: parsed.owner, repo: parsed.repo };
}

export class GitHubReviewService {
  private readonly octokit: Octokit;

  constructor(
    token: string,
    private readonly provider?: ReviewProvider,
    private readonly state = new ReviewStateStore(),
  ) {
    this.octokit = new Octokit({ auth: token });
  }

  private parseRepository(repository: string): { owner: string; repo: string } {
    return parseReviewRepository(repository);
  }

  private async listReviewableFiles(owner: string, repo: string, pullNumber: number): Promise<PullFile[]> {
    const files = await this.octokit.paginate(this.octokit.rest.pulls.listFiles, {
      owner,
      repo,
      pull_number: pullNumber,
      per_page: 100,
    });
    return files.filter((file) => isReviewablePath(file.filename));
  }

  private changedLines(files: PullFile[]): Set<string> {
    const changedLines = new Set<string>();
    for (const file of files) {
      for (const key of changedLinesFromPatch(file.filename, file.patch)) changedLines.add(key);
    }
    return changedLines;
  }

  private async postReview(
    owner: string,
    repo: string,
    repository: string,
    pullNumber: number,
    headSha: string,
    result: ReviewResult,
  ): Promise<{ skipped: boolean; findings: number }> {
    const comments = result.findings.map((finding) => ({
      path: finding.filePath,
      line: finding.line,
      side: "RIGHT" as const,
      body: renderInlineComment(finding),
    }));
    await this.octokit.rest.pulls.createReview({
      owner,
      repo,
      pull_number: pullNumber,
      commit_id: headSha,
      body: renderReviewBody(result),
      event: "COMMENT",
      comments,
    });
    await this.state.markReviewed(repository, pullNumber, headSha);
    return { skipped: false, findings: comments.length };
  }

  async reviewCiArtifact(
    repository: string,
    pullNumber: number,
    headSha: string,
    artifact: CiReviewArtifact,
  ): Promise<{ skipped: boolean; findings: number }> {
    const { owner, repo } = this.parseRepository(repository);
    const canonicalRepository = `${owner}/${repo}`;
    return this.state.withReviewLock(canonicalRepository, pullNumber, headSha, async () => {
      if (await this.state.hasReviewed(canonicalRepository, pullNumber, headSha)) return { skipped: true, findings: 0 };
      const files = await this.listReviewableFiles(owner, repo, pullNumber);
      const normalized = aggregateCiFindings(artifact, this.changedLines(files));
      return this.postReview(owner, repo, canonicalRepository, pullNumber, headSha, normalized);
    });
  }

  async reviewPullRequest(repository: string, pullNumber: number, headSha: string): Promise<{ skipped: boolean; findings: number }> {
    const { owner, repo } = this.parseRepository(repository);
    const canonicalRepository = `${owner}/${repo}`;
    return this.state.withReviewLock(canonicalRepository, pullNumber, headSha, async () => {
      if (await this.state.hasReviewed(canonicalRepository, pullNumber, headSha)) return { skipped: true, findings: 0 };
      if (!this.provider) throw new Error("AI ReviewProvider가 설정되지 않았습니다.");

      const reviewable = await this.listReviewableFiles(owner, repo, pullNumber);
      const context = buildReviewContext(reviewable);
      if (!context.trim()) {
        return this.postReview(owner, repo, canonicalRepository, pullNumber, headSha, { summary: [], findings: [] });
      }

      const normalized = filterReviewFindings(await this.provider.review(context), this.changedLines(reviewable));
      return this.postReview(owner, repo, canonicalRepository, pullNumber, headSha, normalized);
    });
  }
}
