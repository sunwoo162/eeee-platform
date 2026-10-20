import { isAbsolute, relative, resolve, sep } from "node:path";

type EnvLike = Record<string, string | undefined>;

const LOOPBACK_CDP_PROTOCOLS = new Set(["http:", "https:", "ws:", "wss:"]);
const LOOPBACK_CDP_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

export type PlaywrightBrowserRoots = {
  repositoryRoot: string;
  modelRoot: string;
  runRoot: string;
  webRoot: string;
  chatGptWebRoot?: string;
};

export type PlaywrightBrowserDriverConfig =
  | { enabled: false }
  | {
      enabled: true;
      profileRoot: string;
      executablePath?: string;
      headless: boolean;
      cdpUrl?: string;
      lifecycleRoot?: string;
    };

function strictBoolean(value: string | undefined, defaultValue: boolean, label: string): boolean {
  const normalized = value?.trim().toLowerCase() ?? "";
  if (!normalized) return defaultValue;
  if (normalized === "true") return true;
  if (normalized === "false") return false;
  throw new Error(`${label} must be true or false`);
}
function comparable(path: string): string {
  const absolute = resolve(path);
  return process.platform === "win32" ? absolute.toLowerCase() : absolute;
}

function isInsideOrEqual(root: string, target: string): boolean {
  const rootPath = comparable(root);
  const targetPath = comparable(target);
  const relation = relative(rootPath, targetPath);
  return relation === "" || (relation !== ".." && !relation.startsWith(`..${sep}`) && !isAbsolute(relation));
}

function assertSafeProfileRoot(profileRoot: string, roots: PlaywrightBrowserRoots): void {
  for (const [label, root] of Object.entries(roots)) {
    if (!root) continue;
    if (isInsideOrEqual(root, profileRoot)) {
      throw new Error(`ISEOL_CHATGPT_BROWSER_PROFILE_ROOT must be outside ${label}`);
    }
  }
}

export function assertLoopbackCdpUrl(value: string): void {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("ISEOL_CHATGPT_BROWSER_CDP_URL must be a valid loopback CDP URL");
  }
  const host = parsed.hostname.toLowerCase();
  if (!LOOPBACK_CDP_PROTOCOLS.has(parsed.protocol) || !LOOPBACK_CDP_HOSTS.has(host)) {
    throw new Error("ISEOL_CHATGPT_BROWSER_CDP_URL must use a loopback endpoint");
  }
}

export function resolvePlaywrightBrowserDriverConfig(
  env: EnvLike,
  roots: PlaywrightBrowserRoots,
): PlaywrightBrowserDriverConfig {
  const enabled = strictBoolean(env.ISEOL_CHATGPT_BROWSER_ENABLED, false, "ISEOL_CHATGPT_BROWSER_ENABLED");
  if (!enabled) return { enabled: false };

  const profileText = env.ISEOL_CHATGPT_BROWSER_PROFILE_ROOT?.trim() ?? "";
  if (!profileText) throw new Error("ISEOL_CHATGPT_BROWSER_PROFILE_ROOT is required when browser driver is enabled");
  const profileRoot = resolve(profileText);
  assertSafeProfileRoot(profileRoot, roots);
  const executablePath = env.ISEOL_CHATGPT_BROWSER_EXECUTABLE?.trim() || undefined;
  const headless = strictBoolean(env.ISEOL_CHATGPT_BROWSER_HEADLESS, false, "ISEOL_CHATGPT_BROWSER_HEADLESS");
  const cdpUrl = env.ISEOL_CHATGPT_BROWSER_CDP_URL?.trim() || undefined;
  if (cdpUrl) assertLoopbackCdpUrl(cdpUrl);
  return { enabled: true, profileRoot, ...(executablePath ? { executablePath } : {}), headless, ...(cdpUrl ? { cdpUrl } : {}), ...(roots.chatGptWebRoot ? { lifecycleRoot: roots.chatGptWebRoot } : {}) };
}
