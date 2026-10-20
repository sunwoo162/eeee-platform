import { z } from "zod";

export const reviewFindingSchema = z.object({
  filePath: z.string().min(1),
  line: z.number().int().positive(),
  severity: z.enum(["critical", "major", "minor"]),
  category: z.enum(["correctness", "security", "performance", "maintainability"]),
  confidence: z.number().min(0).max(1),
  explanation: z.string().min(1).max(1200),
  suggestion: z.string().max(2000).optional(),
});

export const reviewResultSchema = z.object({
  summary: z.array(z.string().min(1).max(300)).max(5),
  findings: z.array(reviewFindingSchema).max(50),
});

export type ReviewFinding = z.infer<typeof reviewFindingSchema>;
export type ReviewResult = z.infer<typeof reviewResultSchema>;
