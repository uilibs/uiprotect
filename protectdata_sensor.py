from pyunifiprotect.unifi_protect_server import UpvServer
from aiohttp import ClientSession, CookieJar
import asyncio
import json

UFP_USERNAME = "YOUR_USERNAME"
UFP_PASSWORD = "YOUR_PASSWORD"
UFP_IPADDRESS = "IP_ADDRESS_OF_UFP"
UFP_USERNAME = "briis"
UFP_PASSWORD = "QGX9P4zaLQTji7TX"
UFP_IPADDRESS = "192.168.1.1"
UFP_PORT = 443

async def devicedata():
    session = ClientSession(cookie_jar=CookieJar(unsafe=True))

    # Log in to Unifi Protect
    unifiprotect = UpvServer(
        session,
        UFP_IPADDRESS,
        UFP_PORT,
        UFP_USERNAME,
        UFP_PASSWORD,
    )

    data = await unifiprotect.update(True)
    print(json.dumps(data, indent=1))

    # Close the Session
    await session.close()

loop = asyncio.get_event_loop()
loop.run_until_complete(devicedata())
loop.close()