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
      <div className="flex min-h-screen items-center justify-center bg-slate-900 p-6">
        <div className="sheet ticked max-w-md p-6 border-red-500/30 bg-slate-900 text-white shadow-2xl">
          <div className="flex items-center gap-2 label-micro text-rose-400">
            <span className="h-2 w-2 rounded-full bg-rose-500 animate-pulse" />
            API Connection Error
          </div>
          <p className="mt-3 text-sm leading-relaxed text-slate-300">{bootError}</p>
        </div>
      </div>
    );
  }

  if (!actor) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="sheet p-8 shadow-xl text-center">
          <Spinner label="Loading Agentic Console" />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-paper font-sans">
      {/* Top Glass Navbar */}
      <header className="glass-header">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-x-6 gap-y-3 px-6 py-3.5">
          {/* Logo & Brand */}
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-ink text-white shadow-sm ring-1 ring-white/20">
              <svg className="h-5 w-5 text-brand-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5m0 0h4m-4 0V11m0 0h4m-4 0H7m4 0v10" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-display text-base font-bold tracking-tight text-ink">
                  BuildWise
                </span>
                <span className="rounded bg-brand-50 px-1.5 py-0.2 font-mono text-[10px] font-semibold uppercase tracking-wider text-brand-700 border border-brand-200">
                  AI OS
                </span>
              </div>
              <span className="hidden text-[11px] font-medium text-slate-500 sm:block">
                Grounded Enterprise Support System
              </span>
            </div>
          </div>

          {/* Navigation Pill Tabs */}
          <nav className="flex items-center gap-1 rounded-xl bg-slate-100/80 p-1 border border-slate-200/60">
            {available.map((entry) => {
              const active = view === entry.id;
              return (
                <button
                  key={entry.id}
                  title={entry.hint}
                  onClick={() => setView(entry.id)}
                  className={`relative flex items-center gap-2 rounded-lg px-4 py-1.5 font-mono text-xs uppercase font-semibold tracking-wider transition-all duration-150 ${
                    active
                      ? "bg-white text-ink shadow-xs"
                      : "text-slate-600 hover:text-ink hover:bg-slate-200/50"
                  }`}
                >
                  {entry.label}
                  {active && (
                    <span className="h-1.5 w-1.5 rounded-full bg-brand-600" />
                  )}
                </button>
              );
            })}
          </nav>

          {/* User & Provider Controls */}
          <div className="flex items-center gap-3">
            {provider && (
              <div
                title={
                  provider === "mock"
                    ? "Running deterministic offline provider: zero latency, reproducible rules."
                    : `Active OpenAI Intelligence Engine (${provider})`
                }
                className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 font-mono text-micro uppercase tracking-wider font-semibold shadow-2xs ${
                  provider === "mock"
                    ? "border-amber-200 bg-amber-50/80 text-amber-800"
                    : "border-emerald-200 bg-emerald-50/80 text-emerald-800"
                }`}
              >
                <span className={`h-2 w-2 rounded-full ${provider === "mock" ? "bg-amber-500" : "bg-emerald-500 animate-pulse"}`} />
                <span>LLM: {provider}</span>
              </div>
            )}

            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1 shadow-2xs">
              <span className="label-micro text-slate-400">Identity:</span>
              <select
                className="bg-transparent font-mono text-xs font-semibold text-ink focus:outline-none cursor-pointer"
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
            </div>
          </div>
        </div>
      </header>

      {/* Main View Container */}
      <main className="mx-auto max-w-[1440px] px-6 py-6">
        {view === "chat" && <Chat actor={actor} />}
        {view === "approvals" && <Approvals actor={actor} />}
        {view === "dashboard" && <Dashboard actor={actor} />}
        {view === "audit" && <Audit actor={actor} />}
      </main>

      {/* Sleek Footer */}
      <footer className="mx-auto max-w-[1440px] px-6 pb-8 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-200/80 pt-4 font-mono text-micro text-slate-500">
          <p className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
            Numbers sourced from live connectors · Prose synthesized from vetted knowledge corpus · High risk auto-escalated
          </p>
          <p className="text-slate-400">BuildWise OS v1.2</p>
        </div>
      </footer>
    </div>
  );
}
