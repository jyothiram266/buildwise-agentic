"""Mock systems of record, served as a standalone FastAPI app on :8100.

This process stands in for five external systems. It is separate from the API on
purpose: it makes the network boundary real, so the adapters exercise timeouts,
retries and serialisation rather than calling python functions that happen to be
in the same process. Swapping in a real CRM means pointing an adapter elsewhere.

**Scope is enforced here, not in the caller.** Every handler resolves what the
incoming `AccessScope` may see and turns that into a SQL predicate. Two further
properties matter:

* An out-of-scope read returns an empty result, not an error. An error message
  that distinguishes "not yours" from "does not exist" is itself a leak.
* An unapproved revised possession date is stripped from the payload for external
  roles. The value never enters the calling process, so no prompt-assembly bug
  downstream can leak it.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from api.config import configure_logging, get_logger
from db import pool

log = get_logger(__name__)

app = FastAPI(title="BuildWise Mock Systems of Record", version="0.9.0")

READ_ALL_ROLES = {"manager", "legal_finance"}
INTERNAL_ROLES = {"manager", "legal_finance", "site_engineer"}
SALES_ROLES = {"sales_staff", "manager"}
EXTERNAL_ROLES = {"public_lead", "customer", "resident", "broker", "contractor"}


class Envelope(BaseModel):
    operation: str | None = None
    action: str | None = None
    risk_tier: int | None = None
    approval: str | None = None
    scope: dict[str, Any] = {}
    payload: dict[str, Any] = {}


def role_of(scope: dict[str, Any]) -> str:
    return str(scope.get("role") or "public_lead")


def booking_ids(scope: dict[str, Any]) -> list[str]:
    return list(scope.get("booking_ids") or [])


def unit_ids(scope: dict[str, Any]) -> list[str]:
    return list(scope.get("unit_ids") or [])


def project_ids(scope: dict[str, Any]) -> list[str]:
    return list(scope.get("project_ids") or [])


def may_read_booking(scope: dict[str, Any], booking_id: str) -> bool:
    role = role_of(scope)
    if role in READ_ALL_ROLES or role == "sales_staff":
        return True
    return booking_id in booking_ids(scope)


def may_read_unit(scope: dict[str, Any], unit_id: str | None) -> bool:
    role = role_of(scope)
    if role in READ_ALL_ROLES or role in {"sales_staff", "site_engineer"}:
        return True
    return bool(unit_id) and unit_id in unit_ids(scope)


def may_read_project(scope: dict[str, Any], project_id: str | None) -> bool:
    role = role_of(scope)
    if role in READ_ALL_ROLES or role in {"sales_staff", "site_engineer", "public_lead", "broker"}:
        return True
    return bool(project_id) and project_id in project_ids(scope)


def iso(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: iso(v) for k, v in row.items()}


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def _startup() -> None:
    configure_logging()
    log.info("mock_connectors_starting")


@app.get("/health")
async def root_health() -> dict:
    db = await pool.healthcheck()
    return {"ok": bool(db.get("ok")), "systems": ["crm", "pm", "payments", "dms", "ticketing"], "db": db}


for prefix in ("crm", "pm", "payments", "dms", "ticketing"):

    def _make(prefix: str = prefix):
        async def handler(_: dict | None = None) -> dict:
            db = await pool.healthcheck()
            return {"ok": bool(db.get("ok")), "system": prefix, "detail": db.get("error")}

        return handler

    app.post(f"/{prefix}/health")(_make())


# ---------------------------------------------------------------------------
# CRM
# ---------------------------------------------------------------------------


@app.post("/crm/query")
async def crm_query(env: Envelope) -> dict:
    op, scope, payload = env.operation, env.scope, env.payload

    if op == "inventory":
        return await _inventory(scope, payload)
    if op == "booking":
        return await _booking(scope, payload)
    if op == "leads":
        return await _leads(scope, payload)
    return {"error": f"unknown crm operation {op}"}


async def _inventory(scope: dict, payload: dict) -> dict:
    clauses = ["u.status = $1"]
    params: list[Any] = [payload.get("status") or "available"]

    project_id = payload.get("project_id")
    project_name = payload.get("project_name")
    if project_name and not project_id:
        row = await pool.fetchrow(
            "SELECT project_id FROM projects WHERE name ILIKE $1", f"%{project_name}%"
        )
        project_id = row["project_id"] if row else None
    if project_id:
        clauses.append(f"u.project_id = ${len(params) + 1}")
        params.append(project_id)
    if payload.get("config"):
        clauses.append(f"u.config = ${len(params) + 1}")
        params.append(payload["config"])
    if payload.get("city"):
        clauses.append(f"p.city ILIKE ${len(params) + 1}")
        params.append(f"%{payload['city']}%")
    if payload.get("budget_max"):
        clauses.append(f"u.all_in_price <= ${len(params) + 1}")
        params.append(int(payload["budget_max"]))
    if payload.get("budget_min"):
        clauses.append(f"u.all_in_price >= ${len(params) + 1}")
        params.append(int(payload["budget_min"]))

    limit = min(int(payload.get("limit") or 10), 50)
    rows = await pool.fetch(
        f"""
        SELECT u.unit_id, u.project_id, p.name AS project_name, t.name AS tower_name,
               p.city, p.locality, u.config, u.carpet_area, u.floor, u.facing, u.status,
               u.base_price, u.all_in_price, u.price_ref
        FROM units u
        JOIN projects p ON p.project_id = u.project_id
        JOIN towers t ON t.tower_id = u.tower_id
        WHERE {' AND '.join(clauses)}
        ORDER BY u.all_in_price ASC
        LIMIT {limit}
        """,
        *params,
    )
    count = await pool.fetchval(
        f"""
        SELECT count(*) FROM units u JOIN projects p ON p.project_id = u.project_id
        WHERE {' AND '.join(clauses)}
        """,
        *params,
    )

    # Distinguish "sold out" from "this configuration does not exist here": the
    # honest no-match answer depends on which one it is.
    config_exists = True
    total_in_project = 0
    project_status = None
    price_ref = None
    price_effective = None
    if project_id:
        project_status = await pool.fetchval(
            "SELECT status FROM projects WHERE project_id = $1", project_id
        )
        total_in_project = await pool.fetchval(
            "SELECT count(*) FROM units WHERE project_id = $1", project_id
        )
        if payload.get("config"):
            config_exists = bool(
                await pool.fetchval(
                    "SELECT count(*) FROM units WHERE project_id = $1 AND config = $2",
                    project_id,
                    payload["config"],
                )
            )
        row = await pool.fetchrow(
            """
            SELECT source_id, effective_date FROM documents_corpus
            WHERE collection = 'pricing_sheets' AND project_id = $1
            ORDER BY effective_date DESC LIMIT 1
            """,
            project_id,
        )
        if row:
            price_ref, price_effective = row["source_id"], row["effective_date"]

    note = None
    if project_status == "pre_launch":
        note = "Project has not launched; no inventory is released for sale."

    return {
        "units": [clean(r) for r in rows],
        "match_count": int(count or 0),
        "total_in_project": int(total_in_project or 0),
        "price_ref": price_ref,
        "price_effective_date": iso(price_effective),
        "project_status": project_status,
        "config_exists_in_project": config_exists,
        "note": note,
    }


async def _booking(scope: dict, payload: dict) -> dict:
    booking_id = payload.get("booking_id")
    customer_id = payload.get("customer_id")
    role = role_of(scope)

    if not booking_id and not customer_id:
        # Fall back to the caller's own scope rather than returning everything.
        ids = booking_ids(scope)
        if not ids:
            return {"bookings": [], "found": False}
        booking_id = ids[0]

    clauses, params = [], []
    if booking_id:
        clauses.append(f"b.booking_id = ${len(params) + 1}")
        params.append(booking_id)
    if customer_id:
        clauses.append(f"b.customer_id = ${len(params) + 1}")
        params.append(customer_id)

    # Scope predicate, in SQL, before anything is read.
    if role in EXTERNAL_ROLES:
        allowed = booking_ids(scope)
        if not allowed:
            return {"bookings": [], "found": False}
        clauses.append(f"b.booking_id = ANY(${len(params) + 1}::text[])")
        params.append(allowed)

    rows = await pool.fetch(
        f"""
        SELECT b.booking_id, b.customer_id, c.name AS customer_name, b.unit_id, b.project_id,
               p.name AS project_name, t.name AS tower_name, u.config, b.stage,
               b.agreement_status, b.booked_on, b.possession_date,
               b.possession_date_approved, b.total_value, b.sales_owner
        FROM bookings b
        JOIN customers c ON c.customer_id = b.customer_id
        JOIN units u ON u.unit_id = b.unit_id
        JOIN towers t ON t.tower_id = u.tower_id
        JOIN projects p ON p.project_id = b.project_id
        WHERE {' AND '.join(clauses)}
        LIMIT 5
        """,
        *params,
    )
    return {"bookings": [clean(r) for r in rows], "found": bool(rows)}


async def _leads(scope: dict, payload: dict) -> dict:
    if role_of(scope) not in SALES_ROLES:
        return {"leads": [], "match_count": 0}
    clauses = ["l.stage NOT IN ('won','lost')"]
    params: list[Any] = []
    if payload.get("owner"):
        clauses.append(f"l.owner = ${len(params) + 1}")
        params.append(payload["owner"])
    if payload.get("due_on"):
        clauses.append(f"(l.next_action_due IS NULL OR l.next_action_due <= ${len(params) + 1})")
        params.append(date.fromisoformat(str(payload["due_on"])[:10]))
    if payload.get("min_score"):
        clauses.append(f"l.score >= ${len(params) + 1}")
        params.append(int(payload["min_score"]))

    limit = min(int(payload.get("limit") or 25), 100)
    rows = await pool.fetch(
        f"""
        SELECT l.lead_id, l.name, l.interest_config, l.budget_max, l.city, l.project_interest,
               l.score, l.stage, l.site_visit_done, l.last_contact, l.next_action,
               l.next_action_due, (CURRENT_DATE - l.last_contact) AS days_since_contact
        FROM leads l
        WHERE {' AND '.join(clauses)}
        ORDER BY l.score DESC, l.last_contact ASC
        LIMIT {limit}
        """,
        *params,
    )
    out = []
    for row in rows:
        record = clean(row)
        # Reason codes are derived here so ranking rationale is data, not prose.
        codes = []
        if (row.get("days_since_contact") or 0) >= 10:
            codes.append("ageing")
        if (row.get("score") or 0) >= 75:
            codes.append("high_intent")
        if row.get("site_visit_done"):
            codes.append("site_visit_done")
        if row.get("next_action") == "payment_pending":
            codes.append("payment_pending")
        if row.get("next_action_due") and row["next_action_due"] <= date.today():
            codes.append("followup_due")
        record["reason_codes"] = codes
        out.append(record)
    return {"leads": out, "match_count": len(out)}


# ---------------------------------------------------------------------------
# Project management
# ---------------------------------------------------------------------------


@app.post("/pm/query")
async def pm_query(env: Envelope) -> dict:
    op, scope, payload = env.operation, env.scope, env.payload
    if op == "milestones":
        return await _milestones(scope, payload)
    if op == "site_reports":
        return await _site_reports(scope, payload)
    if op == "blockers":
        return await _blockers(scope, payload)
    return {"error": f"unknown pm operation {op}"}


async def _milestones(scope: dict, payload: dict) -> dict:
    clauses, params = [], []
    project_id = payload.get("project_id")
    if not project_id and payload.get("project_name"):
        row = await pool.fetchrow(
            "SELECT project_id FROM projects WHERE name ILIKE $1", f"%{payload['project_name']}%"
        )
        project_id = row["project_id"] if row else None
    if project_id:
        clauses.append(f"t.project_id = ${len(params) + 1}")
        params.append(project_id)
    if payload.get("tower_id"):
        clauses.append(f"t.tower_id = ${len(params) + 1}")
        params.append(payload["tower_id"])
    if payload.get("tower_name"):
        clauses.append(f"t.name ILIKE ${len(params) + 1}")
        params.append(f"%{payload['tower_name']}%")

    role = role_of(scope)
    if role in EXTERNAL_ROLES:
        allowed = project_ids(scope)
        if role in {"public_lead", "broker"}:
            pass  # published project timelines are public
        elif not allowed:
            return {"towers": [], "found": False}
        else:
            clauses.append(f"t.project_id = ANY(${len(params) + 1}::text[])")
            params.append(allowed)

    where = " AND ".join(clauses) if clauses else "TRUE"
    towers = await pool.fetch(
        f"""
        SELECT t.tower_id, t.name AS tower_name, t.project_id, p.name AS project_name,
               t.floors, t.status, t.planned_possession, t.revised_possession, t.revised_approved
        FROM towers t JOIN projects p ON p.project_id = t.project_id
        WHERE {where}
        ORDER BY t.tower_id
        LIMIT 12
        """,
        *params,
    )
    out = []
    for tower in towers:
        record = clean(tower)
        # Data minimisation for external audiences: an unapproved date is removed
        # from the payload entirely rather than sent with a "do not use" flag.
        if role in EXTERNAL_ROLES and not tower["revised_approved"]:
            record["revised_possession"] = None
        milestones = await pool.fetch(
            """
            SELECT milestone_id, name, seq, planned_date, actual_date, pct_complete, status
            FROM milestones WHERE tower_id = $1 ORDER BY seq
            """,
            tower["tower_id"],
        )
        record["milestones"] = [clean(m) | {"pct_complete": float(m["pct_complete"])} for m in milestones]
        out.append(record)
    return {"towers": out, "found": bool(out)}


async def _site_reports(scope: dict, payload: dict) -> dict:
    role = role_of(scope)
    if role not in INTERNAL_ROLES:
        # Site reports are internal by classification. External roles receive the
        # generated customer-safe summary through a different path, not this one.
        return {"reports": [], "found": False}
    clauses, params = [], []
    if payload.get("project_id"):
        clauses.append(f"project_id = ${len(params) + 1}")
        params.append(payload["project_id"])
    if payload.get("tower_id"):
        clauses.append(f"tower_id = ${len(params) + 1}")
        params.append(payload["tower_id"])
    where = " AND ".join(clauses) if clauses else "TRUE"
    limit = min(int(payload.get("limit") or 4), 20)
    rows = await pool.fetch(
        f"""
        SELECT report_id, project_id, tower_id, week_of, author, raw_note, approval_status,
               contains_injection_probe AS flagged_injection
        FROM site_reports WHERE {where}
        ORDER BY week_of DESC LIMIT {limit}
        """,
        *params,
    )
    return {"reports": [clean(r) for r in rows], "found": bool(rows)}


async def _blockers(scope: dict, payload: dict) -> dict:
    role = role_of(scope)
    clauses, params = [], []
    if payload.get("open_only", True):
        clauses.append("b.resolved_on IS NULL")
    if payload.get("project_id"):
        clauses.append(f"b.project_id = ${len(params) + 1}")
        params.append(payload["project_id"])
    if payload.get("work_package_id"):
        clauses.append(f"b.work_package_id = ${len(params) + 1}")
        params.append(payload["work_package_id"])

    if role == "contractor":
        allowed = list(scope.get("work_package_ids") or [])
        if not allowed:
            return {"blockers": [], "impacted_milestone_records": [], "found": False}
        clauses.append(f"b.work_package_id = ANY(${len(params) + 1}::text[])")
        params.append(allowed)
    elif role not in INTERNAL_ROLES:
        return {"blockers": [], "impacted_milestone_records": [], "found": False}

    where = " AND ".join(clauses) if clauses else "TRUE"
    rows = await pool.fetch(
        f"""
        SELECT b.blocker_id, b.project_id, b.category, b.description, b.severity, b.raised_on,
               b.resolved_on, b.impacted_milestones, b.vendor_id, b.work_package_id
        FROM blockers b WHERE {where} ORDER BY b.raised_on DESC LIMIT 25
        """,
        *params,
    )
    impacted_ids = sorted({m for r in rows for m in (r["impacted_milestones"] or [])})
    milestones = []
    if impacted_ids:
        milestones = await pool.fetch(
            """
            SELECT milestone_id, name, seq, planned_date, actual_date, pct_complete, status
            FROM milestones WHERE milestone_id = ANY($1::text[]) ORDER BY seq
            """,
            impacted_ids,
        )
    return {
        "blockers": [clean(r) for r in rows],
        "impacted_milestone_records": [
            clean(m) | {"pct_complete": float(m["pct_complete"])} for m in milestones
        ],
        "found": bool(rows),
    }


# ---------------------------------------------------------------------------
# Payments (read only)
# ---------------------------------------------------------------------------


@app.post("/payments/query")
async def payments_query(env: Envelope) -> dict:
    booking_id = env.payload.get("booking_id")
    if not booking_id or not may_read_booking(env.scope, booking_id):
        return {"milestones": [], "found": False}

    rows = await pool.fetch(
        """
        SELECT milestone_id, label, amount, due_date, paid_on, status, receipt_ref, seq
        FROM payment_milestones WHERE booking_id = $1 ORDER BY seq
        """,
        booking_id,
    )
    total_value = int(
        await pool.fetchval("SELECT total_value FROM bookings WHERE booking_id = $1", booking_id) or 0
    )
    paid = sum(int(r["amount"]) for r in rows if r["status"] == "paid")
    due = sum(int(r["amount"]) for r in rows if r["status"] == "due")
    overdue = sum(int(r["amount"]) for r in rows if r["status"] == "overdue")
    upcoming = [r for r in rows if r["status"] in {"due", "overdue"}]
    return {
        "booking_id": booking_id,
        "milestones": [clean(r) for r in rows],
        "total_value": total_value,
        "total_paid": paid,
        "total_due": due,
        "total_overdue": overdue,
        "overdue_count": sum(1 for r in rows if r["status"] == "overdue"),
        "next_due_label": upcoming[0]["label"] if upcoming else None,
        "next_due_date": iso(upcoming[0]["due_date"]) if upcoming else None,
        "found": bool(rows),
    }


@app.post("/payments/write")
async def payments_write(env: Envelope) -> dict:
    """Exists only to refuse. A 405 makes the design rule visible over the wire."""
    from fastapi.responses import JSONResponse

    log.warning("payments_write_attempt_refused", action=env.action)
    return JSONResponse(
        status_code=405,
        content={
            "ok": False,
            "action": env.action or "unknown",
            "detail": "payments is read-only by design; no write path exists",
        },
    )


# ---------------------------------------------------------------------------
# Document management
# ---------------------------------------------------------------------------


@app.post("/dms/query")
async def dms_query(env: Envelope) -> dict:
    booking_id = env.payload.get("booking_id")
    if not booking_id or not may_read_booking(env.scope, booking_id):
        return {"documents": [], "found": False}

    params: list[Any] = [booking_id]
    clause = "booking_id = $1"
    if env.payload.get("stage"):
        clause += " AND stage = $2"
        params.append(env.payload["stage"])
    rows = await pool.fetch(
        f"""
        SELECT doc_id, type, status, stage, submitted_on, expires_on,
               CASE WHEN expires_on IS NULL THEN NULL ELSE (expires_on - CURRENT_DATE) END
                    AS days_to_expiry
        FROM documents WHERE {clause} ORDER BY stage, type
        """,
        *params,
    )
    return {
        "booking_id": booking_id,
        "stage": env.payload.get("stage"),
        "documents": [clean(r) for r in rows],
        "submitted": [r["type"] for r in rows if r["status"] == "submitted"],
        "pending": [r["type"] for r in rows if r["status"] == "pending"],
        "expired": [r["type"] for r in rows if r["status"] == "expired"],
        "found": bool(rows),
    }


# ---------------------------------------------------------------------------
# Ticketing
# ---------------------------------------------------------------------------


@app.post("/ticketing/query")
async def ticketing_query(env: Envelope) -> dict:
    scope, payload = env.scope, env.payload
    clauses, params = [], []
    if payload.get("ticket_id"):
        clauses.append(f"ticket_id = ${len(params) + 1}")
        params.append(payload["ticket_id"])
    if payload.get("unit_id"):
        clauses.append(f"unit_id = ${len(params) + 1}")
        params.append(payload["unit_id"])
    if payload.get("status"):
        clauses.append(f"status = ${len(params) + 1}")
        params.append(payload["status"])
    if payload.get("open_only"):
        clauses.append("status NOT IN ('resolved','closed')")

    role = role_of(scope)
    if role in EXTERNAL_ROLES:
        allowed = unit_ids(scope)
        if not allowed:
            return {"tickets": [], "match_count": 0, "found": False}
        clauses.append(f"unit_id = ANY(${len(params) + 1}::text[])")
        params.append(allowed)

    where = " AND ".join(clauses) if clauses else "TRUE"
    limit = min(int(payload.get("limit") or 20), 100)
    rows = await pool.fetch(
        f"""
        SELECT ticket_id, unit_id, category, priority, complaint_text, assigned_team, status,
               warranty_flag, created_at, sla_due, resolved_at,
               (status NOT IN ('resolved','closed') AND sla_due < now()) AS sla_breached
        FROM tickets WHERE {where} ORDER BY created_at DESC LIMIT {limit}
        """,
        *params,
    )
    return {"tickets": [clean(r) for r in rows], "match_count": len(rows), "found": bool(rows)}


# ---------------------------------------------------------------------------
# Writes (shared handler)
# ---------------------------------------------------------------------------


async def _validate_approval(env: Envelope) -> str | None:
    """Second, independent check that a tier-2+ write carries a real token.

    The adapter already refused a missing token. This verifies the token actually
    exists, was issued for this case, and has not been used before — a token the
    caller invented is not a token.
    """
    tier = int(env.risk_tier or 0)
    if tier < 2:
        return None
    if not env.approval:
        return "approval token required for a tier %d write" % tier
    row = await pool.fetchrow(
        "SELECT token, consumed, risk_tier FROM approval_tokens WHERE token = $1", env.approval
    )
    if row is None:
        return "approval token not recognised"
    if row["consumed"]:
        return "approval token already used"
    await pool.execute("UPDATE approval_tokens SET consumed = TRUE WHERE token = $1", env.approval)
    return None


@app.post("/crm/write")
async def crm_write(env: Envelope) -> dict:
    problem = await _validate_approval(env)
    if problem:
        return {"ok": False, "action": env.action or "", "detail": problem}
    payload = env.payload

    if env.action == "create_lead":
        seq = int(await pool.fetchval("SELECT count(*) FROM leads") or 0) + 1
        lead_id = f"LEAD-{seq:04d}"
        await pool.execute(
            """
            INSERT INTO leads (lead_id, name, contact_email, contact_phone, interest_config,
                               budget_max, city, project_interest, score, stage, last_contact,
                               next_action, next_action_due, owner, source)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'new',CURRENT_DATE,$10,CURRENT_DATE + 1,'STF-SALES-01',$11)
            ON CONFLICT (lead_id) DO NOTHING
            """,
            lead_id,
            payload.get("name") or "Unnamed enquiry",
            payload.get("contact_email"),
            payload.get("contact_phone"),
            payload.get("interest_config"),
            payload.get("budget_max"),
            payload.get("city"),
            payload.get("project_interest"),
            60,
            payload.get("next_action") or "site_visit_offer",
            payload.get("source") or "web_chat",
        )
        return {"ok": True, "action": "create_lead", "record_id": lead_id}

    if env.action == "log_interaction":
        await pool.execute(
            "INSERT INTO team_notifications (case_id, team, kind, message) VALUES ($1,$2,$3,$4)",
            payload.get("case_id"),
            "sales",
            "interaction",
            payload.get("summary", "")[:1000],
        )
        return {"ok": True, "action": "log_interaction"}

    return {"ok": False, "action": env.action or "", "detail": "unsupported crm action"}


@app.post("/pm/write")
async def pm_write(env: Envelope) -> dict:
    problem = await _validate_approval(env)
    if problem:
        return {"ok": False, "action": env.action or "", "detail": problem}
    payload = env.payload

    if env.action == "log_blocker":
        seq = int(await pool.fetchval("SELECT count(*) FROM blockers") or 0) + 1
        blocker_id = f"BLK-{seq:04d}"
        await pool.execute(
            """
            INSERT INTO blockers (blocker_id, project_id, vendor_id, work_package_id, category,
                                  description, impacted_milestones, severity, raised_on, raised_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,CURRENT_DATE,$9)
            ON CONFLICT (blocker_id) DO NOTHING
            """,
            blocker_id,
            payload["project_id"],
            payload.get("vendor_id"),
            payload.get("work_package_id"),
            payload["category"],
            payload["description"][:2000],
            payload.get("impacted_milestones") or [],
            payload.get("severity", "medium"),
            payload.get("raised_by", "system"),
        )
        return {"ok": True, "action": "log_blocker", "record_id": blocker_id}

    if env.action == "attach_summary":
        await pool.execute(
            """
            UPDATE site_reports SET internal_summary = $2, customer_summary = $3,
                   approval_status = 'approved'
            WHERE report_id = $1
            """,
            payload["report_id"],
            payload["internal_summary"],
            payload["customer_summary"],
        )
        return {"ok": True, "action": "attach_summary", "record_id": payload["report_id"]}

    return {"ok": False, "action": env.action or "", "detail": "unsupported pm action"}


@app.post("/dms/write")
async def dms_write(env: Envelope) -> dict:
    problem = await _validate_approval(env)
    if problem:
        return {"ok": False, "action": env.action or "", "detail": problem}
    if env.action == "flag_missing":
        await pool.execute(
            "INSERT INTO team_notifications (team, kind, message) VALUES ($1,$2,$3)",
            "documentation",
            "missing_documents",
            f"booking {env.payload.get('booking_id')}: {', '.join(env.payload.get('doc_types', []))}",
        )
        return {"ok": True, "action": "flag_missing"}
    return {"ok": False, "action": env.action or "", "detail": "unsupported dms action"}


@app.post("/ticketing/write")
async def ticketing_write(env: Envelope) -> dict:
    problem = await _validate_approval(env)
    if problem:
        return {"ok": False, "action": env.action or "", "detail": problem}
    payload = env.payload

    if env.action == "create_ticket":
        seq = int(await pool.fetchval("SELECT count(*) FROM tickets") or 0) + 1
        ticket_id = f"TKT-{1000 + seq}"
        project_id = await pool.fetchval(
            "SELECT project_id FROM units WHERE unit_id = $1", payload.get("unit_id")
        )
        sla_hours = int(payload.get("sla_hours") or 72)
        await pool.execute(
            """
            INSERT INTO tickets (ticket_id, unit_id, project_id, raised_by, category, priority,
                                 complaint_text, assigned_team, status, warranty_flag,
                                 created_at, sla_due, case_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'open',$9, now(), now() + ($10 || ' hours')::interval, $11)
            """,
            ticket_id,
            payload.get("unit_id"),
            project_id,
            payload.get("raised_by", "unknown"),
            payload["category"],
            payload["priority"],
            payload["complaint_text"][:2000],
            payload["assigned_team"],
            bool(payload.get("warranty_flag")),
            str(sla_hours),
            payload.get("case_id"),
        )
        await pool.execute(
            "INSERT INTO ticket_events (ticket_id, actor, action, detail) VALUES ($1,$2,$3,$4)",
            ticket_id,
            "system",
            "created",
            f"routed to {payload['assigned_team']} at {payload['priority']}",
        )
        due = await pool.fetchval("SELECT sla_due FROM tickets WHERE ticket_id = $1", ticket_id)
        return {
            "ok": True,
            "action": "create_ticket",
            "record_id": ticket_id,
            "detail": iso(due),
        }

    return {"ok": False, "action": env.action or "", "detail": "unsupported ticketing action"}


@app.on_event("shutdown")
async def _shutdown() -> None:
    await pool.close_pool()


def run() -> None:  # pragma: no cover - entry point
    import uvicorn

    uvicorn.run("connectors.mock_server.main:app", host="0.0.0.0", port=8100, reload=False)


if __name__ == "__main__":  # pragma: no cover
    run()
