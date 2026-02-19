import asyncio

from .agent import ContinuousTelegramAlertAgent


async def main():
    print("Starting Continuous Telegram Alert Agent...")

    agent = ContinuousTelegramAlertAgent()

    # Minimal test context
    context = {
        "context": {
            "iteration": 0
        }
    }
    result = await agent.run(context)
    print("Execution result:", result)


if __name__ == "__main__":
    asyncio.run(main())
