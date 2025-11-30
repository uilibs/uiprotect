"""Audio streaming utilities for UniFi Protect cameras using PyAV."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple, cast
from urllib.parse import ParseResult, urlparse

import av
from av.audio import AudioStream

from .exceptions import BadRequest, StreamError

if TYPE_CHECKING:
    from .data import Camera

_LOGGER = logging.getLogger(__name__)

#: Default UDP port for talkback streaming.
DEFAULT_TALKBACK_PORT = 7004

#: Input timeout (open, read) in seconds.
INPUT_TIMEOUT = 5.0

#: Output timeout (open) in seconds. None = no read timeout for UDP.
OUTPUT_TIMEOUT: tuple[float, float | None] = (5.0, None)


class CodecConfig(NamedTuple):
    """
    Audio codec configuration for talkback streaming.

    Attributes:
        encoder: FFmpeg encoder name (e.g., "aac", "libopus").
        format: Output container format (e.g., "adts", "rtp").

    """

    encoder: str
    format: str


#: Supported audio codecs for talkback. Maps codec name to encoder/format config.
CODEC_MAP: dict[str, CodecConfig] = {
    "aac": CodecConfig("aac", "adts"),
    "opus": CodecConfig("libopus", "rtp"),
}


@dataclass(slots=True)
class TalkbackSession:
    """
    Talkback session configuration from the UniFi Protect public API.

    Attributes:
        url: UDP URL for talkback streaming (e.g., "udp://192.168.1.1:7004").
        codec: Audio codec name ("aac" or "opus").
        sampling_rate: Audio sampling rate in Hz.

    """

    url: str
    codec: str
    sampling_rate: int
    _parsed_url: ParseResult = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Parse URL on initialization."""
        self._parsed_url = urlparse(self.url)

    @classmethod
    def from_unifi_dict(cls, **data: object) -> TalkbackSession:
        """
        Create from UniFi API response.

        Args:
            **data: Raw API response fields (url, codec, samplingRate).

        Returns:
            Configured TalkbackSession instance.

        """
        return cls(
            url=str(data.get("url", "")),
            codec=str(data.get("codec", "")),
            sampling_rate=int(cast(Any, data.get("samplingRate", 0))),
        )

    @property
    def host(self) -> str:
        """Get hostname from talkback URL."""
        return self._parsed_url.hostname or ""

    @property
    def port(self) -> int:
        """Get port from talkback URL, defaults to 7004."""
        return self._parsed_url.port or DEFAULT_TALKBACK_PORT


class TalkbackStream:
    """
    Stream audio to a UniFi Protect camera's speaker using PyAV.

    This class handles audio transcoding and UDP streaming to camera speakers.
    It runs the actual streaming in a thread pool to avoid blocking the event loop.

    Example:
        ```python
        stream = TalkbackStream(camera, "/path/to/audio.wav", session)
        await stream.run_until_complete()
        ```

    """

    __slots__ = (
        "_error",
        "_lock",
        "_stop_event",
        "_task",
        "camera",
        "content_url",
        "session",
    )

    def __init__(
        self,
        camera: Camera,
        content_url: str,
        session: TalkbackSession | None = None,
    ) -> None:
        """
        Initialize talkback stream.

        Args:
            camera: Camera device to stream audio to.
            content_url: URL or file path of audio source.
            session: Optional talkback session from public API.

        Raises:
            BadRequest: If camera does not have a speaker.

        """
        if not camera.feature_flags.has_speaker:
            raise BadRequest("Camera does not have a speaker for talkback")

        self.camera = camera
        self.content_url = content_url
        self.session = session
        self._stop_event = threading.Event()
        self._task: asyncio.Future[None] | None = None
        self._lock = asyncio.Lock()
        self._error: BaseException | None = None

    async def __aenter__(self) -> TalkbackStream:
        """Start streaming when entering async context."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Stop streaming when exiting async context."""
        await self.stop()

    @property
    def is_running(self) -> bool:
        """Check if the stream is currently running."""
        return self._task is not None and not self._task.done()

    def _get_stream_params(self) -> tuple[str, int, str, int]:
        """
        Get streaming parameters from session or camera settings.

        Returns:
            Tuple of (host, port, codec, sample_rate).

        """
        if self.session:
            return (
                self.session.host,
                self.session.port,
                self.session.codec,
                self.session.sampling_rate,
            )
        ts = self.camera.talkback_settings
        return str(self.camera.host), ts.bind_port, ts.type_fmt.value, ts.sampling_rate

    def _stream_audio_sync(self) -> None:
        """Stream audio to the camera (runs in executor thread)."""
        host, port, codec, sample_rate = self._get_stream_params()

        config = CODEC_MAP.get(codec)
        if not config:
            self._error = StreamError(f"Unsupported codec: {codec}")
            return

        udp_url = f"udp://{host}:{port}"
        _LOGGER.debug("Talkback: %s codec=%s rate=%d", udp_url, codec, sample_rate)

        input_container = None
        output_container = None

        try:
            # Open input with timeout to avoid hanging
            input_container = av.open(
                self.content_url,
                timeout=(INPUT_TIMEOUT, INPUT_TIMEOUT),
            )

            if not input_container.streams.audio:
                self._error = StreamError("No audio stream found in input")
                return

            input_stream = input_container.streams.audio[0]

            output_container = av.open(
                udp_url,
                "w",
                format=config.format,
                timeout=OUTPUT_TIMEOUT,
            )

            output_stream = cast(
                AudioStream,
                output_container.add_stream(config.encoder, rate=sample_rate),
            )
            output_stream.layout = "mono"

            resampler = av.AudioResampler(
                format=output_stream.format, layout="mono", rate=sample_rate
            )

            for frame in input_container.decode(input_stream):
                if self._stop_event.is_set():
                    break
                for resampled in resampler.resample(frame):
                    resampled.pts = None
                    for packet in output_stream.encode(resampled):
                        output_container.mux(packet)

            # Flush encoder only if completed normally
            if not self._stop_event.is_set():
                for packet in output_stream.encode(None):
                    output_container.mux(packet)

        except av.FFmpegError as e:
            self._error = StreamError(f"Audio streaming failed: {e}")
        finally:
            if output_container is not None:
                output_container.close()
            if input_container is not None:
                input_container.close()

    def _start_task(self) -> None:
        """Reset state and start streaming task. Must hold lock."""
        self._stop_event.clear()
        self._error = None
        self._task = asyncio.get_running_loop().run_in_executor(
            None, self._stream_audio_sync
        )

    async def start(self) -> None:
        """Start the audio stream."""
        async with self._lock:
            if self._task is not None and not self._task.done():
                raise StreamError("Stream already started")
            self._start_task()

    async def stop(self) -> None:
        """Stop the audio stream gracefully and wait for completion."""
        async with self._lock:
            self._stop_event.set()
            if self._task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
                self._task = None

    async def run_until_complete(self) -> None:
        """Run the stream until it completes naturally."""
        async with self._lock:
            if self._task is None or self._task.done():
                self._start_task()
            task = self._task

        if task is not None:
            await task
        if self._error is not None:
            error = self._error
            self._error = None
            raise error
