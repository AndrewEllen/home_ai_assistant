# modules/command_interpreter/client_command_router.py

from __future__ import annotations
from typing import Tuple, Any, Optional, Dict

from modules.voice_synth.voice_synth import speak_async

def detect_command(payload: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Returns a tuple (action, query, say)

    Actions:
      - "launch_game": run launcher locally using query; speak 'say' if provided
      - "say": just speak the message (from 'say' or 'msg'), no local action
    """
    if not isinstance(payload, dict):
        return ("say", None, str(payload))

    # Explicit client-route from server
    if payload.get("route") == "client":
        action = (payload.get("action") or "").lower()
        if action == "launch_game":
            query = (payload.get("query") or "").strip()
            say = (payload.get("say") or "").strip() or None
            return ("launch_game", query, say)
        # Unknown routed action -> just say fallback
        say = (payload.get("say") or "").strip() or None
        return ("say", None, say)

    # Normal server reply flow -> speak msg if present
    msg = payload.get("msg")
    if isinstance(msg, str) and msg.strip():
        return ("say", None, msg.strip())

    # Nothing useful
    return ("say", None, None)


def handle_server_payload(payload: Dict[str, Any]) -> None:
    """
    Execute routed client actions or speak server messages.
    """
    action, query, say = detect_command(payload)

    if action == "launch_game":
        try:
            from modules.application_control.open_games import launch_game_by_name
        except Exception:
            launch_game_by_name = None  # type: ignore

        spoken: Optional[str] = None
        if callable(launch_game_by_name):
            try:
                # Expected to return "Launching {name}" or False
                res = launch_game_by_name(query or "")
                if isinstance(res, str) and res.strip():
                    spoken = res
            except Exception as e:
                spoken = f"Couldn't launch {query}: {e}"

        if not spoken:
            spoken = say or (f"Launching {query}" if query else "Launching")

        speak_async(spoken)
        return

    # Default: just speak whatever the server sent
    text = say or payload.get("msg")
    if isinstance(text, str) and text.strip():
        speak_async(text.strip())
