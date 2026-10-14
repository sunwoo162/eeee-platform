import type { ChatGptWebBrowserAdapter, ChatGptWebResultContract, ChatGptWebSessionProbe, ChatGptBrowserOperationFailureClass } from "./browser-adapter.js";
import {
  ChatGptWebAuthenticationRequiredError,
  ChatGptWebSessionLostError,
  ChatGptWebTemporarilyLimitedError,
  ChatGptWebConversationLimitError,
  ChatGptWebUsageLimitError,
  ChatGptWebStructuredResultError,
} from "./browser-adapter.js";
import type { CompiledWebPrompt } from "./prompt-compiler.js";

export interface ChatGptBrowserDriver {
  openOrResumeConversation(input: { conversationRef?: string; prompt: string; promptSha256: string }): Promise<{ conversationRef?: string }>;
  submitPrompt(input: { conversationRef?: string; prompt: string; promptSha256: string }): Promise<{ conversationRef?: string } | void>;
  readStructuredResult(input: { requestId?: string; conversationRef: string; timeoutMs: number; contract: ChatGptWebResultContract }): Promise<unknown>;
  probeConversation(conversationRef: string): Promise<ChatGptWebSessionProbe>;
  /** Check the owned browser page before any conversation exists. */
  probeBrowser?(): Promise<ChatGptWebSessionProbe>;
  closeConversation(conversationRef: string): Promise<void>;
  recordParserDiagnostic?(input: {
    runId?: string; projectId?: string; stage: string; sessionId: string; generation: number;
    conversationRef?: string; resultContract?: ChatGptWebResultContract; message: string;
    diagnostic?: Record<string, string | boolean>;
    correctionAttempt?: number; correctionBudgetUsed?: number; correctionBudgetLimit?: number;
  }): Promise<void>;
  recordOperationDiagnostic?(input: { runId?: string; projectId?: string; operation: string; phase: "failure"; stage: string; sessionId: string; generation: number; conversationRef?: string; failureClass: string }): Promise<void>;
  dispose?(): Promise<void>;
}

export type { ChatGptBrowserOperationFailureClass } from "./browser-adapter.js";

export function classifyChatGptBrowserOperationFailure(error: unknown): ChatGptBrowserOperationFailureClass {
  const message = error instanceof Error ? error.message : "";
  const name = error instanceof Error ? error.name : "";
  const text = `${name} ${message}`.toLowerCase();
  if (/browser.*disconnect|disconnected.*browser|browser has been closed/.test(text)) return "browser-disconnected";
  if (/execution context.*destroyed|cannot find context/.test(text)) return "execution-context-destroyed";
  if (/target.*closed|target page, context or browser has been closed/.test(text)) return "target-closed";
  if (/page.*closed|page has been closed/.test(text)) return "page-closed";
  if (/context.*closed|context has been closed/.test(text)) return "context-closed";
  if (/owned page.*missing|owned page.*unavailable/.test(text)) return "owned-page-missing";
  if (/conversation identity .*?(?:changed|invalid|unavailable|drifted)|assistant message identity changed|did not assign .*conversation identity|new conversation (?:identity is unavailable|navigation drifted)/.test(text)) return "conversation-identity-changed";
  if (/no pending .*submission|pending .*submission .*available/.test(text)) return "pending-submission-missing";
  if (/structured result .*timed out|response .*timed out/.test(text)) return "response-timeout";
  if (/clipboard|text\/plain|copy.*capture|capture.*clipboard/.test(text)) return "clipboard-capture-failed";
  if (/assistant.*(?:source|turn|response|copy)|(?:assistant|response).*extraction/.test(text)) return "assistant-response-extraction-failed";
  if (/page.*missing|page.*not found/.test(text)) return "page-missing";
  if (/navigation|net::|goto/.test(text)) return "navigation-failed";
  if (/locator|selector|composer/.test(text)) return "locator-missing";
  if (/timeout|timed out/.test(text)) return "timeout";
  if (/session.*not found|no session/.test(text)) return "session-not-found";
  if (/conversation.*not found|conversation.*unavailable/.test(text)) return "conversation-not-found";
  if (/auth|login|sign.?in/.test(text)) return "auth-or-login-page";
  if (/abort|aborted/.test(text)) return "operation-aborted";
  return "unknown";
}

