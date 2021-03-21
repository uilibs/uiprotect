from pyunifiprotect.unifi_protect_server import UpvServer
from aiohttp import ClientSession, CookieJar
import asyncio
import json

UFP_USERNAME = "YOUR_USERNAME"
UFP_PASSWORD = "YOUR_PASSWORD"
UFP_IPADDRESS = "IP_ADDRESS_OF_UFP"
UFP_PORT = 443
CAM_ID = "ID_OF_CAMERA"

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

    await unifiprotect.update(True)
    data = await unifiprotect.set_doorbell_chime(CAM_ID, True)
    print(data)

    # Close the Session
    await session.close()

loop = asyncio.get_event_loop()
loop.run_until_complete(raw_data())
loop.close()