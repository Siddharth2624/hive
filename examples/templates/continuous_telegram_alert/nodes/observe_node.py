from framework.graph.node import NodeSpec

async def observe_handler(**kwargs):
    iteration = kwargs.get("iteration", 0)
    if iteration >= 5:
        return {"done": True, "iteration": iteration}
    print("Observing signal...")
    return {"done": False, "iteration": iteration + 1}

observe_node = NodeSpec(
    id="observe",
    name="Observe",
    description="Simulate observing a signal.",
    client_facing=False,
    node_type="function",
    execution_type="function",
    function_name="observe_handler",
    handler=observe_handler,
    max_visits=5,  # Retaining max_visits as it may be relevant
)
