import subprocess

from ..errors import SetupError


class WindowsProxy:
    """Translates pods commands to WSL2 equivalents on Windows.

    Full port forwarding implemented in Phase 2.
    """

    def check_wsl(self) -> bool:
        result = subprocess.run(
            ["wsl", "--status"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

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
        """Configure netsh portproxy to forward Windows port to WSL2.

        Implemented in Phase 2.
        """
        raise NotImplementedError("Port forwarding setup implemented in Phase 2")
