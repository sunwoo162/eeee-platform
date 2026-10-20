import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { createHash } from "node:crypto";

import { withDurableFileStateLock } from "../file-state-lock.js";

type ReviewState = { repository: string; pullNumber: number; headSha: string; reviewedAt: string };

export class ReviewStateStore {
  constructor(private readonly file = resolve(process.cwd(), "data", "review-state.json")) {}

  async withReviewLock<T>(repository: string, pullNumber: number, headSha: string, task: () => Promise<T>): Promise<T> {
    const identity = `${repository.toLowerCase()}:${pullNumber}:${headSha}`;
    const digest = createHash("sha256").update(identity).digest("hex");
    return withDurableFileStateLock(`${this.file}.review-${digest}`, task, { waitForMs: 60_000, pollIntervalMs: 25 });
  }

  private async read(): Promise<ReviewState[]> {
    try { return JSON.parse(await readFile(this.file, "utf8")) as ReviewState[]; }
    catch { return []; }
  }

  private async write(items: ReviewState[]): Promise<void> {
    await mkdir(dirname(this.file), { recursive: true });
    const temp = `${this.file}.tmp`;
    await writeFile(temp, JSON.stringify(items, null, 2), "utf8");
    await rename(temp, this.file);
  }

  async hasReviewed(repository: string, pullNumber: number, headSha: string): Promise<boolean> {
    const repo = repository.toLowerCase();
    return withDurableFileStateLock(this.file, async () => (await this.read()).some((item) => item.repository.toLowerCase() === repo && item.pullNumber === pullNumber && item.headSha === headSha), { waitForMs: 2_000 });
  }

  async markReviewed(repository: string, pullNumber: number, headSha: string): Promise<void> {
    await withDurableFileStateLock(this.file, async () => {
      const items = await this.read();
      if (items.some((item) => item.repository.toLowerCase() === repository.toLowerCase() && item.pullNumber === pullNumber && item.headSha === headSha)) return;
      items.push({ repository, pullNumber, headSha, reviewedAt: new Date().toISOString() });
      await this.write(items);
    }, { waitForMs: 2_000 });
  }
}
