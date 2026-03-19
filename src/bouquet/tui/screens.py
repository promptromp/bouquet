"""Modal screens for the Bouquet TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from bouquet.agents.base import AgentResponse


class ConfirmQuitScreen(ModalScreen[bool]):
    """Confirmation dialog before quitting and killing the tmux session."""

    CSS = """
    ConfirmQuitScreen {
        align: center middle;
    }

    #quit-dialog {
        width: 64;
        height: auto;
        padding: 1 2;
        border: thick $error;
        background: $surface;
    }

    #quit-dialog Label {
        margin-bottom: 1;
    }

    .button-row {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }

    .button-row Button {
        margin-right: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="quit-dialog"):
            yield Label("Quit Bouquet?")
            yield Label("This will kill the tmux session and all agent windows.")
            yield Label("Git worktrees will be left in place.")
            with Vertical(classes="button-row"):
                yield Button("Quit", variant="error", id="confirm-quit-btn")
                yield Button("Cancel", variant="default", id="cancel-quit-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-quit-btn")


class NewWorktreeScreen(ModalScreen[tuple[str, str] | None]):
    """Modal dialog for creating a new worktree."""

    CSS = """
    NewWorktreeScreen {
        align: center middle;
    }

    #dialog {
        width: 60;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    #dialog Label {
        margin-bottom: 1;
    }

    #dialog Input {
        margin-bottom: 1;
    }

    .button-row {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }

    .button-row Button {
        margin-right: 1;
    }
    """

    def __init__(self, default_base: str = "main") -> None:
        super().__init__()
        self._default_base = default_base

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("New Worktree")
            yield Label("Branch name:")
            yield Input(placeholder="feature/my-feature", id="branch-input")
            yield Label("Base branch:")
            yield Input(value=self._default_base, id="base-input")
            with Vertical(classes="button-row"):
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            branch_input = self.query_one("#branch-input", Input)
            base_input = self.query_one("#base-input", Input)
            branch = branch_input.value.strip()
            base = base_input.value.strip()
            if branch:
                self.dismiss((branch, base))
            else:
                branch_input.focus()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "branch-input":
            self.query_one("#base-input", Input).focus()
        elif event.input.id == "base-input":
            self.query_one("#create-btn", Button).press()


class BroadcastInputScreen(ModalScreen[str | None]):
    """Modal dialog to enter a message to broadcast to all agents."""

    CSS = """
    BroadcastInputScreen {
        align: center middle;
    }

    #broadcast-dialog {
        width: 80;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    #broadcast-dialog Label {
        margin-bottom: 1;
    }

    #broadcast-dialog Input {
        margin-bottom: 1;
    }

    .button-row {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }

    .button-row Button {
        margin-right: 1;
    }
    """

    def __init__(self, default_prompt: str = "") -> None:
        super().__init__()
        self._default_prompt = default_prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="broadcast-dialog"):
            yield Label("Broadcast to All Agents")
            yield Label("This will send a prompt to all active worktrees via claude -p.")
            yield Label("Prompt:")
            yield Input(
                value=self._default_prompt,
                placeholder="e.g. Summarize your current progress",
                id="prompt-input",
            )
            with Vertical(classes="button-row"):
                yield Button("Send", variant="primary", id="send-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            prompt = self.query_one("#prompt-input", Input).value.strip()
            self.dismiss(prompt if prompt else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#send-btn", Button).press()


class BroadcastResultsScreen(ModalScreen[None]):
    """Display results from a broadcast to all agents."""

    CSS = """
    BroadcastResultsScreen {
        align: center middle;
    }

    #results-dialog {
        width: 90%;
        height: 80%;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    #results-dialog Label {
        margin-bottom: 1;
    }

    #results-scroll {
        height: 1fr;
        margin-bottom: 1;
    }

    .result-branch {
        text-style: bold;
        color: $accent;
        margin-top: 1;
    }

    .result-error {
        text-style: bold;
        color: $error;
        margin-top: 1;
    }

    .result-body {
        margin-left: 2;
        margin-bottom: 1;
    }

    .result-meta {
        margin-left: 2;
        color: $text-muted;
    }
    """

    def __init__(self, responses: list[AgentResponse]) -> None:
        super().__init__()
        self._responses = responses

    def compose(self) -> ComposeResult:
        with Vertical(id="results-dialog"):
            ok = sum(1 for r in self._responses if r.ok)
            total = len(self._responses)
            yield Label(f"Broadcast Results ({ok}/{total} succeeded)")
            with VerticalScroll(id="results-scroll"):
                for resp in self._responses:
                    if resp.ok:
                        yield Static(f"[{resp.worktree_branch}]", classes="result-branch")
                        yield Static(resp.result[:2000] if resp.result else "(empty response)", classes="result-body")
                    else:
                        yield Static(f"[{resp.worktree_branch}] ERROR", classes="result-error")
                        yield Static(resp.error or "Unknown error", classes="result-body")
                    duration = f"{resp.duration_ms / 1000:.1f}s" if resp.duration_ms else "?"
                    cost = f"${resp.cost_usd:.4f}" if resp.cost_usd else ""
                    yield Static(f"  {duration} {cost}".strip(), classes="result-meta")
            yield Button("Close", variant="primary", id="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)
