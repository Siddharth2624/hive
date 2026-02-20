from framework.graph import NodeSpec

notify_node = NodeSpec(
    id="notify",
    name="Notify",
    description="Send a monitoring alert and pass state through.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["iteration", "halt"],
    output_keys=["iteration", "halt"],
    tools=["send_alert"],
    system_prompt="""\
You are executing ONE step of a monitoring loop. Follow these steps in order:
1. Call send_alert EXACTLY ONCE with the 'iteration' and 'halt' values from context.
2. Call set_output with key "iteration" passing through the same iteration value as a string.
3. Call set_output with key "halt" passing through the same halt value as "true" or "false".
Do NOT call send_alert more than once. Stop immediately after step 3.
""",
)