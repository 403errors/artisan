import { afterEach, describe, expect, it, vi } from "vitest";

// config.ts reads env at module scope, so every case resets the module registry and re-imports
// with an explicit env. The helper clears all config keys first so tests are deterministic even
// when a developer/CI env happens to set some of them.
const CONFIG_ENV_KEYS = [
  "ARTISAN_TARGET_REPO",
  "ARTISAN_PUBSUB_TOPIC",
  "GCP_PROJECT_ID",
  "GOOGLE_CLOUD_PROJECT",
  "NEXT_PUBLIC_JIRA_SITE",
  "NEXT_PUBLIC_GCP_PROJECT_ID",
] as const;

type ConfigEnv = Partial<Record<(typeof CONFIG_ENV_KEYS)[number], string>>;

async function loadConfig(env: ConfigEnv = {}) {
  vi.resetModules();
  for (const key of CONFIG_ENV_KEYS) delete process.env[key];
  for (const [key, value] of Object.entries(env)) process.env[key] = value;
  return import("@/lib/config");
}

afterEach(() => {
  for (const key of CONFIG_ENV_KEYS) delete process.env[key];
  vi.resetModules();
});

describe("dashboard config", () => {
  it("falls back to the v1 defaults when no env is set", async () => {
    const config = await loadConfig();
    expect(config.TARGET_REPO).toBe("403errors/artisan-demo");
    expect(config.PUBSUB_TOPIC).toBe("artisan-github-events");
    expect(config.GCP_PROJECT_ID).toBe("artisan-multiagent-ai");
    expect(config.JIRA_SITE).toBe("pieisnot22by7.atlassian.net");
    expect(config.CLIENT_GCP_PROJECT_ID).toBe("artisan-multiagent-ai");
  });

  it("honors server-runtime env overrides", async () => {
    const config = await loadConfig({
      ARTISAN_TARGET_REPO: "acme/widgets",
      ARTISAN_PUBSUB_TOPIC: "acme-events",
      GCP_PROJECT_ID: "acme-gcp-project",
    });
    expect(config.TARGET_REPO).toBe("acme/widgets");
    expect(config.PUBSUB_TOPIC).toBe("acme-events");
    expect(config.GCP_PROJECT_ID).toBe("acme-gcp-project");
  });

  it("prefers GCP_PROJECT_ID over GOOGLE_CLOUD_PROJECT for the server project id", async () => {
    const config = await loadConfig({
      GCP_PROJECT_ID: "explicit-project",
      GOOGLE_CLOUD_PROJECT: "fallback-project",
    });
    expect(config.GCP_PROJECT_ID).toBe("explicit-project");
  });

  it("falls back to GOOGLE_CLOUD_PROJECT for the server project id", async () => {
    const config = await loadConfig({ GOOGLE_CLOUD_PROJECT: "fallback-project" });
    expect(config.GCP_PROJECT_ID).toBe("fallback-project");
  });

  it("honors client-visible NEXT_PUBLIC_ overrides in the URL helpers", async () => {
    const config = await loadConfig({
      NEXT_PUBLIC_JIRA_SITE: "acme.atlassian.net",
      NEXT_PUBLIC_GCP_PROJECT_ID: "acme-gcp-project",
    });
    expect(config.jiraTicketUrl("ABC-1")).toBe("https://acme.atlassian.net/browse/ABC-1");
    expect(config.cloudTraceUrl("trace-123")).toBe(
      "https://console.cloud.google.com/traces/list?project=acme-gcp-project&tid=trace-123",
    );
  });

  it("falls the client project id back to the server project id when NEXT_PUBLIC is unset", async () => {
    const config = await loadConfig({ GCP_PROJECT_ID: "server-project" });
    expect(config.CLIENT_GCP_PROJECT_ID).toBe("server-project");
  });

  it("keeps githubIssueUrl per-ticket (repo comes from the ticket, not config)", async () => {
    const config = await loadConfig({ ARTISAN_TARGET_REPO: "acme/widgets" });
    expect(config.githubIssueUrl("acme/widgets", 42)).toBe(
      "https://github.com/acme/widgets/issues/42",
    );
  });
});
