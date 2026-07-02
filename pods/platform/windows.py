import subprocess
import sys

from ..errors import SetupError

_FORWARD_PORTS = [8080]


class WindowsProxy:
    """Translates pods commands to WSL2 equivalents on Windows."""

    def check_wsl(self) -> bool:
        try:
            result = subprocess.run(
                ["wsl", "--status"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def _get_wsl_ip(self) -> str:
        try:
            result = subprocess.run(
                ["wsl", "--", "hostname", "-I"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise SetupError(
                "Cannot determine WSL2 IP address",
                reason=str(e),
                suggestion="Ensure WSL2 is installed and running",
            )
        if result.returncode != 0 or not result.stdout.strip():
            raise SetupError(
                "Cannot determine WSL2 IP address",
                reason="'wsl -- hostname -I' failed",
                suggestion="Ensure WSL2 is running: open a WSL terminal and retry",
            )
        return result.stdout.strip().split()[0]

    def run_in_wsl(self, args: list[str]) -> int:
        if not self.check_wsl():
            raise SetupError(
                "WSL2 not installed",
                reason="wsl --status failed",
                suggestion="Run 'wsl --install' in PowerShell as Administrator and restart",
            )
        result = subprocess.run(["wsl", "--"] + args)
        return result.returncode

    def setup_port_forwarding(self, port: int = 8080) -> None:
        """Forward Windows port to WSL2 via netsh portproxy.

        Requires Administrator privileges. Idempotent — deletes any existing
        rule for the same port before adding the new one.
        """
        wsl_ip = self._get_wsl_ip()

        # Remove stale rule first (ignore errors — rule may not exist)
        subprocess.run(
            [
                "netsh", "interface", "portproxy", "delete", "v4tov4",
                f"listenport={port}",
                "listenaddress=0.0.0.0",
            ],
            capture_output=True,
        )

        add = subprocess.run(
            [
                "netsh", "interface", "portproxy", "add", "v4tov4",
                f"listenport={port}",
                "listenaddress=0.0.0.0",
                f"connectport={port}",
                f"connectaddress={wsl_ip}",
            ],
            capture_output=True,
            text=True,
        )
        if add.returncode != 0:
            raise SetupError(
                f"Failed to forward port {port} to WSL2",
                reason=add.stderr.strip() or add.stdout.strip(),
                suggestion="Run PowerShell as Administrator and retry 'pods init'",
            )

    def setup_all_port_forwarding(self) -> None:
        for port in _FORWARD_PORTS:
            self.setup_port_forwarding(port)


def main() -> None:
    """Entry point for the Windows WSL2 proxy binary."""
    proxy = WindowsProxy()
    proxy.check_wsl()
    args = sys.argv[1:]
    # Forward gateway port when coordinator initialises
    if args and args[0] == "init":
        try:
            proxy.setup_all_port_forwarding()
        except SetupError as e:
            print(f"Warning: {e}", file=sys.stderr)
    returncode = proxy.run_in_wsl(["pods"] + args)
    sys.exit(returncode)


if __name__ == "__main__":
    main()
