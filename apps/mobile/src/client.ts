export type MobilePairing = {
  deviceId: string;
  deviceName: string;
  accessToken: string;
};

export type MobileEvent = {
  cursor: number;
  kind: string;
  payload: Record<string, unknown>;
  createdAt: string;
};

export type MobileEventBatch = {
  cursor: number;
  events: MobileEvent[];
};

export type AssistantRouteOptions = {
  conversationId?: string;
  requestId?: string;
  approved?: boolean;
  approvalRequestId?: string;
};

export type MobileConversationSummary = {
  conversationId: string;
  messageCount: number;
  preview: string;
  updatedAt: string;
};

export type MobileConversationTranscript = {
  conversationId: string;
  messageCount: number;
  turns: Array<Record<string, unknown>>;
  nextBeforeId: number | null;
};

export type TokenStore = {
  get(): string | null;
  set(token: string): void;
  clear(): void;
};

export class MemoryTokenStore implements TokenStore {
  private token: string | null = null;

  get(): string | null { return this.token; }
  set(token: string): void { this.token = token; }
  clear(): void { this.token = null; }
}

export class GleaveMobileClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string, private readonly tokens: TokenStore = new MemoryTokenStore()) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    if (!this.baseUrl) throw new Error("Desktop URL is required");
  }

  async pair(pairingCode: string, deviceName: string): Promise<MobilePairing> {
    const pairing = await this.request<MobilePairing>("/api/mobile/pair", {
      method: "POST",
      body: JSON.stringify({ pairingCode, deviceName }),
    }, false);
    this.tokens.set(pairing.accessToken);
    return pairing;
  }

  async state(projectId?: string): Promise<Record<string, unknown>> {
    const query = projectId ? `?projectId=${encodeURIComponent(projectId)}` : "";
    return this.request<Record<string, unknown>>(`/api/mobile/state${query}`);
  }

  async assistantRoute(
    text: string,
    workspace?: string,
    options: AssistantRouteOptions = {},
  ): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("/api/mobile/assistant/route", {
      method: "POST",
      body: JSON.stringify({
        text,
        ...(workspace ? { workspace } : {}),
        ...(options.conversationId ? { conversationId: options.conversationId } : {}),
        ...(options.requestId ? { requestId: options.requestId } : {}),
        ...(options.approved !== undefined ? { approved: options.approved } : {}),
        ...(options.approvalRequestId ? { approvalRequestId: options.approvalRequestId } : {}),
      }),
    });
  }

  async conversations(query?: string, limit = 50): Promise<MobileConversationSummary[]> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (query) params.set("query", query);
    return this.request<MobileConversationSummary[]>(
      `/api/mobile/assistant/conversations?${params.toString()}`,
    );
  }

  async conversation(
    conversationId: string,
    limit = 100,
    beforeId?: number,
  ): Promise<MobileConversationTranscript> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (beforeId !== undefined) params.set("beforeId", String(beforeId));
    return this.request<MobileConversationTranscript>(
      `/api/mobile/assistant/conversations/${encodeURIComponent(conversationId)}/messages?${params.toString()}`,
    );
  }

  async events(cursor = 0): Promise<MobileEventBatch> {
    return this.request<MobileEventBatch>(`/api/mobile/events?cursor=${cursor}`);
  }

  async streamEvents(
    cursor: number,
    onEvent: (event: MobileEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/mobile/events/stream?cursor=${cursor}`, {
      headers: this.headers(),
      signal,
    });
    if (!response.ok) throw new Error(`Desktop event stream failed (${response.status})`);
    if (!response.body) throw new Error("Desktop event stream has no body");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const data = frame.split("\n").find((line) => line.startsWith("data: "));
        if (!data) continue;
        onEvent(JSON.parse(data.slice(6)) as MobileEvent);
      }
    }
  }

  disconnect(): void { this.tokens.clear(); }

  private headers(): Record<string, string> {
    const token = this.tokens.get();
    if (!token) throw new Error("Mobile client is not paired with Desktop");
    return { "content-type": "application/json", "X-Gleave-Bridge-Token": token };
  }

  private async request<T>(path: string, init: RequestInit = {}, authorized = true): Promise<T> {
    const headers = authorized ? this.headers() : { "content-type": "application/json" };
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers: { ...headers, ...init.headers } });
    const body = await response.text();
    let payload: unknown = {};
    try { payload = body ? JSON.parse(body) : {}; } catch { /* handled below */ }
    if (!response.ok) {
      const detail = typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail?: unknown }).detail ?? response.statusText)
        : response.statusText;
      throw new Error(`Desktop request failed (${response.status}): ${detail}`);
    }
    return payload as T;
  }
}
