"""Continuous Telegram Alert Agent — LLM-driven event_loop nodes."""

from framework.graph import EdgeSpec, EdgeCondition, Goal

from .config import default_config, metadata
from .nodes import observe_node, notify_node

# ---- Goal ----
goal = Goal(
    id="continuous-telegram-alert",
    name="Continuous Telegram Alert",
    description=(
        "Monitoring agent that observes a signal in a loop and sends Telegram "
        "alerts each iteration until a halt condition is met."
    ),
)

# ---- Nodes & Edges ----
nodes = [observe_node, notify_node]

edges = [
    EdgeSpec(
        id="observe-to-notify",
        source="observe",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # Loop back only when halt is not "true"
    EdgeSpec(
        id="notify-to-observe",
        source="notify",
        target="observe",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='halt != "true" and halt != True',
        priority=1,
    ),
]

entry_node = "observe"
entry_points = {"start": "observe"}
terminal_nodes = []
pause_nodes = []

__all__ = ["goal", "nodes", "edges"]
