"""Runtime configuration for Continuous Telegram Alert Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Continuous Telegram Alert Agent"
    version: str = "1.0.0"
    description: str = (
        "Minimal continuous alert agent that observes a signal in a loop "
        "and sends Telegram notifications until a halt condition is met."
    )
    intro_message: str = (
        "Continuous Telegram Alert Agent is running. "
        "Observing signal and sending alerts..."
    )


metadata = AgentMetadata()