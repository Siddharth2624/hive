import asyncio

from framework.runner import AgentRunner


async def main():
    print("Starting Continuous Telegram Alert Agent...")
    runner = AgentRunner.load("examples/templates/continuous_telegram_alert")
    runner._setup()
    result = await runner.run(input_data={"iteration": "0"})
    print("Result:", "SUCCESS" if result.success else "FAILED")
    print("Path:", result.path)
    print("Quality:", result.execution_quality)


if __name__ == "__main__":
    asyncio.run(main())
