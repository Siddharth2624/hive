"""
Revenue Leak Detector — Custom Tools

Scans a CRM / invoice / support pipeline each cycle and detects four
revenue-leak patterns:

  GHOSTED         — prospect silent for 21+ days
  STALLED         — deal stuck in same stage for 10-20 days
  OVERDUE_PAYMENT — invoice unpaid past due date
  CHURN_RISK      — 3+ unresolved support escalations

Telegram delivery
-----------------
Set two environment variables to send real alerts to Telegram:

  TELEGRAM_BOT_TOKEN  — token from @BotFather  (e.g. 7123456789:AAF...)
  TELEGRAM_CHAT_ID    — your chat / group / channel ID (e.g. -1001234567890)

When these are absent the agent falls back to console output so it runs
fully offline without any credentials.
"""

import os


# ---------------------------------------------------------------------------
# Minimal @tool decorator (framework convention)
# ---------------------------------------------------------------------------

def tool(func):
    """Marks a function for auto-discovery by ToolRegistry."""
    func._tool_metadata = {"name": func.__name__}
    return func


# ---------------------------------------------------------------------------
# Simulated CRM / ERP / Support database — one snapshot per monitoring cycle
# ---------------------------------------------------------------------------

_PIPELINE_DB: dict = {
    1: {
        "deals": [
            {"id": "DEAL-001", "contact": "Acme Corp",     "stage": "Proposal Sent",  "days_inactive": 7,  "value": 12000},
            {"id": "DEAL-002", "contact": "Beta Ltd",      "stage": "Demo Scheduled", "days_inactive": 2,  "value": 8500},
            {"id": "DEAL-003", "contact": "Gamma Inc",     "stage": "Negotiation",    "days_inactive": 14, "value": 25000},
            {"id": "DEAL-004", "contact": "Delta Co",      "stage": "Proposal Sent",  "days_inactive": 5,  "value": 5000},
            {"id": "DEAL-005", "contact": "Epsilon LLC",   "stage": "Follow-up",      "days_inactive": 21, "value": 18000},
        ],
        "overdue_payments": [],
        "support_escalations": 0,
    },
    2: {
        "deals": [
            {"id": "DEAL-001", "contact": "Acme Corp",     "stage": "Proposal Sent",  "days_inactive": 12, "value": 12000},
            {"id": "DEAL-003", "contact": "Gamma Inc",     "stage": "Negotiation",    "days_inactive": 19, "value": 25000},
            {"id": "DEAL-005", "contact": "Epsilon LLC",   "stage": "Follow-up",      "days_inactive": 26, "value": 18000},
            {"id": "DEAL-006", "contact": "Zeta Partners", "stage": "Closed Won",     "days_inactive": 0,  "value": 31000},
        ],
        "overdue_payments": [
            {"id": "INV-2024-089", "client": "Eta Systems", "amount": 7200, "days_overdue": 18},
        ],
        "support_escalations": 2,
    },
    3: {
        "deals": [
            {"id": "DEAL-001", "contact": "Acme Corp",     "stage": "Proposal Sent",  "days_inactive": 19, "value": 12000},
            {"id": "DEAL-003", "contact": "Gamma Inc",     "stage": "Negotiation",    "days_inactive": 26, "value": 25000},
            {"id": "DEAL-005", "contact": "Epsilon LLC",   "stage": "Ghosted",        "days_inactive": 33, "value": 18000},
            {"id": "DEAL-007", "contact": "Theta Ventures","stage": "Proposal Sent",  "days_inactive": 11, "value": 9500},
        ],
        "overdue_payments": [
            {"id": "INV-2024-089", "client": "Eta Systems", "amount": 7200,  "days_overdue": 25},
            {"id": "INV-2024-091", "client": "Iota Corp",   "amount": 4500,  "days_overdue": 31},
        ],
        "support_escalations": 5,
    },
}

# Shared in-process state — survives across node calls within the same run
_CURRENT_CYCLE_DATA: dict = {}
_CURRENT_LEAKS: list = []


# ---------------------------------------------------------------------------
# Tool 1 — scan_pipeline
# ---------------------------------------------------------------------------

