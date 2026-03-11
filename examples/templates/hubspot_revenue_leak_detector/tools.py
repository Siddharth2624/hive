"""
HubSpot Revenue Leak Detector — Custom Tools

Architecture
------------
The LLM uses HubSpot MCP tools to fetch live deal data, then passes that data
to our Python tools which serialise it and return it via output keys so it
flows cleanly across nodes via output_keys/input_keys without contextvars.

Node flow:
  monitor   → hubspot_search_deals (MCP)
              + hubspot_get_deal(include_associations=["contacts"]) (MCP)
              + hubspot_get_contact (MCP)
              → scan_pipeline(cycle, deals)     [returns deals_json]
              → set_output("deals_json", ...)

  analyze   → detect_revenue_leaks(cycle, deals_json)  [returns leaks_json]
              → set_output("leaks_json", ...)

  notify    → build_telegram_alert(..., leaks_json)  [builds + sends Telegram message internally]

  followup  → prepare_followup_emails(cycle, leaks_json)
              → gmail_create_draft (MCP) per GHOSTED contact

Required credentials (via env vars / MCP credential store):
  HUBSPOT_ACCESS_TOKEN  — HubSpot Private App token
  TELEGRAM_BOT_TOKEN    — Telegram bot token
  TELEGRAM_CHAT_ID      — Telegram chat ID (find via /getUpdates)
  Google OAuth          — Required for gmail_create_draft (sign in via hive open)
"""

import html as _html
import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Any

from framework.llm.provider import Tool, ToolUse, ToolResult

MAX_CYCLES = 3  # halt after this many consecutive low-severity cycles
MAX_TOTAL_CYCLES = 10  # absolute cap — prevents infinite loops

_SEVERITY_EMOJI: dict[str, str] = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🔴",
    "critical": "🚨",
}

# HubSpot API deal stage → human-readable name
_STAGE_MAP: dict[str, str] = {
    "appointmentscheduled": "Demo Scheduled",
    "qualifiedtobuy": "Qualified",
    "presentationscheduled": "Proposal Sent",
    "decisionmakerboughtin": "Negotiation",
    "contractsent": "Contract Sent",
    "closedwon": "Closed Won",
    "closedlost": "Closed Lost",
}


# ---------------------------------------------------------------------------
# Telegram chat_id helper
# ---------------------------------------------------------------------------


