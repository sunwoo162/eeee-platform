import { GoogleGenAI } from "@google/genai";
import { reviewResultSchema, type ReviewResult } from "./review-types.js";

const REVIEW_JSON_SCHEMA = {
  type: "object",
  properties: {
    summary: { type: "array", items: { type: "string" }, maxItems: 5 },
    findings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          filePath: { type: "string" },
          line: { type: "integer" },
          severity: { type: "string", enum: ["critical", "major", "minor"] },
          category: { type: "string", enum: ["correctness", "security", "performance", "maintainability"] },
          confidence: { type: "number" },
          explanation: { type: "string" },
          suggestion: { type: "string" },
        },
        required: ["filePath", "line", "severity", "category", "confidence", "explanation"],
      },
    },
  },
  required: ["summary", "findings"],
} as const;

export interface ReviewProvider {
  review(context: string): Promise<ReviewResult>;
}

export class GeminiReviewProvider implements ReviewProvider {
  private readonly ai: GoogleGenAI;

  constructor(apiKey: string, private readonly model = "gemini-3.7-flash") {
    if (!apiKey) throw new Error("GEMINI_API_KEY 환경변수가 필요합니다.");
    this.ai = new GoogleGenAI({ apiKey });
  }

  async review(context: string): Promise<ReviewResult> {
    const prompt = [
      "당신은 시니어 코드 리뷰어입니다.",
      "변경된 diff만 검토하고 실제로 수정할 가치가 높은 문제만 지적하세요.",
      "추측성 코멘트, 취향 문제, 이미 diff 밖에 존재하던 문제는 제외하세요.",
      "confidence는 0~1이며 확신이 높을 때만 0.8 이상을 사용하세요.",
      "summary는 최대 5개의 짧은 한국어 문장으로 작성하세요.",
      "findings의 line은 반드시 추가/변경된 새 파일의 라인 번호여야 합니다.",
      "\n--- PR DIFF ---\n",
      context,
    ].join("\n");

    const response = await this.ai.models.generateContent({
      model: this.model,
      contents: prompt,
      config: {
        responseMimeType: "application/json",
        responseSchema: REVIEW_JSON_SCHEMA as any,
      },
    });
    const text = response.text ?? "";
    if (!text.trim()) throw new Error("Gemini가 빈 리뷰 응답을 반환했습니다.");
    return reviewResultSchema.parse(JSON.parse(text));
  }
}
