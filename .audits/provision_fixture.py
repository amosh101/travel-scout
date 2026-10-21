"""Provision the audit superadmin fixture via the app's own bootstrap."""
import asyncio
from app.database import get_session_factory
from app.services.bootstrap import bootstrap_admin


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await bootstrap_admin(session)
        if result is None:
            print("bootstrap disabled (no fixture email configured)")
            return
        print("EMAIL:", result["email"])
        print("NEWLY_CREATED:", result.get("newly_created"))
        if result.get("password"):
            print("PASSWORD:", result["password"])
        else:
            print("PASSWORD: (existing user — unchanged)")


asyncio.run(main())