function safeRef(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$/.test(value)) {
    throw new ChatGptWebSessionLostError("Browser returned an unsafe conversation reference");
  }
  return value;
}
function requireRef(value?: string): string {
  if (!value) throw new ChatGptWebSessionLostError("ChatGPT Web conversation reference is unavailable");
  return safeRef(value);
}
function classify(error: unknown): never {
  if (
    error instanceof ChatGptWebAuthenticationRequiredError
    || error instanceof ChatGptWebSessionLostError
    || error instanceof ChatGptWebTemporarilyLimitedError
    || error instanceof ChatGptWebConversationLimitError
    || error instanceof ChatGptWebUsageLimitError
    || error instanceof ChatGptWebStructuredResultError
  ) throw error;
  const message = error instanceof Error ? error.message : "ChatGPT browser operation failed";
  if (/auth|login|sign.?in/i.test(message)) throw new ChatGptWebAuthenticationRequiredError(message);
  throw new ChatGptWebSessionLostError("ChatGPT browser operation failed", classifyChatGptBrowserOperationFailure(error));
}

export function createProductionChatGptWebAdapter(driver: ChatGptBrowserDriver): ChatGptWebBrowserAdapter {
  const recordFailure = async (operation: string, session: any, error: unknown) => {
    const message = error instanceof Error ? error.message : "";
    const failureClass = error instanceof ChatGptWebStructuredResultError ? "structured-result-parser-rejection" : /conversation identity/i.test(message) ? "conversation-identity-failure" : /composer/i.test(message) ? "composer-failure" : /assistant/i.test(message) ? "assistant-response-failure" : /timeout/i.test(message) ? "response-timeout" : classifyChatGptBrowserOperationFailure(error);
    await driver.recordOperationDiagnostic?.({ runId: session.runId, ...(session.projectId ? { projectId: session.projectId } : {}), operation, phase: "failure", stage: session.stage, sessionId: session.sessionId, generation: session.generation, ...(session.conversationRef ? { conversationRef: session.conversationRef } : {}), failureClass }).catch(() => undefined);
  };
  const promptInput = (prompt: CompiledWebPrompt) => ({ prompt: prompt.body, promptSha256: prompt.sha256 });
  return {
    async openOrResumeSession(session, prompt) {
      try {
        const result = await driver.openOrResumeConversation({
          ...(session.conversationRef ? { conversationRef: safeRef(session.conversationRef) } : {}),
          ...promptInput(prompt),
        });
        return result.conversationRef ? { conversationRef: safeRef(result.conversationRef) } : {};
      } catch (error) { await recordFailure(session.conversationRef ? "reacquire-owned-page" : "acquire-owned-page", session, error); return classify(error); }
    },
    async submitTurn(session, prompt) {
      try {
        const result = await driver.submitPrompt({
          ...(session.conversationRef ? { conversationRef: safeRef(session.conversationRef) } : {}),
          ...promptInput(prompt),
        });
        return result?.conversationRef ? { conversationRef: safeRef(result.conversationRef) } : {};
      } catch (error) { await recordFailure("submit-prompt", session, error); return classify(error); }
    },
    async awaitStructuredResult(session, timeoutMs, contract) {
      try { return await driver.readStructuredResult({ requestId: session.sessionId, conversationRef: requireRef(session.conversationRef), timeoutMs, contract }); }
      catch (error) { await recordFailure("extract-structured-result", session, error); if (error instanceof ChatGptWebStructuredResultError) await driver.recordParserDiagnostic?.({ runId: session.runId, ...(session.projectId ? { projectId: session.projectId } : {}), stage: session.stage, sessionId: session.sessionId, generation: session.generation, resultContract: contract, ...(session.conversationRef ? { conversationRef: session.conversationRef } : {}), message: error.message, diagnostic: error.diagnostic }); return classify(error); }
    },
    async probeSession(session) {
      try { return await driver.probeConversation(requireRef(session.conversationRef)); }
      catch (error) { await recordFailure("inspect-page-state", session, error); return classify(error); }
    },
    async closeSession(session) {
      if (!session.conversationRef) return;
      try { await driver.closeConversation(safeRef(session.conversationRef)); }
      catch (error) { classify(error); }
    },
    async recordResultDiagnostic(input) {
      await driver.recordParserDiagnostic?.({
        runId: input.session.runId,
        ...(input.session.projectId ? { projectId: input.session.projectId } : {}),
        stage: input.session.stage,
        sessionId: input.session.sessionId,
        generation: input.session.generation,
        resultContract: input.contract,
        ...(input.session.conversationRef ? { conversationRef: input.session.conversationRef } : {}),
        message: input.message,
        diagnostic: input.diagnostic,
        ...(input.correctionAttempt === undefined ? {} : { correctionAttempt: input.correctionAttempt }),
        ...(input.correctionBudgetUsed === undefined ? {} : { correctionBudgetUsed: input.correctionBudgetUsed }),
        ...(input.correctionBudgetLimit === undefined ? {} : { correctionBudgetLimit: input.correctionBudgetLimit }),
      });
    },
  };
}
