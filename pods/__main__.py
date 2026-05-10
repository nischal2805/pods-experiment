import click
from .cli import (
    init, join, attach, invite, keygen, status, logs, ping,
    model as model_cmd, worker as worker_cmd, key as key_cmd, leave,
)

@click.group()
def main():
    """Pods — distributed LLM inference cluster."""

main.add_command(init.cmd, "init")
main.add_command(join.cmd, "join")
main.add_command(attach.cmd, "attach")
main.add_command(invite.cmd, "invite")
main.add_command(keygen.cmd, "keygen")
main.add_command(status.cmd, "status")
main.add_command(logs.cmd, "logs")
main.add_command(ping.cmd, "ping")
main.add_command(model_cmd.cmd, "model")
main.add_command(worker_cmd.cmd, "worker")
main.add_command(key_cmd.cmd, "key")
main.add_command(leave.cmd, "leave")

if __name__ == "__main__":
    main()