def _get_telegram_chat_id() -> str:
    """
    Return TELEGRAM_CHAT_ID from env.

    Chat ID discovery is handled outside this agent — set TELEGRAM_CHAT_ID
    in the environment before running. To find your chat ID, send any message
    to your bot and check: https://api.telegram.org/bot<TOKEN>/getUpdates
    """
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def _send_telegram(chat_id: str, html_message: str, parse_mode: str = "HTML") -> dict:
    """
    Send a Telegram message directly via the Bot API.

    Uses urllib (stdlib only) so the full message reaches Telegram without
    the LLM ever touching or relaying the text content.

    Returns a dict with "ok": True on success, or "error": str on failure.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"error": "TELEGRAM_BOT_TOKEN env var not set"}
    if not chat_id:
        return {"error": "chat_id is empty"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": html_message,
        "parse_mode": parse_mode,
    }).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if data.get("ok"):
                return {"ok": True}
            return {"error": data.get("description", "unknown Telegram error")}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _scan_pipeline(cycle: int, deals: list | None = None) -> dict:
    """
    Process HubSpot deals fetched by the LLM via MCP tools and store them
    in module-level state for use by detect_revenue_leaks this cycle.

    The LLM should:
      1. Call hubspot_search_deals to get open deals (skip closedwon/closedlost)
      2. For each deal call hubspot_get_contact to get the contact email
      3. Call this tool with cycle and the assembled deals array

    Each deal object must include:
      id, contact, email, stage, days_inactive (int), value (int)

    Args:
        cycle: Current cycle number from context (0 on first run).
        deals: List of HubSpot deal objects assembled by the LLM.

    Returns:
        next_cycle    — incremented cycle number
        deals_scanned — number of open deals processed
        deals_json    — JSON string of normalised deals (pass to detect_revenue_leaks)
        status        — "ok" or "no_deals"
    """
    try:
        cycle_num = int(float(cycle or 0))
    except (ValueError, TypeError):
        cycle_num = 0
    next_cycle = cycle_num + 1

    if not deals:
        print(
            f"\n[scan_pipeline] Cycle {next_cycle} — no deals provided.\n"
            "  Ensure HUBSPOT_ACCESS_TOKEN is set and hubspot_search_deals returned results."
        )
        return {
            "next_cycle": next_cycle,
            "deals_scanned": 0,
            "deals_json": "[]",
            "status": "no_deals",
        }

    # Normalise each deal — guard against LLM sending partial objects
    now = datetime.now(timezone.utc)
    normalised: list[dict] = []
    for raw in deals:
        if not isinstance(raw, dict):
            continue

        # Resolve days_inactive from real sales activity.
        # PRIMARY:  notes_last_contacted — last logged call/email/meeting (all plans).
        # BACKUP:   hs_lastmodifieddate  — last property change on the deal record.
        # Always recompute from raw date strings; do not trust the LLM's arithmetic.
        last_activity = (
            raw.get("notes_last_contacted")
            or raw.get("hs_lastmodifieddate")
        )
        if last_activity:
            try:
                dt = datetime.fromisoformat(str(last_activity).replace("Z", "+00:00"))
                days_inactive = max(0, (now - dt).days)
            except (ValueError, OverflowError):
                days_inactive = int(raw.get("days_inactive") or 0)
        else:
            days_inactive = int(raw.get("days_inactive") or 0)

        # Resolve stage — accept raw API key or already-mapped name.
        # Numeric IDs are custom pipeline stages; label them clearly.
        raw_stage = str(raw.get("stage") or raw.get("dealstage") or "unknown")
        if raw_stage in _STAGE_MAP:
            stage = _STAGE_MAP[raw_stage]
        elif raw_stage.isdigit():
            stage = f"Stage {raw_stage}"  # custom pipeline numeric ID
        else:
            stage = raw_stage.replace("_", " ").title()

        # Skip closed deals
        if raw_stage in ("closedwon", "closedlost"):
            continue

        try:
            value = int(float(raw.get("value") or raw.get("amount") or 0))
        except (ValueError, TypeError):
            value = 0

        normalised.append(
            {
                "id": str(raw.get("id", "")),
                "contact": str(
                    raw.get("contact") or raw.get("dealname") or "Unknown Deal"
                ),
                "email": str(raw.get("email", "")),
                "stage": stage,
                "days_inactive": int(days_inactive),
                "value": value,
            }
        )

    print(
        f"\n[scan_pipeline] Cycle {next_cycle} — {len(normalised)} open deal(s) from HubSpot"
    )
    for d in normalised:
        print(
            f"  • {d['contact']}  stage={d['stage']}  "
            f"inactive={d['days_inactive']}d  value=${d['value']:,}  "
            f"email={d['email'] or '—'}"
        )

    return {
        "next_cycle": next_cycle,
        "deals_scanned": len(normalised),
        "deals_json": json.dumps(normalised),
        "status": "ok",
    }


def _detect_revenue_leaks(cycle: int, deals_json: str | None = None) -> dict:
    """
    Analyse deals and detect revenue leak patterns.

    Args:
        cycle:      Current monitoring cycle (use next_cycle from scan_pipeline).
        deals_json: JSON string of deals from scan_pipeline output. REQUIRED —
                    pass the deals_json value returned by scan_pipeline so state
                    survives across event_loop node boundaries.

    Returns:
        leak_count      — total leaks detected
        severity        — low / medium / high / critical
        total_at_risk   — USD sum of at-risk deal values
        halt            — True when agent should stop looping
        leaks_json      — JSON string of leak objects for followup node
    """
    try:
        cycle_num = int(float(cycle or 0))
    except (ValueError, TypeError):
        cycle_num = 0

    # Prefer deals_json passed explicitly (survives node async context boundary).
    # Fall back to contextvar for single-session / test use.
    if deals_json is not None:
        try:
            deals = json.loads(deals_json)
        except (json.JSONDecodeError, TypeError):
            deals = []
    else:
        deals = []

    if not deals:
        _no_data_halt = cycle_num >= MAX_CYCLES
        print(
            f"[detect_revenue_leaks] Cycle {cycle_num} — no deal data, "
            f"halt={_no_data_halt}"
        )
        return {
            "cycle": cycle_num,
            "leak_count": 0,
            "severity": "low",
            "total_at_risk": 0,
            "halt": _no_data_halt,
            "leaks_json": "[]",
            "warning": "No deal data — ensure deals_json from scan_pipeline is passed",
        }

    leaks: list[dict] = []
    for deal in deals:
        days = deal.get("days_inactive", 0)
        did = deal.get("id", "")
        name = deal.get("contact", "Unknown")
        value = deal.get("value", 0)
        stage = deal.get("stage", "Unknown")
        email = deal.get("email", "")

        if days > 30:
            # No real sales activity for over 30 days — treat as ghosted.
            leaks.append(
                {
                    "type": "GHOSTED",
                    "deal_id": did,
                    "contact": name,
                    "email": email,
                    "value": value,
                    "days_inactive": days,
                    "stage": stage,
                    "recommendation": (
                        f"Send re-engagement sequence to {name} immediately — "
                        f"no sales activity for {days} days."
                    ),
                }
            )
        elif days > 14:
            # 15-30 days without activity — deal is stalling.
            leaks.append(
                {
                    "type": "STALLED",
                    "deal_id": did,
                    "contact": name,
                    "email": email,
                    "value": value,
                    "days_inactive": days,
                    "stage": stage,
                    "recommendation": (
                        f"Schedule an unblocking call with {name} — "
                        f"stuck in '{stage}' for {days} days."
                    ),
                }
            )

    total_at_risk = int(sum(leak.get("value", 0) for leak in leaks))
    ghosted_count = sum(1 for leak in leaks if leak["type"] == "GHOSTED")



    if ghosted_count >= 2 or total_at_risk >= 50_000:
        severity = "critical"
        halt = True
    elif len(leaks) >= 3 or total_at_risk >= 20_000:
        severity = "high"
        halt = False
    elif len(leaks) >= 1:
        severity = "medium"
        halt = False
    else:
        severity = "low"
        halt = cycle_num >= MAX_CYCLES

    if not halt and cycle_num >= MAX_TOTAL_CYCLES:
        halt = True

    print(
        f"[detect_revenue_leaks] Cycle {cycle_num} — "
        f"{len(leaks)} leak(s) | severity={severity} | "
        f"at_risk=${total_at_risk:,} | halt={halt}"
    )

    return {
        "cycle": cycle_num,
        "leak_count": len(leaks),
        "severity": severity,
        "total_at_risk": total_at_risk,
        "halt": halt,
        # Serialised leaks for followup node — passes across node boundary
        "leaks_json": json.dumps(leaks),
    }


def _build_telegram_alert(
    cycle: int,
    leak_count: int,
    severity: str,
    total_at_risk: int,
    leaks_json: str | None = None,
) -> dict:
    """
    Print a rich console report and build an HTML Telegram alert.

    chat_id is read from TELEGRAM_CHAT_ID env var. Set it before running.
    To find your chat ID: https://api.telegram.org/bot<TOKEN>/getUpdates

    Args:
        cycle:         Current monitoring cycle.
        leak_count:    Total leaks detected this cycle.
        severity:      Overall severity (low / medium / high / critical).
        total_at_risk: Total USD value at risk.

    Returns:
        telegram_sent  — True if the message was delivered, False otherwise
        telegram_error — error string if send failed, empty string on success
        cycle / severity / leak_count / total_at_risk — echoed for context
    """
    try:
        cycle_num = int(float(cycle or 0))
        leak_count_int = int(float(leak_count or 0))
        at_risk_int = int(float(total_at_risk or 0))
    except (ValueError, TypeError):
        cycle_num = leak_count_int = at_risk_int = 0

    sev = str(severity).lower()
    emoji = _SEVERITY_EMOJI.get(sev, "⚪")
    try:
        leaks = json.loads(leaks_json) if leaks_json else []
    except (json.JSONDecodeError, TypeError):
        leaks = []
    esc = _html.escape

    # ── Console report ──────────────────────────────────────────────────────
    border = "═" * 64
    thin = "─" * 64
    print(f"\n{border}")
    print(f"  💰  HUBSPOT REVENUE LEAK DETECTOR  ·  Cycle {cycle_num}")
    print(f"{border}")
    print(f"  Severity        : {emoji}  {sev.upper()}")
    print(f"  Leaks Detected  : {leak_count_int}")
    print(f"  Total At Risk   : ${at_risk_int:,}")
    print(f"{thin}")

    if not leaks:
        print("  ✅  Pipeline healthy — no revenue leaks detected.")
    else:
        for i, leak in enumerate(leaks, 1):
            lt = leak.get("type", "UNKNOWN")
            print(f"\n  [{i}]  {lt}")
            print(
                f"        Deal     :  {leak.get('deal_id', '')}  ({leak.get('contact', '')})"
            )
            print(f"        Stage    :  {leak.get('stage', '')}")
            print(f"        Inactive :  {leak.get('days_inactive', 0)} days")
            print(f"        Value    :  ${leak.get('value', 0):,}")
            print(f"        ➜  {leak.get('recommendation', '')}")

    print(f"\n{thin}")
    action_console = {
        "critical": "🚨  CRITICAL — Escalating to VP Sales & Finance immediately.",
        "high": "🔴  HIGH PRIORITY — Assign owners, act within 24 hours.",
        "medium": "🟡  MEDIUM — Review findings and schedule follow-ups.",
        "low": "🟢  Pipeline healthy — continue monitoring.",
    }.get(sev, "")
    print(f"  {action_console}")
    print(f"{border}\n")

    # ── Telegram HTML message ─────────────────────────────────────────────
    # Use HTML entities for emoji — LLMs mangle raw multi-plane Unicode
    # when serialising tool call arguments, corrupting the characters.
    _sev_entity = {
        "low": "&#x1F7E2;",
        "medium": "&#x1F7E1;",
        "high": "&#x1F534;",
        "critical": "&#x1F6A8;",
    }.get(sev, "")
    lines = [
        f"<b>&#x1F4B0; HubSpot Revenue Leak Detector &#x2014; Cycle {cycle_num}</b>",
        "",
        f"Severity:       {_sev_entity} <b>{sev.upper()}</b>",
        f"Leaks detected: <b>{leak_count_int}</b>",
        f"Total at risk:  <b>${at_risk_int:,}</b>",
        "",
    ]

    if not leaks:
        lines.append("&#x2705; Pipeline healthy &#x2014; no leaks found.")
    else:
        for i, leak in enumerate(leaks, 1):
            lt = esc(leak.get("type", "UNKNOWN"))
            lines.append(f"<b>[{i}] {lt}</b>")
            lines.append(
                f"  Deal    : {esc(str(leak.get('deal_id', '')))} "
                f"({esc(str(leak.get('contact', '')))}) "
            )
            lines.append(
                f"  Stage   : {esc(str(leak.get('stage', '')))}  |  "
                f"Inactive {esc(str(leak.get('days_inactive', 0)))}d"
            )
            lines.append(f"  Value   : ${leak.get('value', 0):,}")
            lines.append(f"  &#x279C; {esc(str(leak.get('recommendation', '')))}")
            lines.append("")

    action_tg = {
        "critical": "&#x1F6A8; ESCALATE to VP Sales &amp; Finance immediately.",
        "high": "&#x1F534; Assign owners &#x2014; act within 24 hours.",
        "medium": "&#x1F7E1; Review and schedule follow-ups.",
        "low": "&#x1F7E2; Continue monitoring.",
    }.get(sev, "")
    if action_tg:
        lines.append(action_tg)

    html_message = "\n".join(lines)
    chat_id = _get_telegram_chat_id()

    # ── Send directly — don't ask the LLM to relay the full message ─────────
    if not chat_id:
        print(
            "  ⚠️  Telegram alert cannot be sent — TELEGRAM_CHAT_ID not set.\n"
            "     Set TELEGRAM_CHAT_ID env var. To find your chat ID:\n"
            "     https://api.telegram.org/bot<TOKEN>/getUpdates"
        )
        tg_result = {"error": "TELEGRAM_CHAT_ID not set"}
    else:
        tg_result = _send_telegram(chat_id, html_message)
        if tg_result.get("ok"):
            print("  ✅  Telegram alert sent successfully.")
        else:
            print(f"  ⚠️  Telegram send failed: {tg_result.get('error')}")

    return {
        "cycle": cycle_num,
        "severity": sev,
        "leak_count": leak_count_int,
        "total_at_risk": at_risk_int,
        "telegram_sent": tg_result.get("ok", False),
        "telegram_error": tg_result.get("error", ""),
    }


def _prepare_followup_emails(cycle: int, leaks_json: str | None = None) -> dict:
    """
    Build follow-up email payloads for every GHOSTED contact this cycle.

    Args:
        cycle:      Current monitoring cycle.
        leaks_json: JSON string of leaks from detect_revenue_leaks output.
                    REQUIRED — pass leaks_json from context so state survives
                    across event_loop node boundaries.

    Returns:
        contacts: List of dicts — one per GHOSTED contact — each with:
          contact   — display name
          email     — recipient address
          deal_id   — HubSpot deal ID
          subject   — email subject line
          html      — full HTML email body ready to pass to gmail_create_draft
        message: Human-readable summary
    """
    try:
        cycle_num = int(float(cycle or 0))
    except (ValueError, TypeError):
        cycle_num = 0

    # Prefer leaks_json passed explicitly (survives node async context boundary).
    if leaks_json is not None:
        try:
            all_leaks = json.loads(leaks_json)
        except (json.JSONDecodeError, TypeError):
            all_leaks = []
    else:
        all_leaks = []
    ghosted = [leak for leak in all_leaks if leak.get("type") == "GHOSTED"]

    if not ghosted:
        print(
            f"\n[prepare_followup_emails] Cycle {cycle_num} — "
            "no GHOSTED contacts this cycle, nothing to send."
        )
        return {
            "contacts": [],
            "message": f"No GHOSTED contacts in Cycle {cycle_num}.",
        }

    contacts: list[dict] = []
    skipped: list[str] = []

    for leak in ghosted:
        contact = str(leak.get("contact", "there"))
        to_email = str(leak.get("email", "")).strip()
        days = int(leak.get("days_inactive", 0))
        value = int(leak.get("value", 0))
        deal_id = str(leak.get("deal_id", ""))

        if not to_email:
            skipped.append(contact)
            continue

        subject = f"Following up on our conversation — {contact}"
        html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body  {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333;
              max-width: 600px; margin: 0 auto; padding: 20px; }}
    h2    {{ color: #2c3e50; }}
    p     {{ margin: 12px 0; }}
    hr    {{ border: none; border-top: 1px solid #e0e0e0; margin: 20px 0; }}
    .meta {{ color: #888; font-size: 12px; }}
  </style>
</head>
<body>
  <h2>Following up — {_html.escape(contact)}</h2>
  <p>Hi {_html.escape(contact)},</p>
  <p>It has been <strong>{days} days</strong> since we last connected, and I
  wanted to make sure our conversation did not fall through the cracks.</p>
  <p>There is a real opportunity here that could deliver meaningful value for
  your team. Could we find <strong>15 minutes this week</strong> to reconnect?</p>
  <p>Just reply to this email and we can find a time that works.</p>
  <hr>
  <p class="meta">Deal ref: {_html.escape(deal_id)} &nbsp;|&nbsp; Value: ${value:,}</p>
</body>
</html>"""

        contacts.append(
            {
                "contact": contact,
                "email": to_email,
                "deal_id": deal_id,
                "subject": subject,
                "html": html,
            }
        )

    parts = [f"{len(contacts)} follow-up email(s) prepared for Cycle {cycle_num}"]
    if skipped:
        parts.append(
            f"{len(skipped)} skipped (no email on record): {', '.join(skipped)}"
        )
    summary = ".  ".join(parts) + "."

    print(f"\n[prepare_followup_emails] {summary}")
    for c in contacts:
        print(f"  ✉️  To: {c['contact']} <{c['email']}>")

    return {"contacts": contacts, "message": summary}


