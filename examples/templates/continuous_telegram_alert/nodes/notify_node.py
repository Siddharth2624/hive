from framework.graph.node import NodeSpec


async def notify_handler(**kwargs):
    print("Sending Telegram alert...")
    return kwargs.get("result", {})


notify_node = NodeSpec(
    id="notify",
    name="Notify",
    description="Send Telegram alert.",
    client_facing=False,
    node_type="function",
    execution_type="function",
    function_name="notify_handler",
    handler=notify_handler,
    input_keys=["result"],
    max_node_visits=5,
)