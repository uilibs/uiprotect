"""Unifi Protect Server Wrapper."""

import asyncio
import datetime
import enum
import json
import logging
import struct
import time
import zlib
from datetime import timezone

import aiohttp
import jwt
from aiohttp import client_exceptions

CAMERA_UPDATE_INTERVAL_SECONDS = 60
WEBSOCKET_CHECK_INTERVAL_SECONDS = 120

EMPTY_EVENT = {
    "event_start": None,
    "event_score": 0,
    "event_thumbnail": None,
    "event_heatmap": None,
    "event_on": False,
    "event_ring_on": False,
    "event_type": None,
    "event_length": 0,
    "event_object": [],
}

WS_HEADER_SIZE = 8


@enum.unique
class ProtectWSPayloadFormat(enum.Enum):
    """Websocket Payload formats."""

    JSON = 1
    UTF8String = 2
    NodeBuffer = 3


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
        self.ws_path = "ws"
        self._is_authenticated = False
        self._last_camera_update_time = 0
        self._last_websocket_check = 0
        self.access_key = None
        self.device_data = {}
        self.last_update_id = None

        self.req = session
        self.headers = None
        self.ws_session = None
        self.ws = None
        self.ws_task = None
        self._ws_subscriptions = []

    @property
    def devices(self):
        """ Returns a JSON formatted list of Devices. """
        return self.device_data

    async def update(self, force_camera_update=False) -> dict:
        """Updates the status of devices."""

        current_time = time.time()
        if (
            self.is_unifi_os
            and (current_time - WEBSOCKET_CHECK_INTERVAL_SECONDS)
            > self._last_websocket_check
        ):
            _LOGGER.debug("Checking websocket")
            self._last_websocket_check = current_time
            await self.async_connect_ws()

        camera_update = False
        if (
            force_camera_update
            or (current_time - CAMERA_UPDATE_INTERVAL_SECONDS)
            > self._last_camera_update_time
        ):
            _LOGGER.debug("Doing camera update")
            camera_update = True
            await self._get_camera_list()
            self._last_camera_update_time = current_time
        else:
            _LOGGER.debug("Skipping camera update")

        # If the websocket is connected
        # we do not need to get events
        if self.ws and not camera_update:
            _LOGGER.debug("Skipping update since websocket is active")
            return {}

        self._reset_camera_events()
        updates = await self._get_events(10)

        if camera_update:
            return self.devices
        return updates

    async def async_connect_ws(self):
        """Connect the websocket."""
        if self.ws is not None:
            return

        if self.ws_task is not None:
            try:
                self.ws_task.cancel()
                self.ws = None
            except Exception as e:
                _LOGGER.debug("Could not cancel ws_task")
        self.ws_task = asyncio.ensure_future(self._setup_websocket())

    async def async_disconnect_ws(self):
        """Disconnect the websocket."""
        if self.ws is None:
            return

        await self.ws.close()
        await self.ws_session.close()

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
        if response.status != 200:
            return
        if response.headers.get("x-csrf-token"):
            self.is_unifi_os = True
            self.api_path = "proxy/protect/api"
            self.ws_path = "proxy/protect/ws"
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
            self.headers = {
                "x-csrf-token": response.headers.get("x-csrf-token"),
                "cookie": response.headers.get("set-cookie"),
            }
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
            access_key_uri,
            headers=self.headers,
            verify_ssl=self._verify_ssl,
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
            bootstrap_uri,
            headers=self.headers,
            verify_ssl=self._verify_ssl,
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
            bootstrap_uri,
            headers=self.headers,
            verify_ssl=self._verify_ssl,
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
            bootstrap_uri,
            headers=self.headers,
            verify_ssl=self._verify_ssl,
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
                    # Get Status Light Setting
                    status_light = str(camera["ledSettings"]["isEnabled"])

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
                                    f"rtsp://{self._host}:7447/{channel['rtspAlias']}"
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
                                "status_light": status_light,
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
                        self.device_data[camera_id]["status_light"] = status_light
            else:
                raise NvrError(
                    f"Fetching Camera List failed: {response.status} - Reason: {response.reason}"
                )

    def _reset_camera_events(self) -> None:
        """Reset camera events between camera updates."""
        for camera_id in self.device_data:
            self.device_data[camera_id].update(EMPTY_EVENT)

    async def _get_events(self, lookback: int = 86400, camera=None) -> None:
        """Load the Event Log and loop through items to find motion events."""

        await self.ensureAuthenticated()

        event_start = datetime.datetime.now() - datetime.timedelta(seconds=lookback)
        event_end = datetime.datetime.now() + datetime.timedelta(seconds=10)
        start_time = int(time.mktime(event_start.timetuple())) * 1000
        end_time = int(time.mktime(event_end.timetuple())) * 1000
        event_on = False
        event_ring_on = False
        event_length = 0
        event_ring_check = datetime.datetime.now() - datetime.timedelta(seconds=3)
        event_ring_check_converted = (
            int(time.mktime(event_ring_check.timetuple())) * 1000
        )
        event_objects = None
        event_uri = f"{self._base_url}/{self.api_path}/events"
        params = {
            "end": str(end_time),
            "start": str(start_time),
        }
        if camera:
            params["cameras"] = camera
        response = await self.req.get(
            event_uri,
            params=params,
            headers=self.headers,
            verify_ssl=self._verify_ssl,
        )
        if response.status != 200:
            raise NvrError(
                f"Fetching Eventlog failed: {response.status} - Reason: {response.reason}"
            )
        events = await response.json()
        updated = {}
        for event in events:
            camera_id = event["camera"]

            if (
                event["type"] == "motion"
                or event["type"] == "ring"
                or event["type"] == "smartDetectZone"
            ):
                if event["start"]:
                    start_time = datetime.datetime.fromtimestamp(
                        int(event["start"]) / 1000
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    event_length = 0
                else:
                    start_time = None
                if event["type"] == "motion" or event["type"] == "smartDetectZone":
                    if event["end"]:
                        event_on = False
                        event_length = (float(event["end"]) / 1000) - (
                            float(event["start"]) / 1000
                        )
                        if event["type"] == "smartDetectZone":
                            event_objects = event["smartDetectTypes"]
                    else:
                        if int(event["score"]) >= self._minimum_score:
                            event_on = True
                            if event["type"] == "smartDetectZone":
                                event_objects = event["smartDetectTypes"]
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
                            _LOGGER.debug("EVENT: DOORBELL HAS RUNG IN LAST 3 SECONDS!")
                            event_ring_on = True
                        else:
                            _LOGGER.debug(
                                "EVENT: DOORBELL WAS NOT RUNG IN LAST 3 SECONDS"
                            )
                            event_ring_on = False
                    else:
                        _LOGGER.debug("EVENT: DOORBELL IS RINGING")
                        event_ring_on = True

                updated[camera_id] = self.device_data[camera_id]
                self.device_data[camera_id]["event_start"] = start_time
                self.device_data[camera_id]["event_score"] = event["score"]
                self.device_data[camera_id]["event_on"] = event_on
                self.device_data[camera_id]["event_ring_on"] = event_ring_on
                self.device_data[camera_id]["event_type"] = event["type"]
                self.device_data[camera_id]["event_length"] = event_length
                if event_objects is not None:
                    self.device_data[camera_id]["event_object"] = event_objects
                if (
                    event["thumbnail"] is not None
                ):  # Only update if there is a new Motion Event
                    self.device_data[camera_id]["event_thumbnail"] = event["thumbnail"]
                if (
                    event["heatmap"] is not None
                ):  # Only update if there is a new Motion Event
                    self.device_data[camera_id]["event_heatmap"] = event["heatmap"]
        return updated

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
            event_uri,
            params=params,
            headers=self.headers,
            verify_ssl=self._verify_ssl,
        ) as response:
            if response.status == 200:
                events = await response.json()
                return events
            else:
                raise NvrError(
                    f"Fetching Eventlog failed: {response.status} - Reason: {response.reason}"
                )

    async def get_raw_camera_info(self) -> None:
        """Return the RAW JSON data from this NVR."""

        await self.ensureAuthenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/bootstrap"
        async with self.req.get(
            bootstrap_uri,
            headers=self.headers,
            verify_ssl=self._verify_ssl,
        ) as response:
            if response.status == 200:
                json_response = await response.json()
                return json_response
            else:
                raise NvrError(
                    f"Fetching Unique ID failed: {response.status} - Reason: {response.reason}"
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

    async def get_heatmap(self, camera_id: str) -> bytes:
        """Returns the last recorded Heatmap, based on Camera ID."""

        await self.ensureAuthenticated()
        await self._get_events()

        heatmap_id = self.device_data[camera_id]["event_heatmap"]

        if heatmap_id is not None:
            img_uri = f"{self._base_url}/{self.api_path}/heatmaps/{heatmap_id}"
            params = {
                "accessKey": await self._get_api_access_key(),
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
                        f"Heatmap Request failed: {response.status} - Reason: {response.reason}"
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
            "force": "true",
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
        """Returns a Snapshot image of a recording event.
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
        """Sets the camera recoding mode to what is supplied with 'mode'.
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
        """Sets the camera infrared settings to what is supplied with 'mode'.
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

    async def set_camera_status_light(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera status light settings to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        await self.ensureAuthenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"ledSettings": {"isEnabled": mode, "blinkRate": 0}}

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self.device_data[camera_id]["status_light"] = str(mode)
                return True
            else:
                raise NvrError(
                    "Change Status Light failed: %s - Reason: %s"
                    % (response.status, response.reason)
                )

    async def set_camera_hdr_mode(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera HDR mode to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        await self.ensureAuthenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"hdrMode": mode}

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                return True
            else:
                raise NvrError(
                    "Change HDR mode failed: %s - Reason: %s"
                    % (response.status, response.reason)
                )

    async def set_camera_video_mode_highfps(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera High FPS video mode to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        highfps = "highFps" if mode == True else "default"

        await self.ensureAuthenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"videoMode": highfps}

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                return True
            else:
                raise NvrError(
                    "Change Video mode failed: %s - Reason: %s"
                    % (response.status, response.reason)
                )

    async def set_doorbell_custom_text(
        self, camera_id: str, custom_text: str, duration=None
    ) -> bool:
        """Sets a Custom Text string for the Doorbell LCD'."""

        await self.ensureAuthenticated()

        message_type = "CUSTOM_MESSAGE"

        # Truncate text to max 30 characters, as this is what is supported
        custom_text = custom_text[:30]

        # Calculate ResetAt time
        if duration is not None:
            now = datetime.datetime.now()
            now_plus_duration = now + datetime.timedelta(minutes=int(duration))
            duration = int(now_plus_duration.timestamp() * 1000)

        # resetAt is Unix timestam in the future
        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {
            "lcdMessage": {
                "type": message_type,
                "text": custom_text,
                "resetAt": duration,
            }
        }

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                return True
            else:
                raise NvrError(
                    "Setting Doorbell Custom Text failed: %s - Reason: %s"
                    % (response.status, response.reason)
                )

    async def set_doorbell_standard_text(self, custom_text: str) -> bool:
        """Sets a Standard Text string for the Doorbell LCD. *** DOES NOT WORK ***"""

        await self.ensureAuthenticated()

        message_type = "LEAVE_PACKAGE_AT_DOOR"

        # resetAt is Unix timestam in the future
        cam_uri = f"{self._base_url}/{self.api_path}/nvr"
        data = {
            "doorbellSettings": {
                "allMessages": {"type": message_type, "text": custom_text}
            }
        }

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                return True
            else:
                raise NvrError(
                    "Setting Doorbell Custom Text failed: %s - Reason: %s"
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

    async def _setup_websocket(self):
        await self.ensureAuthenticated()
        ip = self._base_url.split("://")
        url = f"wss://{ip[1]}/{self.ws_path}/updates"
        if self.last_update_id:
            url += f"?lastUpdateId={self.last_update_id}"
        if not self.ws_session:
            self.ws_session = aiohttp.ClientSession()
        _LOGGER.debug("WS connecting to: %s", url)

        self.ws = await self.ws_session.ws_connect(
            url, verify_ssl=self._verify_ssl, headers=self.headers
        )
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await self._process_ws_events(msg)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
        finally:
            _LOGGER.debug("websocket disconnected")
            self.ws = None

    def subscribe_websocket(self, ws_callback):
        """Subscribe to websocket events.

        Returns a callback that will unsubscribe.
        """

        def _unsub_ws_callback():
            self._ws_subscriptions.remove(ws_callback)

        _LOGGER.debug("Adding subscription: %s", ws_callback)
        self._ws_subscriptions.append(ws_callback)
        return _unsub_ws_callback

    async def _process_ws_events(self, msg):
        """Process websocket messages."""
        try:
            action_frame, action_frame_payload_format, position = _decode_frame(
                msg.data, 0
            )
        except Exception as ex:
            _LOGGER.exception("Error processing action frame")
            return

        if action_frame_payload_format != ProtectWSPayloadFormat.JSON:
            return

        action_json = json.loads(action_frame)
        _LOGGER.debug("Action Frame: %s", action_json)

        if (
            action_json.get("action") != "update"
            or action_json.get("modelKey") != "camera"
        ):
            return

        try:
            data_frame, data_frame_payload_format, _ = _decode_frame(msg.data, position)
        except Exception as ex:
            _LOGGER.exception("Error processing data frame")
            return

        if data_frame_payload_format != ProtectWSPayloadFormat.JSON:
            return

        data_json = json.loads(data_frame)
        _LOGGER.debug("Data Frame: %s", data_json)

        is_motion_detected = data_json.get("isMotionDetected")
        last_motion = data_json.get("lastMotion")
        last_ring = data_json.get("lastRing")

        if last_motion is None and last_ring is None:
            return

        camera_id = action_json.get("id")

        if camera_id not in self.device_data:
            return

        if last_motion is not None:
            self.device_data[camera_id]["last_motion"] = last_motion
            _LOGGER.debug("Last Motion Set: %s at %s", camera_id, last_motion)
        if last_ring is not None:
            self.device_data[camera_id]["last_ring"] = last_ring
            _LOGGER.debug("Last Ring Set: %s at %s", camera_id, last_ring)

        self.device_data[camera_id].update(EMPTY_EVENT)
        updated = await self._get_events(10, camera_id)

        if not updated:
            _LOGGER.debug(
                "Websocket triggered update but there was no event for: %s", camera_id
            )
            return

        for subscriber in self._ws_subscriptions:
            subscriber(updated)


def _decode_frame(frame, position):
    packet_type, payload_format, deflated, unknown, payload_size = struct.unpack(
        "!bbbbi", frame[position : position + WS_HEADER_SIZE]
    )
    position += WS_HEADER_SIZE
    frame = frame[position : position + payload_size]
    if deflated:
        frame = zlib.decompress(frame)
    position += payload_size
    return frame, ProtectWSPayloadFormat(payload_format), position
