# Clean imports and agent structure
from pathlib import Path
from framework.graph import EdgeSpec, EdgeCondition, Goal
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor, FunctionNode
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.runner.tool_registry import ToolRegistry
from .nodes import observe_node, notify_node
from .nodes.stop_node import stop_node


# Clean imports and agent structure
from pathlib import Path
from framework.graph import EdgeSpec, EdgeCondition, Goal
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor, FunctionNode
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.runner.tool_registry import ToolRegistry
from .nodes import observe_node, notify_node

"""
Continuous Telegram Alert Agent (Example)
Minimal continuous agent aligned with Hive templates.
"""

# ---- Goal ----
goal = Goal(
    id="continuous-telegram-alert",
    name="Continuous Telegram Alert",
    description="Minimal continuous alert example using Telegram output.",
)

# Node and edge setup
nodes = [observe_node, notify_node, stop_node]
edges = [
    EdgeSpec(
        id="observe-to-notify",
        source="observe",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="observe-to-stop",
        source="observe",
        target="stop",
        condition=EdgeCondition.CONDITIONAL,
        custom_condition="done == True",
        priority=2,
    ),
    EdgeSpec(
        id="notify-to-observe",
        source="notify",
        target="observe",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]
entry_node = "observe"
entry_points = {"start": "observe"}
loop_config = {"max_iterations": 5}

class ContinuousTelegramAlertAgent:
    def __init__(self):
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self._executor = None
        self._graph = None
        self._event_bus = None
        self._tool_registry = None

    def _build_graph(self):
        return GraphSpec(
            id="continuous-telegram-alert-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            nodes=self.nodes,
            edges=self.edges,
            conversation_mode="continuous",
            identity_prompt="You are a minimal continuous alert agent.",
            loop_config=loop_config,
        )

    def _setup(self):
        storage_path = Path.home() / ".hive" / "agents" / "continuous_telegram_alert"
        storage_path.mkdir(parents=True, exist_ok=True)
        self._event_bus = EventBus()
        self._tool_registry = ToolRegistry()
        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)
        runtime = Runtime(storage_path)
        self._graph = self._build_graph()
        tools = list(self._tool_registry.get_tools().values())
        tool_executor = self._tool_registry.get_executor()
        # Register function nodes
        from .nodes import observe_handler, notify_handler
        from .nodes.stop_node import stop_handler
        node_registry = {
            observe_node.id: FunctionNode(observe_handler),
            notify_node.id: FunctionNode(notify_handler),
            stop_node.id: FunctionNode(stop_handler),
        }
        self._executor = GraphExecutor(
            runtime=runtime,
            llm=None,
            tools=tools,
            tool_executor=tool_executor,
            event_bus=self._event_bus,
            storage_path=storage_path,
            loop_config=self._graph.loop_config,
            node_registry=node_registry,
        )

    async def run(self, context: dict) -> ExecutionResult:
        if self._executor is None:
            self._setup()
        try:
            return await self._executor.execute(
                graph=self._graph,
                goal=self.goal,
                input_data=context,
            )
        finally:
            await self.stop()

    async def start(self):
        if self._executor is None:
            self._setup()

    async def stop(self):
        self._executor = None
        self._event_bus = None
