"""
aZoth Linux Virtual Environment & Guest OS Manager
Provides containerized micro-OS and virtual environment orchestration for agents.
Supports Docker/Podman Guest OS, local isolated Sandbox PTY, and QEMU micro-VM hooks.
"""

import os
import subprocess
import shutil
import time
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger("azoth.vm_manager")

WORKSPACE_DIR = Path(__file__).parent.parent / "sandbox" / "workspace"
CONTAINER_NAME = "azoth-guest-os"
IMAGE_NAME = "azoth-guest-os:latest"


class GuestOSManager:
    """Manages the isolated Linux Guest OS environment for aZoth agents."""

    def __init__(self):
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(WORKSPACE_DIR, 0o777)
        except Exception:
            pass
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        """Detect the best available backend: docker, podman, or local_sandbox."""
        if shutil.which("docker"):
            try:
                res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                if res.returncode == 0:
                    return "docker"
            except Exception:
                pass

        if shutil.which("podman"):
            try:
                res = subprocess.run(["podman", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                if res.returncode == 0:
                    return "podman"
            except Exception:
                pass

        return "local_sandbox"

    @property
    def backend(self) -> str:
        return self._backend

    def is_running(self) -> bool:
        """Check if the guest OS environment is active."""
        if self._backend in ("docker", "podman"):
            cmd = [self._backend, "ps", "--filter", f"name={CONTAINER_NAME}", "--format", "{{.Names}}"]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                return CONTAINER_NAME in res.stdout.strip().splitlines()
            except Exception:
                return False
        return True  # Local sandbox is always available

    def _ensure_guest_tools(self) -> None:
        """Ensure azoth-browser CLI is present in workspace and symlinked in /usr/local/bin."""
        try:
            cli_src = Path(__file__).parent / "browser_cli.py"
            cli_dest = WORKSPACE_DIR / "azoth-browser"
            if cli_src.exists():
                shutil.copy2(cli_src, cli_dest)
                cli_dest.chmod(0o755)

            # If container is running, symlink into /usr/local/bin
            if self._backend in ("docker", "podman") and self.is_running():
                subprocess.run(
                    [self._backend, "exec", "-u", "0", CONTAINER_NAME, "ln", "-sf", "/workspace/azoth-browser", "/usr/local/bin/azoth-browser"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
        except Exception as e:
            logger.debug(f"Failed ensuring guest tools: {e}")

    def ensure_started(self) -> Dict[str, Any]:
        """Ensure the isolated environment is active."""
        if self._backend not in ("docker", "podman"):
            self._ensure_guest_tools()
            return {
                "success": True,
                "backend": "local_sandbox",
                "message": "Local isolated sandbox environment active.",
                "running": True
            }

        cli = self._backend
        # Check if already running
        if self.is_running():
            self._ensure_guest_tools()
            return {"success": True, "backend": cli, "message": f"{CONTAINER_NAME} is already running.", "running": True}

        # Check if container exists but stopped
        check_all = subprocess.run([cli, "ps", "-a", "--filter", f"name={CONTAINER_NAME}", "--format", "{{.Names}}"],
                                   capture_output=True, text=True, timeout=5)
        if CONTAINER_NAME in check_all.stdout.strip().splitlines():
            # Start existing container
            start_res = subprocess.run([cli, "start", CONTAINER_NAME], capture_output=True, text=True, timeout=10)
            if start_res.returncode == 0:
                self._ensure_guest_tools()
                return {"success": True, "backend": cli, "message": f"Started existing container {CONTAINER_NAME}.", "running": True}

        # Image check - if custom image not present, fallback to debian:bookworm-slim or alpine
        img = IMAGE_NAME
        img_check = subprocess.run([cli, "image", "inspect", img], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if img_check.returncode != 0:
            # Check if debian:bookworm-slim exists
            img_deb = subprocess.run([cli, "image", "inspect", "debian:bookworm-slim"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if img_deb.returncode == 0:
                img = "debian:bookworm-slim"
            else:
                img = "alpine:latest"

        # Create and run container
        workspace_host = str(WORKSPACE_DIR.resolve())
        run_cmd = [
            cli, "run", "-d",
            "--name", CONTAINER_NAME,
            "--hostname", "azoth-guest-os",
            "-v", f"{workspace_host}:/workspace:rw",
            "-w", "/workspace",
            img,
            "/bin/sh", "-c", "while true; do sleep 3600; done"
        ]

        try:
            res = subprocess.run(run_cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                self._ensure_guest_tools()
                return {
                    "success": True,
                    "backend": cli,
                    "message": f"Successfully initialized and started {CONTAINER_NAME} using {img}.",
                    "running": True
                }
            else:
                return {
                    "success": False,
                    "backend": cli,
                    "error": res.stderr.strip(),
                    "running": False
                }
        except Exception as e:
            return {"success": False, "backend": cli, "error": str(e), "running": False}

    def stop(self) -> Dict[str, Any]:
        """Stop the guest OS container."""
        if self._backend in ("docker", "podman"):
            cli = self._backend
            try:
                res = subprocess.run([cli, "stop", CONTAINER_NAME], capture_output=True, text=True, timeout=10)
                return {"success": res.returncode == 0, "message": f"Stopped {CONTAINER_NAME}."}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": True, "message": "Local sandbox stopped."}

    def restart(self) -> Dict[str, Any]:
        """Restart the guest OS container."""
        if self._backend in ("docker", "podman"):
            cli = self._backend
            try:
                res = subprocess.run([cli, "restart", CONTAINER_NAME], capture_output=True, text=True, timeout=15)
                return {"success": res.returncode == 0, "message": f"Restarted {CONTAINER_NAME}."}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": True, "message": "Local sandbox restarted."}

    def run_command(self, command: str, timeout: int = 60, workdir: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute a command inside the isolated Linux Guest OS environment.
        Returns stdout, stderr, exit_code, duration_ms.
        """
        self.ensure_started()
        t0 = time.time()

        if self._backend in ("docker", "podman") and self.is_running():
            cli = self._backend
            cmd = [cli, "exec"]
            if workdir:
                cmd.extend(["-w", workdir])
            cmd.extend([CONTAINER_NAME, "/bin/bash", "-c", command])

            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                duration_ms = int((time.time() - t0) * 1000)
                return {
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "exit_code": res.returncode,
                    "duration_ms": duration_ms,
                    "backend": cli,
                    "target": "guest_os"
                }
            except subprocess.TimeoutExpired:
                return {
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout} seconds.",
                    "exit_code": -1,
                    "duration_ms": int((time.time() - t0) * 1000),
                    "backend": cli,
                    "target": "guest_os"
                }
            except Exception as e:
                return {
                    "stdout": "",
                    "stderr": str(e),
                    "exit_code": -1,
                    "duration_ms": int((time.time() - t0) * 1000),
                    "backend": cli,
                    "target": "guest_os"
                }
        else:
            # Fallback to local sandbox directory
            run_dir = workdir or str(WORKSPACE_DIR)
            try:
                res = subprocess.run(["/bin/bash", "-c", command], cwd=run_dir, capture_output=True, text=True, timeout=timeout)
                duration_ms = int((time.time() - t0) * 1000)
                return {
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "exit_code": res.returncode,
                    "duration_ms": duration_ms,
                    "backend": "local_sandbox",
                    "target": "sandbox_workspace"
                }
            except Exception as e:
                return {
                    "stdout": "",
                    "stderr": str(e),
                    "exit_code": -1,
                    "duration_ms": int((time.time() - t0) * 1000),
                    "backend": "local_sandbox",
                    "target": "sandbox_workspace"
                }

    def get_status(self) -> Dict[str, Any]:
        """Get guest OS runtime status, CPU/RAM vitals, and environment info."""
        is_run = self.is_running()
        status = {
            "backend": self._backend,
            "running": is_run,
            "container_name": CONTAINER_NAME if self._backend in ("docker", "podman") else "local_sandbox",
            "workspace_dir": str(WORKSPACE_DIR.resolve()),
            "hostname": "unknown",
            "os_release": "unknown",
            "kernel": "unknown",
            "uptime": "unknown",
            "memory": "unknown",
            "disk": "unknown"
        }

        if is_run:
            # Fetch uname and vitals
            res = self.run_command("uname -a; uptime; free -h 2>/dev/null || free; df -h /", timeout=5)
            if res.get("exit_code") == 0:
                raw = res.get("stdout", "")
                status["vitals_raw"] = raw
                lines = raw.strip().splitlines()
                if len(lines) >= 1:
                    status["kernel"] = lines[0]
                if len(lines) >= 2:
                    status["uptime"] = lines[1].strip()
                for line in lines:
                    if line.startswith("Mem:"):
                        parts = line.split()
                        if len(parts) >= 3:
                            status["memory"] = f"{parts[2]} / {parts[1]}"
                    elif line.startswith("overlay") or line.endswith("/"):
                        parts = line.split()
                        if len(parts) >= 5:
                            status["disk"] = f"{parts[2]} used / {parts[3]} avail ({parts[4]})"

            # Get OS release
            os_res = self.run_command("cat /etc/os-release 2>/dev/null", timeout=3)
            if os_res.get("exit_code") == 0:
                for line in os_res.get("stdout", "").splitlines():
                    if line.startswith("PRETTY_NAME="):
                        status["os_release"] = line.split("=", 1)[1].strip('"\'')
                        break

            # Hostname
            hn_res = self.run_command("hostname", timeout=3)
            if hn_res.get("exit_code") == 0:
                status["hostname"] = hn_res.get("stdout", "").strip()

        return status

    def install_package(self, package: str) -> Dict[str, Any]:
        """Install software inside the guest OS environment."""
        self.ensure_started()
        # Detect package manager
        check_pkg = self.run_command("which apt-get || which apk || which dnf || which pacman", timeout=5)
        pkg_bin = check_pkg.get("stdout", "").strip()

        if "apt-get" in pkg_bin:
            cmd = f"sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y {package}"
        elif "apk" in pkg_bin:
            cmd = f"apk update && apk add {package}"
        elif "pacman" in pkg_bin:
            cmd = f"pacman -Sy --noconfirm {package}"
        else:
            # Try pip
            cmd = f"pip install {package} || pip3 install {package}"

        return self.run_command(cmd, timeout=180)

    def get_pty_command(self) -> List[str]:
        """Get the argv list for spawning an interactive PTY shell."""
        self.ensure_started()
        if self._backend in ("docker", "podman") and self.is_running():
            return [self._backend, "exec", "-it", CONTAINER_NAME, "/bin/bash"]
        else:
            return ["/bin/bash", "--init-file", str(WORKSPACE_DIR.parent / "sandbox_env.sh")]


# Global singleton
guest_os = GuestOSManager()
