"""Compatibility forwarding module (ZERO Qt imports)."""

from .win_ui import launch_gui, main, run_interactive_native_ui, run_self_test

__all__ = ["launch_gui", "main", "run_interactive_native_ui", "run_self_test"]
