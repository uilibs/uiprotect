"""Unifi Protect Server Wrapper."""

import asyncio
import datetime
import json as pjson
import logging
import time

import aiohttp
import jwt
from aiohttp import client_exceptions

from .unifi_data import (
    EVENT_MOTION,
    EVENT_RING,
    EVENT_SMART_DETECT_ZONE,
    PROCESSED_EVENT_EMPTY,
    ProtectWSPayloadFormat,
    decode_ws_frame,
    process_camera,
    process_event,
)

CAMERA_UPDATE_INTERVAL_SECONDS = 60
WEBSOCKET_CHECK_INTERVAL_SECONDS = 120


class Invalid(Exception):
    """Invalid return from Authorization Request."""


class NotAuthorized(Exception):
    """Wrong username and/or Password."""


class NvrError(Exception):
    """Other error."""


_LOGGER = logging.getLogger(__name__)


class UpvServer:  # pylint: disable=too-many-public-methods, too-many-instance-attributes
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
        self._motion_start_time = {}
        self.last_update_id = None

        self.req = session
        self.headers = None
        self.ws_session = None
        self.ws_connection = None
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
        if self.ws_connection and not camera_update:
            _LOGGER.debug("Skipping update since websocket is active")
            return {}

        self._reset_camera_events()
        updates = await self._get_events(lookback=10)

        if camera_update:
            return self.devices
        return updates

    async def async_connect_ws(self):
        """Connect the websocket."""
        if self.ws_connection is not None:
            return

        if self.ws_task is not None:
            try:
                self.ws_task.cancel()
                self.ws_connection = None
            except Exception:
                _LOGGER.exception("Could not cancel ws_task")
        self.ws_task = asyncio.ensure_future(self._setup_websocket())

    async def async_disconnect_ws(self):
        """Disconnect the websocket."""
        if self.ws_connection is None:
            return

        await self.ws_connection.close()
        await self.ws_session.close()

    async def unique_id(self):
        """Returns a Unique ID for this NVR."""
        return await self._get_unique_id()

    async def server_information(self):
        """Returns a Server Information for this NVR."""
        return await self._get_server_info()

    async def check_unifi_os(self):
        """Check to see if the device is running unifi os."""
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

    async def ensure_authenticated(self):
        """Ensure we are authenticated."""
        if self.is_authenticated() is False:
            await self.authenticate()

    async def authenticate(self):
        """Authenticate and get a token."""
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
        """Check to see if we are already authenticated."""
        if self._is_authenticated is True and self.is_unifi_os is True:
            # Check if token is expired.
            cookies = self.req.cookie_jar.filter_cookies(self._base_url)
            token_cookie = cookies.get("TOKEN")
            if token_cookie is None:
                return False
            try:
                jwt.decode(
                    token_cookie.value,
                    options={"verify_signature": False, "verify_exp": True},
                )
            except jwt.ExpiredSignatureError:
                _LOGGER.debug("Authentication token has expired.")
                return False
            except Exception as broad_ex:
                _LOGGER.debug("Authentication token decode error: %s", broad_ex)
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
            raise NvrError(
                f"Request failed: {response.status} - Reason: {response.reason}"
            )

    async def _get_unique_id(self) -> None:
        """Get a Unique ID for this NVR."""

        await self.ensure_authenticated()

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
            raise NvrError(
                f"Fetching Unique ID failed: {response.status} - Reason: {response.reason}"
            )

    async def _get_server_info(self) -> None:
        """Get Server Information for this NVR."""

        await self.ensure_authenticated()

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
                    "unifios": self.is_unifi_os,
                }
            raise NvrError(
                f"Fetching Unique ID failed: {response.status} - Reason: {response.reason}"
            )

    async def _get_camera_list(self) -> None:
        """Get a list of Cameras connected to the NVR."""

        await self.ensure_authenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/bootstrap"
        response = await self.req.get(
            bootstrap_uri,
            headers=self.headers,
            verify_ssl=self._verify_ssl,
        )
        if response.status != 200:
            raise NvrError(
                f"Fetching Camera List failed: {response.status} - Reason: {response.reason}"
            )
        json_response = await response.json()
        server_id = json_response["nvr"]["mac"]
        for camera in json_response["cameras"]:
            procesed_update = process_camera(server_id, self._host, camera)
            camera_id = str(camera["id"])

            if camera_id in self.device_data:
                self.device_data[camera_id].update(procesed_update)
            else:
                self.device_data[camera_id] = procesed_update

    def _reset_camera_events(self) -> None:
        """Reset camera events between camera updates."""
        for camera_id in self.device_data:
            self.device_data[camera_id].update(PROCESSED_EVENT_EMPTY)

    async def _get_events(
        self, lookback: int = 86400, camera=None, start_time=None, end_time=None
    ) -> None:
        """Load the Event Log and loop through items to find motion events."""

        await self.ensure_authenticated()

        now = int(time.time() * 1000)
        if start_time is None:
            start_time = now - (lookback * 1000)
        if end_time is None:
            end_time = now + 10000
        event_ring_check_converted = now - 3000

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

        updated = {}
        for event in await response.json():
            if event["type"] not in (EVENT_MOTION, EVENT_RING, EVENT_SMART_DETECT_ZONE):
                continue

            camera_id = event["camera"]
            proccessed_event = process_event(
                event, self._minimum_score, event_ring_check_converted
            )
            self.device_data[camera_id].update(proccessed_event)
            updated[camera_id] = self.device_data[camera_id]

        return updated

    async def get_raw_events(self, lookback: int = 86400) -> None:
        """Load the Event Log and return the Raw Data - Used for debugging only."""

        await self.ensure_authenticated()

        event_start = datetime.datetime.now() - datetime.timedelta(seconds=lookback)
        event_end = datetime.datetime.now() + datetime.timedelta(seconds=10)
        start_time = int(time.mktime(event_start.timetuple())) * 1000
        end_time = int(time.mktime(event_end.timetuple())) * 1000

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
            if response.status != 200:
                raise NvrError(
                    f"Fetching Eventlog failed: {response.status} - Reason: {response.reason}"
                )
            return await response.json()

    async def get_raw_camera_info(self) -> None:
        """Return the RAW JSON data from this NVR."""

        await self.ensure_authenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/bootstrap"
        async with self.req.get(
            bootstrap_uri,
            headers=self.headers,
            verify_ssl=self._verify_ssl,
        ) as response:
            if response.status != 200:
                raise NvrError(
                    f"Fetching Unique ID failed: {response.status} - Reason: {response.reason}"
                )
            return await response.json()

    async def get_thumbnail(self, camera_id: str, width: int = 640) -> bytes:
        """Returns the last recorded Thumbnail, based on Camera ID."""

        await self.ensure_authenticated()
        await self._get_events()

        thumbnail_id = self.device_data[camera_id]["event_thumbnail"]

        if thumbnail_id is None:
            return None
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
            if response.status != 200:
                raise NvrError(
                    f"Thumbnail Request failed: {response.status} - Reason: {response.reason}"
                )
            return await response.read()

    async def get_heatmap(self, camera_id: str) -> bytes:
        """Returns the last recorded Heatmap, based on Camera ID."""

        await self.ensure_authenticated()
        await self._get_events()

        heatmap_id = self.device_data[camera_id]["event_heatmap"]

        if heatmap_id is None:
            return None

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
            if response.status != 200:
                raise NvrError(
                    f"Heatmap Request failed: {response.status} - Reason: {response.reason}"
                )
            return await response.read()

    async def get_snapshot_image(self, camera_id: str) -> bytes:
        """ Returns a Snapshot image of a recording event. """

        await self.ensure_authenticated()

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
            _LOGGER.warning(
                "Error Code: %s - Error Status: %s", response.status, response.reason
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
            raise NvrError(
                f"Direct Snapshot failed: {response.status} - Reason: {response.reason}"
            )

    async def set_camera_recording(self, camera_id: str, mode: str) -> bool:
        """Sets the camera recoding mode to what is supplied with 'mode'.
        Valid inputs for mode: never, motion, always
        """

        await self.ensure_authenticated()

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
            raise NvrError(
                f"Set Recording Mode failed: {response.status} - Reason: {response.reason}"
            )

    async def set_camera_ir(self, camera_id: str, mode: str) -> bool:
        """Sets the camera infrared settings to what is supplied with 'mode'.
        Valid inputs for mode: auto, on, autoFilterOnly
        """

        await self.ensure_authenticated()

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
            raise NvrError(
                "Set IR Mode failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_camera_status_light(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera status light settings to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        await self.ensure_authenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"ledSettings": {"isEnabled": mode, "blinkRate": 0}}

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self.device_data[camera_id]["status_light"] = str(mode)
                return True
            raise NvrError(
                "Change Status Light failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_camera_hdr_mode(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera HDR mode to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        await self.ensure_authenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"hdrMode": mode}

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self.device_data[camera_id]["hdr_mode"] = mode
                return True
            raise NvrError(
                "Change HDR mode failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_camera_video_mode_highfps(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera High FPS video mode to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        highfps = "highFps" if mode is True else "default"

        await self.ensure_authenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"videoMode": highfps}

        async with self.req.patch(
            cam_uri, headers=self.headers, verify_ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self.device_data[camera_id]["video_mode"] = highfps
                return True
            raise NvrError(
                "Change Video mode failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_doorbell_custom_text(
        self, camera_id: str, custom_text: str, duration=None
    ) -> bool:
        """Sets a Custom Text string for the Doorbell LCD'."""

        await self.ensure_authenticated()

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
            raise NvrError(
                "Setting Doorbell Custom Text failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_doorbell_standard_text(self, custom_text: str) -> bool:
        """Sets a Standard Text string for the Doorbell LCD. *** DOES NOT WORK ***"""

        await self.ensure_authenticated()

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
        await self.ensure_authenticated()
        ip_address = self._base_url.split("://")
        url = f"wss://{ip_address[1]}/{self.ws_path}/updates"
        if self.last_update_id:
            url += f"?lastUpdateId={self.last_update_id}"
        if not self.ws_session:
            self.ws_session = aiohttp.ClientSession()
        _LOGGER.debug("WS connecting to: %s", url)

        self.ws_connection = await self.ws_session.ws_connect(
            url, verify_ssl=self._verify_ssl, headers=self.headers
        )
        try:
            async for msg in self.ws_connection:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await self._process_ws_events(msg)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
        finally:
            _LOGGER.debug("websocket disconnected")
            self.ws_connection = None

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
            action_frame, action_frame_payload_format, position = decode_ws_frame(
                msg.data, 0
            )
        except Exception:
            _LOGGER.exception("Error processing action frame")
            return

        if action_frame_payload_format != ProtectWSPayloadFormat.JSON:
            return

        action_json = pjson.loads(action_frame)
        _LOGGER.debug("Action Frame: %s", action_json)

        if (
            action_json.get("action") != "update"
            or action_json.get("modelKey") != "camera"
        ):
            return

        try:
            data_frame, data_frame_payload_format, _ = decode_ws_frame(
                msg.data, position
            )
        except Exception:
            _LOGGER.exception("Error processing data frame")
            return

        if data_frame_payload_format != ProtectWSPayloadFormat.JSON:
            return

        data_json = pjson.loads(data_frame)
        _LOGGER.debug("Data Frame: %s", data_json)

        if "lastMotion" not in data_json and "lastRing" not in data_json:
            return

        camera_id = action_json.get("id")

        if camera_id not in self.device_data:
            return

        if "lastRing" in data_json:
            # Make sure the event fetch does not miss the ring
            # by narrowing the start/end time to just the ring
            start_time = data_json["lastRing"]
            end_time = data_json["lastRing"]
        else:
            start_time = self._motion_start_time.get(camera_id, data_json["lastMotion"])
            end_time = None

        self.device_data[camera_id].update(PROCESSED_EVENT_EMPTY)
        # Remember the start or end of a motion event
        # so we can look backwards
        if "isMotionDetected" in data_json:
            if data_json.get("isMotionDetected"):
                self._motion_start_time[camera_id] = data_json["lastMotion"]
            elif camera_id in self._motion_start_time:
                del self._motion_start_time[camera_id]

        try:
            updated = await self._get_events(
                camera=camera_id, start_time=start_time, end_time=end_time
            )
        except NvrError:
            _LOGGER.exception(
                "Failed to fetch events after websocket update for %s", camera_id
            )
            return
        except asyncio.TimeoutError:
            _LOGGER.exception(
                "Timed out fetching events after websocket update for %s", camera_id
            )
            return

        if not updated:
            _LOGGER.debug(
                "No events were found for: %s. Time may be out of sync", camera_id
            )
            return

        for subscriber in self._ws_subscriptions:
            subscriber(updated)
