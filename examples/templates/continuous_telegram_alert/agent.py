"""Continuous Telegram Alert Agent — uses GraphExecutor directly for function node support."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor, FunctionNode
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.core import Runtime

from .config import default_config, metadata
from .nodes import (
    observe_node, observe_handler,
    notify_node, notify_handler,
    stop_node, stop_handler,
)

# ---- Function Node Registry ----
node_registry = {
    "observe": FunctionNode(observe_handler),
    "notify":  FunctionNode(notify_handler),
    "stop":    FunctionNode(stop_handler),
}

# ---- Goal ----
goal = Goal(
    id="continuous-telegram-alert",
    name="Continuous Telegram Alert",
    description="Minimal continuous alert example using Telegram output.",
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
    EdgeSpec(
        id="notify-to-observe",
        source="notify",
        target="observe",
        condition=EdgeCondition.ON_SUCCESS,
        priority=2,  # try observe first (higher priority)
    ),
]

entry_node = "observe"
entry_points = {"start": "observe"}
terminal_nodes = []
pause_nodes = []


class ContinuousTelegramAlertAgent:
    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.terminal_nodes = terminal_nodes
        self.pause_nodes = pause_nodes
        self._executor: GraphExecutor | None = None
        self._graph: GraphSpec | None = None

    def _build_graph(self) -> GraphSpec:
        return GraphSpec(
            id="continuous-telegram-alert-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            max_steps=10,
            loop_config={"max_iterations": 20},
        )

    def _setup(self) -> None:
        storage_path = Path.home() / ".hive" / "agents" / "continuous_telegram_alert"
        storage_path.mkdir(parents=True, exist_ok=True)

        tool_registry = ToolRegistry()
        tool_executor = tool_registry.get_executor()
        tools = list(tool_registry.get_tools().values())

        self._graph = self._build_graph()

        self._executor = GraphExecutor(
            runtime=Runtime(storage_path=storage_path),
            llm=None,
            tools=tools,
            tool_executor=tool_executor,
            node_registry=node_registry,
            storage_path=storage_path,
            loop_config={"max_iterations": 20},
        )

    async def start(self) -> None:
        if self._executor is None:
            self._setup()

    async def stop(self) -> None:
        self._executor = None

    async def run(self, context: dict, session_state=None) -> ExecutionResult:
        await self.start()
        try:
            return await self._executor.execute(
                graph=self._graph,
                goal=self.goal,
                input_data=context,
            )
        finally:
            await self.stop()

    def info(self) -> dict:
        return {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "goal": {"name": self.goal.name, "description": self.goal.description},
            "nodes": [n.id for n in self.nodes],
            "edges": [e.id for e in self.edges],
            "entry_node": self.entry_node,
            "terminal_nodes": self.terminal_nodes,
        }


default_agent = ContinuousTelegramAlertAgent()

__all__ = ["goal", "nodes", "edges", "node_registry", "default_agent"]

# ---- Hive TUI compatibility ----
# TUI expects raw graph exports, not the runtime class
graph_goal = goal
graph_nodes = nodes
graph_edges = edges

goal = graph_goal
nodes = graph_nodes
edges = graph_edges
