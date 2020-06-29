"""Unifi Protect Server Wrapper."""

import datetime
import logging
import time
import jwt

import aiohttp
from aiohttp import client_exceptions

CAMERA_UPDATE_INTERVAL_SECONDS = 60

EMPTY_EVENT = {
    "event_start": None,
    "event_score": 0,
    "event_thumbnail": None,
    "event_on": False,
    "event_ring_on": False,
    "event_type": None,
    "event_length": 0,
}


class Invalid(Exception):
    """Invalid return from Authorization Request."""

    pass


class NotAuthorized(Exception):
    """Wrong username and/or Password."""

    pass


class NvrError(Exception):
    """Other error."""

    pass


_LOGGER = logging.getLogger(__name__)


class UpvServer:
    """Updates device States and Attributes."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = False,
        minimum_score: int = 0,
    ):
        self._host = host
        self._port = port
        self._base_url = f"https://{host}:{port}"
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._minimum_score = minimum_score
        self.is_unifi_os = None
        self.api_path = "api"
        self._is_authenticated = False
        self._last_camera_update_time = 0
        self.access_key = None
        self.device_data = {}

        self.req = session
        self.headers = None

    @property
    def devices(self):
        """ Returns a JSON formatted list of Devices. """
        return self.device_data

    async def update(self) -> dict:
        """Updates the status of devices."""

        current_time = time.time()

        if (
            current_time - CAMERA_UPDATE_INTERVAL_SECONDS
        ) > self._last_camera_update_time:
            _LOGGER.debug("Doing camera update")
            await self._get_camera_list()
            self._last_camera_update_time = current_time
        else:
            _LOGGER.debug("Skipping camera update")

        self._reset_camera_events()
        await self._get_events(10)
        return self.devices

    async def unique_id(self):
        """Returns a Unique ID for this NVR."""
        return await self._get_unique_id()

    async def server_information(self):
        """Returns a Server Information for this NVR."""
        return await self._get_server_info()

    async def check_unifi_os(self):
        if self.is_unifi_os is not None:
            return

        response = await self.request("get", url=self._base_url, allow_redirects=False)
        if response.status == 200:
            if response.headers.get("x-csrf-token"):
                self.is_unifi_os = True
                self.api_path = "proxy/protect/api"
                self.headers = {"x-csrf-token": response.headers.get("x-csrf-token")}
            else:
                self.is_unifi_os = False
            _LOGGER.debug("Unifi OS: %s", self.is_unifi_os)

    async def ensureAuthenticated(self):
        if self.is_authenticated() is False:
            await self.authenticate()

    async def authenticate(self):
        await self.check_unifi_os()
        if self.is_unifi_os:
            url = f"{self._base_url}/api/auth/login"
            self.req.cookie_jar.clear()
        else:
            url = f"{self._base_url}/api/auth"

        auth = {
            "username": self._username,
            "password": self._password,
            "remember": True,
        }

        response = await self.request("post", url=url, json=auth)
        if self.is_unifi_os is True:
            self.headers = {"x-csrf-token": response.headers.get("x-csrf-token")}
        else:
            self.headers = {
                "Authorization": f"Bearer {response.headers.get('Authorization')}"
            }
        self._is_authenticated = True
        _LOGGER.debug("Authenticated successfully!")

    def is_authenticated(self) -> bool:
        if self._is_authenticated is True and self.is_unifi_os is True:
            # Check if token is expired.
            cookies = self.req.cookie_jar.filter_cookies(self._base_url)
            tokenCookie = cookies.get("TOKEN")
            if tokenCookie is None:
                return False
            try:
                jwt.decode(
                    tokenCookie.value,
                    options={"verify_signature": False, "verify_exp": True},
                )
            except jwt.ExpiredSignatureError:
                _LOGGER.debug("Authentication token has expired.")
                return False
            except Exception as e:
                _LOGGER.debug("Authentication token decode error: %s", e)
                return False

        return self._is_authenticated

    async def _get_api_access_key(self) -> str:
        """get API Access Key."""
        if self.is_unifi_os:
            return ""

        access_key_uri = f"{self._base_url}/{self.api_path}/auth/access-key"
        async with self.req.post(
            access_key_uri, headers=self.headers, verify_ssl=self._verify_ssl,
        ) as response:
            if response.status == 200:
                json_response = await response.json()
                return json_response["accessKey"]
            else:
                raise NvrError(
                    f"Request failed: {response.status} - Reason: {response.reason}"
                )

    async def _get_unique_id(self) -> None:
        """Get a Unique ID for this NVR."""

        await self.ensureAuthenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/bootstrap"
        async with self.req.get(
            bootstrap_uri, headers=self.headers, verify_ssl=self._verify_ssl,
        ) as response:
            if response.status == 200:
                json_response = await response.json()
                unique_id = json_response["nvr"]["name"]
                return unique_id
            else:
                raise NvrError(
                    f"Fetching Unique ID failed: {response.status} - Reason: {response.reason}"
                )

    async def _get_server_info(self) -> None:
        """Get Server Information for this NVR."""

        await self.ensureAuthenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/bootstrap"
        async with self.req.get(
            bootstrap_uri, headers=self.headers, verify_ssl=self._verify_ssl,
        ) as response:
            if response.status == 200:
                json_response = await response.json()
                return {
                    "unique_id": json_response["nvr"]["name"],
                    "server_version": json_response["nvr"]["version"],
                    "server_id": json_response["nvr"]["mac"],
                    "server_model": json_response["nvr"]["type"],
                }
            else:
                raise NvrError(
                    f"Fetching Unique ID failed: {response.status} - Reason: {response.reason}"
                )

    async def _get_camera_list(self) -> None:
        """Get a list of Cameras connected to the NVR."""

        await self.ensureAuthenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/bootstrap"
        async with self.req.get(
            bootstrap_uri, headers=self.headers, verify_ssl=self._verify_ssl,
        ) as response:
            if response.status == 200:
                json_response = await response.json()
                server_id = json_response["nvr"]["mac"]

                cameras = json_response["cameras"]

                for camera in cameras:
                    # Get if camera is online
                    if camera["state"] == "CONNECTED":
                        online = True
                    else:
                        online = False
                    # Get Recording Mode
                    recording_mode = str(camera["recordingSettings"]["mode"])
                    # Get Infrared Mode
                    ir_mode = str(camera["ispSettings"]["irLedMode"])
                    # Get the last time motion occured
                    lastmotion = (
                        None
                        if camera["lastMotion"] is None
                        else datetime.datetime.fromtimestamp(
                            int(camera["lastMotion"]) / 1000
                        ).strftime("%Y-%m-%d %H:%M:%S")
                    )
                    # Get the last time doorbell was ringing
                    lastring = (
                        None
                        if camera.get("lastRing") is None
                        else datetime.datetime.fromtimestamp(
                            int(camera["lastRing"]) / 1000
                        ).strftime("%Y-%m-%d %H:%M:%S")
                    )
                    # Get when the camera came online
                    upsince = (
                        "Offline"
                        if camera["upSince"] is None
                        else datetime.datetime.fromtimestamp(
                            int(camera["upSince"]) / 1000
                        ).strftime("%Y-%m-%d %H:%M:%S")
                    )
                    # Check if Regular Camera or Doorbell
                    device_type = (
                        "camera"
                        if "doorbell" not in str(camera["type"]).lower()
                        else "doorbell"
                    )
                    # Get Firmware Version
                    firmware_version = str(camera["firmwareVersion"])

                    if camera["id"] not in self.device_data:
                        # Add rtsp streaming url if enabled
                        rtsp = None
                        channels = camera["channels"]
                        for channel in channels:
                            if channel["isRtspEnabled"]:
                                rtsp = (
                                    "rtsp://"
                                    + str(camera["connectionHost"])
                                    + ":7447/"
                                    + str(channel["rtspAlias"])
                                )
                                break

                        item = {
                            str(camera["id"]): {
                                "name": str(camera["name"]),
                                "type": device_type,
                                "model": str(camera["type"]),
                                "mac": str(camera["mac"]),
                                "ip_address": str(camera["host"]),
                                "firmware_version": firmware_version,
                                "server_id": server_id,
                                "recording_mode": recording_mode,
                                "ir_mode": ir_mode,
                                "rtsp": rtsp,
                                "up_since": upsince,
                                "last_motion": lastmotion,
                                "last_ring": lastring,
                                "online": online,
                            }
                        }
                        self.device_data.update(item)
                    else:
                        camera_id = camera["id"]
                        self.device_data[camera_id]["last_motion"] = lastmotion
                        self.device_data[camera_id]["last_ring"] = lastring
                        self.device_data[camera_id]["online"] = online
                        self.device_data[camera_id]["up_since"] = upsince
                        self.device_data[camera_id]["recording_mode"] = recording_mode
                        self.device_data[camera_id]["ir_mode"] = ir_mode
            else:
                raise NvrError(
                    f"Fetching Camera List failed: {response.status} - Reason: {response.reason}"
                )

    def _reset_camera_events(self) -> None:
        """Reset camera events between camera updates."""
        for camera_id in self.device_data:
            self.device_data[camera_id].update(EMPTY_EVENT)

    async def _get_events(self, lookback: int = 86400) -> None:
        """Load the Event Log and loop through items to find motion events."""

        await self.ensureAuthenticated()

        event_start = datetime.datetime.now() - datetime.timedelta(seconds=lookback)
        event_end = datetime.datetime.now() + datetime.timedelta(seconds=10)
        start_time = int(time.mktime(event_start.timetuple())) * 1000
        end_time = int(time.mktime(event_end.timetuple())) * 1000
        event_on = False
        event_ring_on = False
        event_ring_check = datetime.datetime.now() - datetime.timedelta(seconds=3)
        event_ring_check_converted = (
            int(time.mktime(event_ring_check.timetuple())) * 1000
        )

        event_uri = f"{self._base_url}/{self.api_path}/events"
        params = {
            "end": str(end_time),
            "start": str(start_time),
        }
        async with self.req.get(
            event_uri, params=params, headers=self.headers, verify_ssl=self._verify_ssl,
        ) as response:
            if response.status == 200:
                events = await response.json()
                for event in events:
                    camera_id = event["camera"]

                    if event["type"] == "motion" or event["type"] == "ring":
                        if event["start"]:
                            start_time = datetime.datetime.fromtimestamp(
                                int(event["start"]) / 1000
                            ).strftime("%Y-%m-%d %H:%M:%S")
                            event_length = 0
                        else:
                            start_time = None
                        if event["type"] == "motion":
                            if event["end"]:
                                event_on = False
                                event_length = (float(event["end"]) / 1000) - (
                                    float(event["start"]) / 1000
                                )
                            else:
                                if int(event["score"]) >= self._minimum_score:
                                    event_on = True
                                else:
                                    event_on = False
                            self.device_data[camera_id]["last_motion"] = start_time
                        else:
                            self.device_data[camera_id]["last_ring"] = start_time
                            if event["end"]:
                                if (
                                    event["start"] >= event_ring_check_converted
                                    and event["end"] >= event_ring_check_converted
                                ):
                                    _LOGGER.debug(
                                        "EVENT: DOORBELL HAS RUNG IN LAST 3 SECONDS!"
                                    )
                                    event_ring_on = True
                                else:
                                    _LOGGER.debug(
                                        "EVENT: DOORBELL WAS NOT RUNG IN LAST 3 SECONDS"
                                    )
                                    event_ring_on = False
                            else:
                                _LOGGER.debug("EVENT: DOORBELL IS RINGING")
                                event_ring_on = True

                        self.device_data[camera_id]["event_start"] = start_time
                        self.device_data[camera_id]["event_score"] = event["score"]
                        self.device_data[camera_id]["event_on"] = event_on
                        self.device_data[camera_id]["event_ring_on"] = event_ring_on
                        self.device_data[camera_id]["event_type"] = event["type"]
                        self.device_data[camera_id]["event_length"] = event_length
                        if (
                            event["thumbnail"] is not None
                        ):  # Only update if there is a new Motion Event
                            self.device_data[camera_id]["event_thumbnail"] = event[
                                "thumbnail"
                            ]
            else:
                raise NvrError(
                    f"Fetching Eventlog failed: {response.status} - Reason: {response.reason}"
                )

    async def get_raw_events(self, lookback: int = 86400) -> None:
        """Load the Event Log and return the Raw Data - Used for debugging only."""

        await self.ensureAuthenticated()

        event_start = datetime.datetime.now() - datetime.timedelta(seconds=lookback)
        event_end = datetime.datetime.now() + datetime.timedelta(seconds=10)
        start_time = int(time.mktime(event_start.timetuple())) * 1000
        end_time = int(time.mktime(event_end.timetuple())) * 1000
        event_on = False
        event_ring_on = False
        event_ring_check = datetime.datetime.now() - datetime.timedelta(seconds=3)
        event_ring_check_converted = (
            int(time.mktime(event_ring_check.timetuple())) * 1000
        )

        event_uri = f"{self._base_url}/{self.api_path}/events"
        params = {
            "end": str(end_time),
            "start": str(start_time),
        }
        async with self.req.get(
            event_uri, params=params, headers=self.headers, verify_ssl=self._verify_ssl,
        ) as response:
            if response.status == 200:
                events = await response.json()
                return events
            else:
                raise NvrError(
                    f"Fetching Eventlog failed: {response.status} - Reason: {response.reason}"
                )

    async def get_thumbnail(self, camera_id: str, width: int = 640) -> bytes:
        """Returns the last recorded Thumbnail, based on Camera ID."""

        await self.ensureAuthenticated()
        await self._get_events()

        thumbnail_id = self.device_data[camera_id]["event_thumbnail"]

        if thumbnail_id is not None:
            height = float(width) / 16 * 9
            img_uri = f"{self._base_url}/{self.api_path}/thumbnails/{thumbnail_id}"
            params = {
                "accessKey": await self._get_api_access_key(),
                "h": str(height),
                "w": str(width),
            }
            async with self.req.get(
                img_uri,
                params=params,
                headers=self.headers,
                verify_ssl=self._verify_ssl,
            ) as response:
                if response.status == 200:
                    return await response.read()
                else:
                    raise NvrError(
                        f"Thumbnail Request failed: {response.status} - Reason: {response.reason}"
                    )
        return None

    async def get_snapshot_image(self, camera_id: str) -> bytes:
        """ Returns a Snapshot image of a recording event. """

        await self.ensureAuthenticated()

        access_key = await self._get_api_access_key()
        time_since = int(time.mktime(datetime.datetime.now().timetuple())) * 1000
        model_type = self.device_data[camera_id]["model"]
        if model_type.find("G4") != -1:
            image_width = "3840"
            image_height = "2160"
        else:
            image_width = "1920"
            image_height = "1080"

        img_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}/snapshot"
        params = {
            "accessKey": access_key,
            "h": image_height,
            "ts": str(time_since),
            "w": image_width,
        }
        async with self.req.get(
            img_uri, params=params, headers=self.headers, verify_ssl=self._verify_ssl
        ) as response:
            if response.status == 200:
                return await response.read()
            else:
                _LOGGER.warning(
                    f"Error Code: {response.status} - Error Status: {response.reason}"
                )
                return None

    async def get_snapshot_image_direct(self, camera_id: str) -> bytes:
        """ Returns a Snapshot image of a recording event. 
            This function will only work if Anonymous Snapshots
            are enabled on the Camera.
        """
        ip_address = self.device_data[camera_id]["ip_address"]

        img_uri = f"http://{ip_address}/snap.jpeg"
        async with self.req.get(img_uri) as response:
            if response.status == 200:
                return await response.read()
            else:
                raise NvrError(
                    f"Direct Snapshot failed: {response.status} - Reason: {response.reason}"
                )

    async def set_camera_recording(self, camera_id: str, mode: str) -> bool:
        """ Sets the camera recoding mode to what is supplied with 'mode'.
            Valid inputs for mode: never, motion, always
        """

        await self.ensureAuthenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {
            "recordingSettings": {
                "mode": mode,
                "prePaddingSecs": 2,
                "postPaddingSecs": 2,
                "minMotionEventTrigger": 1000,
                "enablePirTimelapse": False,
            }
        }

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self.device_data[camera_id]["recording_mode"] = mode
                return True
            else:
                raise NvrError(
                    f"Set Recording Mode failed: {response.status} - Reason: {response.reason}"
                )

    async def set_camera_ir(self, camera_id: str, mode: str) -> bool:
        """ Sets the camera infrared settings to what is supplied with 'mode'.
            Valid inputs for mode: auto, on, autoFilterOnly
        """

        await self.ensureAuthenticated()

        if mode == "led_off":
            mode = "autoFilterOnly"
        elif mode == "always_on":
            mode = "on"
        elif mode == "always_off":
            mode = "off"

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"ispSettings": {"irLedMode": mode, "irLedLevel": 255}}

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self.device_data[camera_id]["ir_mode"] = mode
                return True
            else:
                raise NvrError(
                    "Set IR Mode failed: %s - Reason: %s"
                    % (response.status, response.reason)
                )

    async def request(self, method, url, json=None, **kwargs):
        """Make a request to the API."""

        _LOGGER.debug("Request url: %s", url)

        try:
            async with self.req.request(
                method,
                url,
                verify_ssl=self._verify_ssl,
                json=json,
                headers=self.headers,
                **kwargs,
            ) as res:
                _LOGGER.debug("%s %s %s", res.status, res.content_type, res)

                if res.status in (401, 403):
                    raise NotAuthorized(
                        f"Unifi Protect reported authorization failure on request: {url} received {res.status}"
                    )

                if res.status == 404:
                    raise NvrError(f"Call {url} received 404 Not Found")

                return res

        except client_exceptions.ClientError as err:
            raise NvrError(f"Error requesting data from {self._host}: {err}") from None
