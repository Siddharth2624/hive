from framework.graph.node import NodeSpec


async def stop_handler(**kwargs):
    print("Stopping agent...")
    return {"done": True}


stop_node = NodeSpec(
    id="stop",
    name="Stop",
    description="Terminal node to stop the agent.",
    client_facing=False,
    node_type="function",
    execution_type="function",
    function_name="stop_handler",
    handler=stop_handler,
    max_node_visits=0,  # 0 = unlimited, so it always executes when reached
)