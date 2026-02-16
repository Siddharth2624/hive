from framework.graph.node import NodeSpec

async def stop_handler(**kwargs):
    print("Stopping agent...")

stop_node = NodeSpec(
    id="stop",
    name="Stop",
    description="Terminal node to stop the agent.",
    client_facing=False,
    node_type="function",
    execution_type="function",
    function_name="stop_handler",
    handler=stop_handler,
)