@tool
def scan_pipeline(cycle: int) -> dict:
    """
    Scan the CRM pipeline for the next monitoring cycle.

    Simulates polling your CRM, email platform, invoice system, and support
    queue. Increments the cycle counter and loads a fresh deal snapshot.

    Args:
        cycle: Current cycle number from context (0 on first run).

    Returns:
        next_cycle      — incremented cycle number
        deals_scanned   — number of open deals found
        overdue_invoices — number of overdue invoices
        support_escalations — open support tickets needing action
    """
    global _CURRENT_CYCLE_DATA

    next_cycle = int(cycle) + 1
    data = _PIPELINE_DB.get(next_cycle, _PIPELINE_DB[3])
    _CURRENT_CYCLE_DATA = data

    print(
        f"\n[scan_pipeline] Cycle {next_cycle} — "
        f"{len(data['deals'])} deals | "
        f"{len(data['overdue_payments'])} overdue invoices | "
        f"{data['support_escalations']} escalations"
    )

    return {
        "next_cycle": next_cycle,
        "deals_scanned": len(data["deals"]),
        "overdue_invoices": len(data["overdue_payments"]),
        "support_escalations": data["support_escalations"],
    }


# ---------------------------------------------------------------------------
# Tool 2 — detect_revenue_leaks
# ---------------------------------------------------------------------------

@tool
def detect_revenue_leaks(cycle: int) -> dict:
    """
    Analyse the latest pipeline snapshot and detect revenue leak patterns.

    Leak types:
      GHOSTED         — prospect silent for 21+ days (deal still open)
      STALLED         — deal inactive 10-20 days, stuck in same stage
      OVERDUE_PAYMENT — invoice unpaid after due date
      CHURN_RISK      — 3+ unresolved support escalations

    Args:
        cycle: Current monitoring cycle (for report labelling).

    Returns:
        leak_count      — total number of leaks found
        severity        — overall severity (low / medium / high / critical)
        total_at_risk   — USD value at risk across all leaks
        halt            — True when severity reaches critical
    """
    global _CURRENT_LEAKS

    data = _CURRENT_CYCLE_DATA
    leaks: list[dict] = []

    # ---- Deal-level leak detection ----
    for deal in data.get("deals", []):
        days = deal.get("days_inactive", 0)
        if days >= 21:
            leaks.append({
                "type": "GHOSTED",
                "deal_id": deal["id"],
                "contact": deal["contact"],
                "value": deal["value"],
                "days_inactive": days,
                "stage": deal["stage"],
                "recommendation": (
                    f"Send re-engagement sequence to {deal['contact']} immediately. "
                    f"Deal has been silent for {days} days."
                ),
            })
        elif days >= 10:
            leaks.append({
                "type": "STALLED",
                "deal_id": deal["id"],
                "contact": deal["contact"],
                "value": deal["value"],
                "days_inactive": days,
                "stage": deal["stage"],
                "recommendation": (
                    f"Schedule an unblocking call with {deal['contact']} — "
                    f"stuck in '{deal['stage']}' for {days} days."
                ),
            })

    # ---- Invoice-level leak detection ----
    for payment in data.get("overdue_payments", []):
        leaks.append({
            "type": "OVERDUE_PAYMENT",
            "invoice_id": payment["id"],
            "client": payment["client"],
            "amount": payment["amount"],
            "days_overdue": payment["days_overdue"],
            "recommendation": (
                f"Escalate {payment['id']} (${payment['amount']:,}) to Finance — "
                f"{payment['days_overdue']} days overdue."
            ),
        })

    # ---- Support escalation risk ----
    escalations = data.get("support_escalations", 0)
    if escalations >= 3:
        leaks.append({
            "type": "CHURN_RISK",
            "escalations": escalations,
            "value": 0,
            "recommendation": (
                f"Assign a Senior CSM immediately: {escalations} open support "
                f"escalations — high churn risk."
            ),
        })

    _CURRENT_LEAKS = leaks

    # ---- Severity calculation ----
    total_at_risk = sum(l.get("value", l.get("amount", 0)) for l in leaks)
    critical_signals = [l for l in leaks if l["type"] in ("GHOSTED", "CHURN_RISK")]

    if len(critical_signals) >= 2 or total_at_risk >= 50000:
        severity = "critical"
        halt = True
    elif len(leaks) >= 3 or total_at_risk >= 20000:
        severity = "high"
        halt = False
    elif len(leaks) >= 1:
        severity = "medium"
        halt = False
    else:
        severity = "low"
        halt = False

    print(
        f"[detect_revenue_leaks] Cycle {cycle} — "
        f"{len(leaks)} leaks | severity={severity} | at_risk=${total_at_risk:,} | halt={halt}"
    )

    return {
        "cycle": int(cycle),
        "leak_count": len(leaks),
        "severity": severity,
        "total_at_risk": total_at_risk,
        "halt": halt,
    }


