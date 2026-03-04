"""Smoke test: send a message through the handler and print the response."""

import asyncio
import logging
import os

logging.disable(logging.CRITICAL)

from dotenv import load_dotenv

load_dotenv()

from handler.services import call_agent_sync  # noqa: E402

COMPANY_ID = os.getenv("SPICY_DEFAULT_COMPANY_ID")
USER_ID = os.getenv("SPICY_DEFAULT_USER_ID")
MESSAGE = "Hola, busca contactos con nombre Juan"


async def main():
    user_id = f"{COMPANY_ID}:{USER_ID}"

    print(f"[message sent] {MESSAGE}")

    response = await call_agent_sync(user_id, MESSAGE)

    print("[success]")
    print("[message received]")
    print(response)


if __name__ == "__main__":
    asyncio.run(main())
