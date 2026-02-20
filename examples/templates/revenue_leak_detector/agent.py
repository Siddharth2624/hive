"""Revenue Leak Detector Agent — LLM-driven event_loop nodes.

Graph topology
--------------
  monitor ──► analyze ──► notify
                              │
              ◄───────────────┘  (loop while halt != true)

The agent runs 3 monitoring cycles. Severity escalates each cycle:
  Cycle 1 → medium   (ghosted prospect + stalled deal)
  Cycle 2 → high     (more ghosting + overdue invoice)
  Cycle 3 → critical (multiple GHOSTED + CHURN_RISK) → halt
"""

from framework.graph import EdgeSpec, EdgeCondition, Goal

from .config import default_config, metadata
from .nodes import monitor_node, analyze_node, notify_node

# ---- Goal ----
goal = Goal(
    id="revenue-leak-detector",
    name="Revenue Leak Detector",
    description=(
        "Autonomous business health monitor that continuously scans the CRM pipeline, "
        "detects revenue leaks (ghosted prospects, stalled deals, overdue payments, "
        "churn risk), and sends structured alerts until a critical leak threshold "
        "triggers escalation."
    ),
)

# ---- Nodes ----
nodes = [monitor_node, analyze_node, notify_node]

# ---- Edges ----
edges = [
    # monitor → analyze (always proceed to analysis after scanning)
    EdgeSpec(
        id="monitor-to-analyze",
        source="monitor",
        target="analyze",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # analyze → notify (always send alert after analysis)
    EdgeSpec(
        id="analyze-to-notify",
        source="analyze",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # notify → monitor (loop back while not halted)
    EdgeSpec(
        id="notify-to-monitor",
        source="notify",
        target="monitor",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='halt != "true" and halt != True',
        priority=1,
    ),
]

entry_node = "monitor"
entry_points = {"start": "monitor"}
terminal_nodes = []
pause_nodes = []

__all__ = ["goal", "nodes", "edges"]