# ---------------------------------------------------------------------------
# Telegram delivery helper
# ---------------------------------------------------------------------------

def _send_telegram(text: str) -> dict:
    """
    Send *text* to Telegram if TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set.

    Returns a dict describing what happened:
      {"telegram": "sent",   "message_id": <int>}   — real message delivered
      {"telegram": "skipped","reason": "<why>"}      — env vars missing / disabled
      {"telegram": "error",  "detail": "<message>"}  — API call failed
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()

    if not bot_token or not chat_id:
        missing = []
        if not bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        return {
            "telegram": "skipped",
            "reason": f"env vars not set: {', '.join(missing)}",
        }

    try:
        import httpx  # already in the workspace venv via aden_tools
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15.0,
        )
        data = resp.json()
        if data.get("ok"):
            return {"telegram": "sent", "message_id": data["result"]["message_id"]}
        return {"telegram": "error", "detail": data.get("description", str(data))}
    except Exception as exc:
        return {"telegram": "error", "detail": str(exc)}


def _build_telegram_message(
    cycle: int,
    severity: str,
    leak_count: int,
    total_at_risk: int,
    leaks: list,
) -> str:
    """Build an HTML-formatted Telegram message from the current leak report."""
    sev = str(severity).lower()
    emoji = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🚨"}.get(sev, "⚪")

    lines = [
        f"<b>💰 Revenue Leak Detector — Cycle {cycle}</b>",
        "",
        f"Severity:       {emoji} <b>{sev.upper()}</b>",
        f"Leaks detected: <b>{int(leak_count)}</b>",
        f"Total at risk:  <b>${int(total_at_risk):,}</b>",
        "",
    ]

    if not leaks:
        lines.append("✅ Pipeline healthy — no leaks found.")
    else:
        for i, leak in enumerate(leaks, 1):
            t = leak.get("type", "UNKNOWN")
            lines.append(f"<b>[{i}] {t}</b>")
            if t in ("GHOSTED", "STALLED"):
                lines.append(f"  Deal    : {leak.get('deal_id')} ({leak.get('contact')})")
                lines.append(f"  Stage   : {leak.get('stage')}  |  Inactive {leak.get('days_inactive')}d")
                lines.append(f"  Value   : ${leak.get('value', 0):,}")
            elif t == "OVERDUE_PAYMENT":
                lines.append(f"  Invoice : {leak.get('invoice_id')} ({leak.get('client')})")
                lines.append(f"  Amount  : ${leak.get('amount', 0):,}  |  {leak.get('days_overdue')}d overdue")
            elif t == "CHURN_RISK":
                lines.append(f"  Open escalations: {leak.get('escalations')}")
            lines.append(f"  ➜ {leak.get('recommendation')}")
            lines.append("")

    action = {
        "critical": "🚨 ESCALATE to VP Sales &amp; Finance immediately.",
        "high":     "🔴 Assign owners — act within 24 hours.",
        "medium":   "🟡 Review and schedule follow-ups.",
        "low":      "🟢 Continue monitoring.",
    }.get(sev, "")
    if action:
        lines.append(action)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3 — send_revenue_alert
# ---------------------------------------------------------------------------

@tool
def send_revenue_alert(cycle: int, leak_count: int, severity: str, total_at_risk: int) -> dict:
    """
    Send a formatted revenue leak alert to the operations team.

    Prints a full structured report to the console AND — when
    TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set in the environment —
    delivers the same alert to a real Telegram chat/group.

    How to enable Telegram:
      1. Message @BotFather on Telegram → /newbot → copy the token
      2. Add the bot to your group, or DM it and visit:
         https://api.telegram.org/bot<TOKEN>/getUpdates  to find your chat_id
      3. Export the variables before running:
           export TELEGRAM_BOT_TOKEN="7123456789:AAF..."
           export TELEGRAM_CHAT_ID="-1001234567890"

    Args:
        cycle:          Current monitoring cycle number.
        leak_count:     Number of leaks found this cycle.
        severity:       Overall severity (low / medium / high / critical).
        total_at_risk:  Total USD value at risk this cycle.

    Returns:
        Confirmation dict including telegram delivery status.
    """
    sev = str(severity).lower()
    severity_emoji = {
        "low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🚨",
    }.get(sev, "⚪")

    leaks = _CURRENT_LEAKS

    # ---- Console report (always printed) ----
    border = "═" * 64
    thin   = "─" * 64

    print(f"\n{border}")
    print(f"  💰  REVENUE LEAK DETECTOR  ·  Cycle {cycle} Report")
    print(f"{border}")
    print(f"  Severity        : {severity_emoji}  {sev.upper()}")
    print(f"  Leaks Detected  : {int(leak_count)}")
    print(f"  Total At Risk   : ${int(total_at_risk):,}")
    print(f"{thin}")

    if not leaks:
        print("  ✅  Pipeline healthy — no revenue leaks detected.")
    else:
        for i, leak in enumerate(leaks, 1):
            leak_type = leak.get("type", "UNKNOWN")
            print(f"\n  [{i}]  {leak_type}")
            if leak_type in ("GHOSTED", "STALLED"):
                print(f"        Deal     :  {leak.get('deal_id')}  ({leak.get('contact')})")
                print(f"        Stage    :  {leak.get('stage')}")
                print(f"        Inactive :  {leak.get('days_inactive')} days")
                print(f"        Value    :  ${leak.get('value', 0):,}")
            elif leak_type == "OVERDUE_PAYMENT":
                print(f"        Invoice  :  {leak.get('invoice_id')}  ({leak.get('client')})")
                print(f"        Amount   :  ${leak.get('amount', 0):,}")
                print(f"        Overdue  :  {leak.get('days_overdue')} days")
            elif leak_type == "CHURN_RISK":
                print(f"        Open Escalations :  {leak.get('escalations')}")
            print(f"        ➜  {leak.get('recommendation')}")

    print(f"\n{thin}")
    if sev == "critical":
        print(f"  🚨  CRITICAL — Escalating to VP Sales & Finance immediately.")
        print(f"      Immediate action required across {int(leak_count)} revenue risks.")
    elif sev == "high":
        print(f"  🔴  HIGH PRIORITY — Assign owners and act within 24 hours.")
    elif sev == "medium":
        print(f"  🟡  MEDIUM — Review findings and schedule follow-ups.")
    else:
        print(f"  🟢  Pipeline healthy — continue monitoring.")
    print(f"{border}\n")

    # ---- Real Telegram delivery ----
    tg_message = _build_telegram_message(
        cycle=int(cycle),
        severity=severity,
        leak_count=int(leak_count),
        total_at_risk=int(total_at_risk),
        leaks=leaks,
    )
    tg_result = _send_telegram(tg_message)

    if tg_result["telegram"] == "sent":
        print(f"  ✅  Telegram alert sent (message_id={tg_result['message_id']})")
    elif tg_result["telegram"] == "skipped":
        print(f"  ℹ️   Telegram skipped — {tg_result['reason']}")
        print(f"       Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to enable real alerts.")
    else:
        print(f"  ⚠️   Telegram delivery failed: {tg_result.get('detail')}")

    return {
        "sent": True,
        "cycle": int(cycle),
        "severity": severity,
        "leaks_reported": int(leak_count),
        "total_at_risk_usd": int(total_at_risk),
        "telegram": tg_result,
    }
