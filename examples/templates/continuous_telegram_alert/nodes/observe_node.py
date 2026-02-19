from framework.graph.node import NodeSpec


async def observe_handler(**kwargs):
    # Read iteration from previous result (stored as top-level "result" key)
    prev = kwargs.get("result", {})
    iteration = prev.get("iteration", 0) if isinstance(prev, dict) else 0

    print("Observing signal...")
    new_iteration = iteration + 1
    return {
        "iteration": new_iteration,
        "halt": new_iteration >= 5,
    }


observe_node = NodeSpec(
    id="observe",
    name="Observe",
    description="Simulate observing a signal.",
    client_facing=False,
    node_type="function",
    execution_type="function",
    function_name="observe_handler",
    handler=observe_handler,
    input_keys=["result"],
    max_node_visits=5,
)