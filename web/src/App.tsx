// App shell: role switcher plus four views.
//
// The role switcher is the demo's most important control. Everything else in this
// UI is the same code for every actor; what changes is the scope the API resolves,
// so switching from a customer to a manager and re-asking the same question is the
// clearest possible demonstration that authorisation sits below the model.

import { useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import type { Actor } from "./api/types";
import { Spinner } from "./components/Bits";
import Approvals from "./pages/Approvals";
import Audit from "./pages/Audit";
import Chat from "./pages/Chat";
import Dashboard from "./pages/Dashboard";

type View = "chat" | "approvals" | "dashboard" | "audit";

const VIEWS: { id: View; label: string; hint: string; internalOnly: boolean }[] = [
  { id: "chat", label: "Conversation", hint: "Ask as this actor", internalOnly: false },
  { id: "approvals", label: "Approvals", hint: "Drafts waiting on a person", internalOnly: true },
  { id: "dashboard", label: "Operations", hint: "Metrics and cost", internalOnly: true },
  { id: "audit", label: "Audit", hint: "Replay a case", internalOnly: true },
];

const EXTERNAL_ROLES = new Set(["public_lead", "customer", "resident", "broker", "contractor"]);

const ROLE_GROUPS: { label: string; match: (role: string) => boolean }[] = [
  { label: "Outside the company", match: (role) => EXTERNAL_ROLES.has(role) },
  { label: "Inside the company", match: (role) => !EXTERNAL_ROLES.has(role) },
];

export default function App() {
  const [actors, setActors] = useState<Actor[]>([]);
  const [actorId, setActorId] = useState<string | null>(null);
  const [view, setView] = useState<View>("chat");
  const [provider, setProvider] = useState<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [list, health] = await Promise.all([api.actors(), api.health()]);
        setActors(list);
        setActorId(list[0]?.actor_id ?? null);
        setProvider(health.llm_provider);
      } catch (exc) {
        setBootError(
          `Could not reach the API. Start it with \`make up\`, then reload. (${String(exc)})`,
        );
      }
    })();
  }, []);

  const actor = useMemo(() => actors.find((a) => a.actor_id === actorId) ?? null, [actors, actorId]);
  const isExternal = actor ? EXTERNAL_ROLES.has(actor.role) : true;
  const available = VIEWS.filter((entry) => !entry.internalOnly || !isExternal);

  // Switching to an external role while on an internal view would leave the UI
  // asking for data the API will refuse. Fall back rather than show an error.
  useEffect(() => {
    if (isExternal && view !== "chat") setView("chat");
  }, [isExternal, view]);

  if (bootError) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="sheet ticked max-w-md p-6">
          <div className="label-micro text-signal-red">API unreachable</div>
          <p className="mt-2 text-sm leading-relaxed text-ink">{bootError}</p>
        </div>
      </div>
    );
  }

  if (!actor) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="loading identities" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-paper">
      <header className="border-b border-paper-edge bg-white">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-sm font-semibold uppercase tracking-[0.2em] text-ink">
              BuildWise
            </span>
            <span className="hidden font-mono text-micro uppercase tracking-widest text-steel sm:inline">
              agentic support
            </span>
          </div>

          <nav className="flex flex-wrap gap-1.5">
            {available.map((entry) => (
              <button
                key={entry.id}
                title={entry.hint}
                onClick={() => setView(entry.id)}
                className={view === entry.id ? "btn-primary" : "btn-ghost"}
              >
                {entry.label}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex flex-wrap items-center gap-3">
            {provider && (
              <span
                title={
                  provider === "mock"
                    ? "Running the deterministic offline provider: no API key, no network, stable output. Set LLM_PROVIDER to use a real model."
                    : `Language generation via ${provider}`
                }
                className="border border-paper-edge px-2 py-1 font-mono text-micro uppercase tracking-wider text-steel"
              >
                llm: {provider}
              </span>
            )}
            <label className="flex items-center gap-2">
              <span className="label-micro">Acting as</span>
              <select
                className="field w-auto max-w-[280px] font-mono text-xs"
                value={actor.actor_id}
                onChange={(event) => setActorId(event.target.value)}
              >
                {ROLE_GROUPS.map((group) => (
                  <optgroup key={group.label} label={group.label}>
                    {actors
                      .filter((candidate) => group.match(candidate.role))
                      .map((candidate) => (
                        <option key={candidate.actor_id} value={candidate.actor_id}>
                          {candidate.display_name}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </label>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-4 py-5">
        {view === "chat" && <Chat actor={actor} />}
        {view === "approvals" && <Approvals actor={actor} />}
        {view === "dashboard" && <Dashboard actor={actor} />}
        {view === "audit" && <Audit actor={actor} />}
      </main>

      <footer className="mx-auto max-w-[1400px] px-4 pb-8 pt-2">
        <p className="border-t border-paper-edge pt-3 font-mono text-micro leading-relaxed text-steel">
          Numbers come from the systems of record; wording comes from approved documents. When a
          figure is missing the system says so instead of estimating.
        </p>
      </footer>
    </div>
  );
}
