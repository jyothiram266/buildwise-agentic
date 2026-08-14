// The signature element: a four-rung ladder that appears wherever a risk tier is
// shown. Tier is the single most important fact about a case in this system, so it
// gets one consistent visual form rather than four differently-coloured badges.

const RUNGS = [
  { tier: 0, label: "Auto", detail: "Answered automatically" },
  { tier: 1, label: "Notify", detail: "Answered, owning team told" },
  { tier: 2, label: "Draft", detail: "Held for human approval" },
  { tier: 3, label: "Escalate", detail: "Acknowledged only, human owns it" },
];

const TIER_COLOR: Record<number, string> = {
  0: "bg-signal-green",
  1: "bg-signal-blue",
  2: "bg-signal-amber",
  3: "bg-signal-red",
};

export function RiskLadder({
  tier,
  compact = false,
}: {
  tier: number | null;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "flex items-end gap-[3px]" : "flex items-end gap-1"}>
      {RUNGS.map((rung) => {
        const active = tier !== null && rung.tier <= tier;
        const isCurrent = tier === rung.tier;
        const height = compact ? 6 + rung.tier * 3 : 10 + rung.tier * 6;
        return (
          <div
            key={rung.tier}
            title={`Tier ${rung.tier} — ${rung.label}: ${rung.detail}`}
            style={{ height }}
            className={[
              compact ? "w-[5px]" : "w-2",
              "rounded-sm transition-colors",
              active ? TIER_COLOR[tier ?? 0] : "bg-paper-deep",
              isCurrent ? "ring-1 ring-ink/30 ring-offset-1" : "",
            ].join(" ")}
          />
        );
      })}
    </div>
  );
}

export function TierBadge({ tier }: { tier: number | null }) {
  if (tier === null) return <span className="label-micro">tier —</span>;
  const rung = RUNGS[tier] ?? RUNGS[0];
  return (
    <span className="inline-flex items-center gap-2">
      <RiskLadder tier={tier} compact />
      <span className="font-mono text-xs uppercase tracking-wider text-ink-soft">
        T{tier} {rung.label}
      </span>
    </span>
  );
}

export { RUNGS as RISK_RUNGS };
