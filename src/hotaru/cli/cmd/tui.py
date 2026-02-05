"""TUI command - start the interactive terminal interface."""

from typing import Optional
from ...tui.app import run_tui
from ...util.log import Log

log = Log.create({"service": "cli.tui"})

def tui_command(
    model: Optional[str] = None,
    agent: Optional[str] = None,
    session_id: Optional[str] = None,
    continue_session: bool = False,
    prompt: Optional[str] = None,
) -> None:
    """Start the Hotaru Code TUI.

    Args:
        model: Model in format provider/model
        agent: Agent name
        session_id: Session ID to continue
        continue_session: Continue last session
        prompt: Initial prompt to send
    """
    log.info("starting TUI", {
        "model": model,
        "agent": agent,
        "session_id": session_id,
        "continue_session": continue_session
    })

    # Run TUI application
    # run_tui is blocking, it takes over the terminal until exit
    run_tui(
        session_id=session_id,
        initial_prompt=prompt,
        model=model,
        agent=agent,
        continue_session=continue_session
    )
