-- ---------------------------------------------------------------------------
-- 001_init — reporting views layered on top of db/schema.sql.
--
-- The base tables live in schema.sql (applied first by scripts/migrate.py).
-- Views live in a migration because they change more often than tables do, and
-- the dashboard reads them directly rather than assembling the same joins in
-- five different route handlers.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_tower_progress AS
SELECT
    t.tower_id,
    t.project_id,
    p.name  AS project_name,
    t.name  AS tower_name,
    count(m.milestone_id)                                              AS milestones_total,
    count(m.milestone_id) FILTER (WHERE m.status = 'completed')         AS milestones_complete,
    COALESCE(round(avg(m.pct_complete), 2), 0)                         AS pct_complete,
    COALESCE(max(
        CASE
            WHEN m.actual_date IS NOT NULL THEN (m.actual_date - m.planned_date)
            WHEN m.planned_date < CURRENT_DATE AND m.status <> 'completed'
                THEN (CURRENT_DATE - m.planned_date)
            ELSE 0
        END), 0)                                                       AS max_slip_days
FROM towers t
JOIN projects p ON p.project_id = t.project_id
LEFT JOIN milestones m ON m.tower_id = t.tower_id
GROUP BY t.tower_id, t.project_id, p.name, t.name;

CREATE OR REPLACE VIEW v_delayed_milestones AS
SELECT
    m.milestone_id, m.project_id, m.tower_id, p.name AS project_name,
    t.name AS tower_name, m.name, m.planned_date, m.actual_date, m.pct_complete,
    CASE
        WHEN m.actual_date IS NOT NULL THEN (m.actual_date - m.planned_date)
        ELSE (CURRENT_DATE - m.planned_date)
    END AS slip_days
FROM milestones m
JOIN projects p ON p.project_id = m.project_id
LEFT JOIN towers t ON t.tower_id = m.tower_id
WHERE (m.actual_date IS NOT NULL AND m.actual_date > m.planned_date)
   OR (m.actual_date IS NULL AND m.status <> 'completed' AND m.planned_date < CURRENT_DATE);

CREATE OR REPLACE VIEW v_sla_breached_tickets AS
SELECT ticket_id, unit_id, project_id, category, priority, assigned_team, status,
       sla_due, created_at,
       EXTRACT(EPOCH FROM (now() - sla_due)) / 3600 AS hours_overdue
FROM tickets
WHERE status NOT IN ('resolved', 'closed') AND sla_due < now();

CREATE OR REPLACE VIEW v_open_escalations AS
SELECT e.esc_id, e.case_id, e.type, e.owner_team, e.sla_due, e.status, e.assigned_to,
       c.role AS actor_role, c.intent, e.created_at,
       EXTRACT(EPOCH FROM (now() - e.created_at)) / 3600 AS age_hours,
       (e.sla_due < now()) AS breached
FROM escalations e
JOIN cases c ON c.case_id = e.case_id
WHERE e.status <> 'resolved';

CREATE OR REPLACE VIEW v_followups_due AS
SELECT lead_id, name, interest_config, budget_max, city, project_interest, score,
       stage, site_visit_done, last_contact, next_action, next_action_due, owner,
       (CURRENT_DATE - last_contact) AS days_since_contact
FROM leads
WHERE stage NOT IN ('won', 'lost')
  AND (next_action_due IS NULL OR next_action_due <= CURRENT_DATE);
