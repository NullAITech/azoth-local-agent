"""
WebSocket PTY Terminal Bridge for aZoth
Connects browser xterm.js sessions to the isolated Linux Guest OS or Sandbox shell.
"""

import asyncio
import fcntl
import json
import logging
import os
import pty
import select
import struct
import subprocess
import termios
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from .vm_manager import guest_os

logger = logging.getLogger("azoth.terminal_bridge")


async def handle_terminal_websocket(websocket: WebSocket, mode: str = "guest_os"):
    """
    Manages a live WebSocket connection to a Linux PTY running the Guest OS shell.
    Supports terminal resize, ANSI rendering, and bidirectional input/output.
    """
    await websocket.accept()

    # Ensure the guest OS environment is running
    guest_os.ensure_started()

    # Determine command to run based on requested mode and availability
    if mode == "guest_os" and guest_os.backend in ("docker", "podman") and guest_os.is_running():
        pty_cmd = [guest_os.backend, "exec", "-it", "azoth-guest-os", "/bin/bash"]
    else:
        pty_cmd = guest_os.get_pty_command()

    # Open pseudo-terminal
    master_fd, slave_fd = pty.openpty()

    # Default 80x24 window size
    try:
        winsize = struct.pack("HHHH", 24, 80, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
    except Exception as e:
        logger.warning("Could not set initial window size: %s", e)

    # Launch subprocess with the slave PTY
    proc = subprocess.Popen(
        pty_cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        close_fds=True,
    )
    os.close(slave_fd)  # Slave belongs to the child process

    # Set master_fd to non-blocking
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    async def read_from_pty():
        """Reads output from PTY master and pushes to browser WebSocket."""
        try:
            while not stop_event.is_set():
                # Check if master_fd has data
                readable, _, _ = await loop.run_in_executor(None, select.select, [master_fd], [], [], 0.05)
                if master_fd in readable:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            break
                        await websocket.send_text(data.decode("utf-8", errors="replace"))
                    except (OSError, IOError):
                        break
                if proc.poll() is not None:
                    break
        except Exception as e:
            logger.debug("PTY read error or closed: %s", e)
        finally:
            stop_event.set()

    async def write_to_pty():
        """Receives key inputs & control signals from browser WebSocket and writes to PTY."""
        try:
            while not stop_event.is_set():
                msg = await websocket.receive_text()
                if not msg:
                    continue

                # Check for resize or control packets
                if msg.startswith("{") and msg.endswith("}"):
                    try:
                        data = json.loads(msg)
                        if data.get("type") == "resize":
                            cols = int(data.get("cols", 80))
                            rows = int(data.get("rows", 24))
                            winsize = struct.pack("HHHH", rows, cols, 0, 0)
                            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                            continue
                    except Exception:
                        pass

                # Normal terminal keystrokes
                os.write(master_fd, msg.encode("utf-8"))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug("PTY write error: %s", e)
        finally:
            stop_event.set()

    # Run read and write concurrently
    read_task = asyncio.create_task(read_from_pty())
    write_task = asyncio.create_task(write_to_pty())

    done, pending = await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()

    # Cleanup
    try:
        os.close(master_fd)
    except Exception:
        pass

    try:
        proc.terminate()
        proc.wait(timeout=1)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    try:
        await websocket.close()
    except Exception:
        pass
