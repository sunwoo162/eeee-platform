import { createHmac, timingSafeEqual } from "node:crypto";

export function verifyGitHubSignature(secret: string, body: Buffer, signature?: string | null): boolean {
  if (!secret || !signature?.startsWith("sha256=")) return false;
  const expected = Buffer.from(`sha256=${createHmac("sha256", secret).update(body).digest("hex")}`);
  const actual = Buffer.from(signature);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

export function shouldReviewPullRequestAction(action: string): boolean {
  return action === "opened" || action === "reopened" || action === "synchronize";
}