# ---------------------------------------------------------------------------
# TOOLS dict — discovered by ToolRegistry.discover_from_module()
# ---------------------------------------------------------------------------

TOOLS: dict[str, Tool] = {
    "scan_pipeline": Tool(
        name="scan_pipeline",
        description=(
            "Process and store HubSpot deals fetched via MCP tools for analysis. "
            "Call AFTER fetching deals with hubspot_search_deals and contact emails "
            "with hubspot_get_contact. Pass the assembled deals array. "
            "Returns next_cycle, deals_scanned, deals_json (JSON string — pass to detect_revenue_leaks)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {
                    "type": "integer",
                    "description": "Current cycle number from context (0 on first run).",
                },
                "deals": {
                    "type": "array",
                    "description": (
                        "Array of open HubSpot deal objects. Each must include: "
                        "id (string), contact (string — deal/company name), "
                        "email (string — primary contact email), "
                        "stage (string — deal stage name), "
                        "days_inactive (integer — days since last activity), "
                        "value (integer — deal amount in USD). "
                        "Omit closedwon and closedlost deals."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "contact": {"type": "string"},
                            "email": {"type": "string"},
                            "stage": {"type": "string"},
                            "days_inactive": {"type": "integer"},
                            "value": {"type": "integer"},
                        },
                        "required": [
                            "id",
                            "contact",
                            "stage",
                            "days_inactive",
                            "value",
                        ],
                    },
                },
            },
            "required": ["cycle"],
        },
    ),
    "detect_revenue_leaks": Tool(
        name="detect_revenue_leaks",
        description=(
            "Analyse HubSpot deals and classify revenue leak patterns: "
            "GHOSTED (21+ days silent) and STALLED (10-20 days inactive). "
            "Pass deals_json from scan_pipeline output. "
            "Returns leak_count, severity, total_at_risk, halt, and leaks_json."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {
                    "type": "integer",
                    "description": "Cycle number (use next_cycle returned by scan_pipeline).",
                },
                "deals_json": {
                    "type": "string",
                    "description": (
                        "JSON string of deals from scan_pipeline's deals_json output. "
                        "Must be passed so data survives the node async context boundary."
                    ),
                },
            },
            "required": ["cycle", "deals_json"],
        },
    ),
    "build_telegram_alert": Tool(
        name="build_telegram_alert",
        description=(
            "Print a rich console cycle report, build an HTML Telegram alert, "
            "and send it directly to Telegram (reads TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID from env automatically). "
            "Returns telegram_sent=True/False. "
            "Call AFTER detect_revenue_leaks. Do NOT call telegram_send_message separately."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {"type": "integer", "description": "Current cycle number."},
                "leak_count": {
                    "type": "integer",
                    "description": "Total leaks detected.",
                },
                "severity": {
                    "type": "string",
                    "description": "low / medium / high / critical",
                },
                "total_at_risk": {
                    "type": "integer",
                    "description": "Total USD value at risk.",
                },
                "leaks_json": {
                    "type": "string",
                    "description": (
                        "JSON string of leaks from detect_revenue_leaks's leaks_json output. "
                        "Pass verbatim so individual deal details appear in the alert body."
                    ),
                },
            },
            "required": ["cycle", "leak_count", "severity", "total_at_risk", "leaks_json"],
        },
    ),
    "prepare_followup_emails": Tool(
        name="prepare_followup_emails",
        description=(
            "Build draft email payloads for all GHOSTED contacts this cycle. "
            "Returns a contacts array — call gmail_create_draft MCP tool for each entry. "
            "Pass leaks_json from detect_revenue_leaks output so data survives the node boundary. "
            "Must be called AFTER detect_revenue_leaks."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cycle": {
                    "type": "integer",
                    "description": "Current monitoring cycle.",
                },
                "leaks_json": {
                    "type": "string",
                    "description": (
                        "JSON string of leaks from detect_revenue_leaks's leaks_json output. "
                        "Must be passed so data survives the node async context boundary."
                    ),
                },
            },
            "required": ["cycle", "leaks_json"],
        },
    ),
}


# ---------------------------------------------------------------------------
# Unified tool executor — dispatches to private handler functions
# ---------------------------------------------------------------------------

_TOOL_HANDLERS: dict[str, Any] = {
    "scan_pipeline": _scan_pipeline,
    "detect_revenue_leaks": _detect_revenue_leaks,
    "build_telegram_alert": _build_telegram_alert,
    "prepare_followup_emails": _prepare_followup_emails,
}


def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch a ToolUse to the correct handler and return a JSON ToolResult."""
    handler = _TOOL_HANDLERS.get(tool_use.name)
    if handler is None:
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
            is_error=True,
        )
    try:
        result = handler(**tool_use.input)
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps(result),
        )
    except Exception as exc:
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps({"error": str(exc)}),
            is_error=True,
        )
