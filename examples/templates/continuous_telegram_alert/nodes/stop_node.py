from framework.graph import NodeSpec


async def stop_handler(**kwargs):
    return {"done": True}


stop_node = NodeSpec(
    id="stop",
    name="Stop",
    description="Terminal node to gracefully stop the agent.",
    node_type="function",
    client_facing=False,
    input_keys=[],
    output_keys=["done"],
    handler=stop_handler,
)