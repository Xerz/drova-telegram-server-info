"""Bounded, asynchronous SteamCMD PTY transport and public-build VDF parsing."""

from __future__ import annotations

import asyncio
import contextlib
import os
import pty
import re
import signal
import tty
from typing import Any

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TOKEN = re.compile(r'\s*("(?:\\.|[^"\\])*"|[{}])')


class SteamMetadataError(Exception):
    """No trustworthy public build was obtained; never expose raw command output."""


def _frame(output: str, appid: int) -> str:
    output = ANSI.sub("", output)
    match = re.search(rf'"{appid}"\s*\{{', output)
    if match is None:
        raise SteamMetadataError("metadata_unavailable")
    quoted = escaped = False
    depth = 0
    start = output.index("{", match.start())
    for pos in range(start, len(output)):
        char = output[pos]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
            if depth > 64:
                raise SteamMetadataError("metadata_depth")
        elif char == "}":
            depth -= 1
            if depth == 0:
                return output[start : pos + 1]
    raise SteamMetadataError("metadata_truncated")


def parse_app_info(output: str, appid: int) -> str:
    frame = _frame(output, appid)
    tokens: list[str] = []
    pos = 0
    while pos < len(frame):
        token = TOKEN.match(frame, pos)
        if token is None:
            raise SteamMetadataError("metadata_invalid")
        tokens.append(token[1])
        pos = token.end()
    index = 0

    def obj() -> dict[str, Any]:
        nonlocal index
        if tokens[index] != "{":
            raise SteamMetadataError("metadata_invalid")
        index += 1
        result: dict[str, Any] = {}
        while tokens[index] != "}":
            key = tokens[index]
            index += 1
            if not key.startswith('"'):
                raise SteamMetadataError("metadata_invalid")
            key = key[1:-1]
            if key in result:
                raise SteamMetadataError("metadata_duplicate_key")
            if tokens[index] == "{":
                result[key] = obj()
            else:
                value = tokens[index]
                if not value.startswith('"'):
                    raise SteamMetadataError("metadata_invalid")
                result[key] = value[1:-1]
                index += 1
        index += 1
        return result

    try:
        data = obj()
        build = data["depots"]["branches"]["public"]["buildid"]
        if not isinstance(build, str) or not re.fullmatch(r"[0-9]+", build) or int(build) <= 0:
            raise SteamMetadataError("metadata_invalid_build")
        return build
    except (IndexError, KeyError, TypeError) as exc:
        raise SteamMetadataError("metadata_unavailable") from exc


class SteamCmd:
    """One interactive anonymous session. Call refresh before each observation cycle."""

    def __init__(
        self,
        command: list[str] | None = None,
        *,
        timeout: float = 30,
        startup_timeout: float = 180,
        max_output: int = 8_000_000,
    ) -> None:
        self.command = command or ["/opt/steamcmd/steamcmd.sh"]
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self.max_output = max_output
        self._process: asyncio.subprocess.Process | None = None
        self._fd: int | None = None
        self._buffer = bytearray()
        self._lock = asyncio.Lock()

    async def _read_prompt(self, timeout: float) -> str:
        async with asyncio.timeout(timeout):
            while b"Steam>" not in self._buffer:
                if self._fd is None:
                    raise SteamMetadataError("steamcmd_closed")
                loop = asyncio.get_running_loop()
                ready: asyncio.Future[None] = loop.create_future()

                def readable(future: asyncio.Future[None] = ready) -> None:
                    if not future.done():
                        future.set_result(None)

                loop.add_reader(self._fd, readable)
                try:
                    await ready
                    chunk = os.read(self._fd, 65536)
                    if not chunk:
                        raise SteamMetadataError("steamcmd_closed")
                    self._buffer.extend(chunk)
                    if len(self._buffer) > self.max_output:
                        raise SteamMetadataError("steamcmd_output_limit")
                finally:
                    loop.remove_reader(self._fd)
            end = self._buffer.index(b"Steam>") + len(b"Steam>")
            result = bytes(self._buffer[:end]).decode("utf-8", errors="replace")
            del self._buffer[:end]
            return result

    async def _start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        await self.close()
        master, slave = pty.openpty()
        self._fd = master
        tty.setraw(slave)
        os.set_blocking(master, False)
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
            )
        finally:
            os.close(slave)
        await self._read_prompt(self.startup_timeout)
        login = await self._command("login anonymous", timeout=self.startup_timeout)
        if "OK" not in login or "Failure" in login or "FAILED" in login:
            raise SteamMetadataError("steamcmd_login")

    async def _command(self, command: str, *, timeout: float | None = None) -> str:
        if self._fd is None:
            raise SteamMetadataError("steamcmd_closed")
        os.write(self._fd, (command + "\n").encode("ascii"))
        return await self._read_prompt(timeout or self.timeout)

    async def refresh(self) -> None:
        async with self._lock:
            try:
                await self._start()
                output = await self._command("app_info_update 1")
                if re.search(r"failed|not logged|not online", output, re.IGNORECASE):
                    raise SteamMetadataError("steamcmd_refresh")
            except (OSError, TimeoutError, SteamMetadataError) as exc:
                await self.close()
                raise SteamMetadataError("steamcmd_refresh") from exc

    async def buildid(self, appid: int) -> str:
        if not 0 < appid <= 4294967295:
            raise ValueError("invalid AppID")
        async with self._lock:
            try:
                await self._start()
            except (OSError, TimeoutError, SteamMetadataError) as exc:
                await self.close()
                raise SteamMetadataError("steamcmd_start") from exc
            for attempt in range(3):
                try:
                    output = await self._command(f"app_info_print {appid}")
                except (OSError, TimeoutError, SteamMetadataError) as exc:
                    await self.close()
                    raise SteamMetadataError("steamcmd_transport") from exc
                try:
                    return parse_app_info(output, appid)
                except SteamMetadataError:
                    if attempt == 2:
                        # An unavailable app does not mean the Steam session is broken.
                        raise
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise SteamMetadataError("metadata_unavailable")

    async def close(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self._buffer.clear()
