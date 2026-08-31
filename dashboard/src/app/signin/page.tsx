import { signIn } from "@/auth";

export default function SignInPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-6 sm:p-10">
      <div className="flex w-full max-w-md flex-col gap-6">
        {/* Header */}
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground font-bold shadow-sm">
            A
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Artisan Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Autonomous multi-agent triage, plan-and-execute resolution, and merge conflict monitor.
          </p>
        </div>

        {/* Authentication Card */}
        <div className="flex flex-col gap-4 rounded-xl border bg-card p-6 shadow-sm">
          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-semibold">Sign In</h2>
            <p className="text-xs text-muted-foreground">
              Authenticate via GitHub to access live ticket monitoring and agent audit trails.
            </p>
          </div>

          <form
            action={async () => {
              "use server";
              await signIn("github", { redirectTo: "/tickets" });
            }}
          >
            <button
              type="submit"
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2.5 text-sm font-medium text-background transition hover:opacity-90 active:scale-[0.98]"
            >
              <svg className="size-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                />
              </svg>
              <span>Sign in with GitHub</span>
            </button>
          </form>

          {/* Evaluator Access Notice */}
          <div className="rounded-lg border border-border/60 bg-muted/40 p-3 text-xs text-muted-foreground flex flex-col gap-1.5">
            <span className="font-semibold text-foreground">Hackathon Evaluators & Judges:</span>
            <p>
              Sign in with a GitHub account linked to one of the authorized evaluator emails:
            </p>
            <ul className="list-disc pl-4 font-mono text-[11px] text-foreground space-y-0.5">
              <li>testing@devpost.com</li>
              <li>cloudhackathons@google.com</li>
            </ul>
            <p className="text-[11px]">
              Or sign in with any GitHub account added as a collaborator on the repository.
            </p>
            <p className="text-[11px] border-t border-border/50 pt-1.5 text-foreground/80">
              💡 <span className="font-medium text-foreground">Jira Live Board:</span> Please accept the Jira invitation sent to your email to view the live Kanban board and watch tickets transition across columns in real time.
            </p>
          </div>
        </div>

        {/* Live Demo Instructions Card */}
        <div className="flex flex-col gap-3 rounded-xl border bg-card p-6 shadow-sm text-sm">
          <div className="flex items-center gap-2 font-semibold">
            <span className="text-base">🚀</span>
            <span>How to test the Live Demo</span>
          </div>

          <ol className="flex flex-col gap-2.5 text-xs text-muted-foreground pl-4 list-decimal">
            <li>
              <span className="text-foreground font-medium">Open an issue on GitHub:</span> Visit the public demo repo at{" "}
              <a
                href="https://github.com/403errors/artisan-demo"
                target="_blank"
                rel="noreferrer"
                className="font-mono text-primary underline underline-offset-2 hover:opacity-80"
              >
                403errors/artisan-demo
              </a>{" "}
              and open a feature or bug issue.
            </li>
            <li>
              <span className="text-foreground font-medium">Autonomous Agent Processing:</span> Artisan automatically triages your issue (clarifying if ambiguous), plans changes, writes code and tests in a Cloud Run sandbox, and creates a real Pull Request.
            </li>
            <li>
              <span className="text-foreground font-medium">Track Live on Dashboard & Jira:</span> Sign in above to inspect the real-time agent execution feed, synchronized Jira tickets (<code className="font-mono">ART-*</code>), PR links, and Cloud Trace telemetry. Accept the Jira invitation to see tickets move on the live board!
            </li>
          </ol>
        </div>
      </div>
    </div>
  );
}
