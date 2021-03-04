from pyunifiprotect.unifi_protect_server import UpvServer
from aiohttp import ClientSession, CookieJar
import asyncio
import json

UFP_USERNAME = "YOUR USERNAME"
UFP_PASSWORD = "YOUR PASSWORD"
UFP_IPADDRESS = "IP ADDRESS OF UFP"
UFP_PORT = 443

async def raw_data():
    session = ClientSession(cookie_jar=CookieJar(unsafe=True))

    # Log in to Unifi Protect
    unifiprotect = UpvServer(
        session,
        UFP_IPADDRESS,
        UFP_PORT,
        UFP_USERNAME,
        UFP_PASSWORD,
    )

    data = await unifiprotect.get_raw_device_info()
    print(json.dumps(data, indent=1))

    # Close the Session
    await session.close()

loop = asyncio.get_event_loop()
loop.run_until_complete(raw_data())
loop.close()