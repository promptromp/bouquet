"""Modal screens for the Bouquet TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, Switch

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


class NewWorktreeScreen(ModalScreen[tuple[str, str, str | None] | None]):
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

    #dialog Select {
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

    def __init__(self, default_base: str = "main", profile_names: list[str] | None = None) -> None:
        super().__init__()
        self._default_base = default_base
        self._profile_names = profile_names or []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("New Worktree")
            yield Label("Branch name:")
            yield Input(placeholder="feature/my-feature", id="branch-input")
            yield Label("Base branch:")
            yield Input(value=self._default_base, id="base-input")
            if self._profile_names:
                yield Label("Agent profile:")
                yield Select(
                    [(name, name) for name in self._profile_names],
                    value=self._profile_names[0],
                    id="profile-select",
                )
            with Vertical(classes="button-row"):
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            branch_input = self.query_one("#branch-input", Input)
            base_input = self.query_one("#base-input", Input)
            branch = branch_input.value.strip()
            base = base_input.value.strip()
            profile: str | None = None
            if self._profile_names:
                select = self.query_one("#profile-select", Select)
                profile = str(select.value) if select.value != Select.BLANK else None
            if branch:
                self.dismiss((branch, base, profile))
            else:
                branch_input.focus()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "branch-input":
            self.query_one("#base-input", Input).focus()
        elif event.input.id == "base-input":
            self.query_one("#create-btn", Button).press()


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

    .result-header {
        text-style: bold underline;
        margin-top: 1;
    }

    .result-body {
        margin-left: 2;
        margin-bottom: 1;
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
                    branch = resp.worktree_branch or "unknown"
                    duration = f"{resp.duration_ms / 1000:.1f}s" if resp.duration_ms else "?"
                    cost = f"  ${resp.cost_usd:.4f}" if resp.cost_usd else ""
                    if resp.ok:
                        header = f"{branch}  ({duration}{cost})"
                        yield Static(header, classes="result-header", markup=False)
                        yield Static(resp.result[:2000] if resp.result else "(empty response)", classes="result-body")
                    else:
                        header = f"{branch}  ERROR ({duration}{cost})"
                        yield Static(header, classes="result-header", markup=False)
                        yield Static(resp.error or "Unknown error", classes="result-body")
            yield Button("Close", variant="primary", id="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class SendPromptScreen(ModalScreen[tuple[str, bool] | None]):
    """Send a prompt directly to running agent(s) via tmux send-keys."""

    CSS = """
    SendPromptScreen {
        align: center middle;
    }

    #send-prompt-dialog {
        width: 70;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    #send-prompt-dialog Label {
        margin-bottom: 1;
    }

    #send-prompt-dialog Input {
        margin-bottom: 1;
    }

    .toggle-row {
        height: auto;
        margin-bottom: 1;
    }

    .toggle-row Switch {
        margin-right: 1;
    }

    .toggle-row .toggle-label {
        margin-top: 1;
        margin-bottom: 0;
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

    def __init__(self, selected_branch: str | None = None, default_send_all: bool = False) -> None:
        super().__init__()
        self._selected_branch = selected_branch
        self._default_send_all = default_send_all

    def compose(self) -> ComposeResult:
        with Vertical(id="send-prompt-dialog"):
            yield Label("Send Prompt to Agent")
            yield Label("Types directly into the agent's terminal via tmux send-keys.")
            yield Label("Prompt:")
            yield Input(placeholder="e.g. Fix the failing test", id="prompt-input")
            with Horizontal(classes="toggle-row"):
                yield Switch(value=self._default_send_all, id="all-switch")
                yield Label("Send to all worktrees", classes="toggle-label")
            if self._selected_branch:
                yield Label(f"Selected: {self._selected_branch}", id="target-label")
            with Vertical(classes="button-row"):
                yield Button("Send", variant="primary", id="send-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            prompt = self.query_one("#prompt-input", Input).value.strip()
            send_all = self.query_one("#all-switch", Switch).value
            if prompt:
                self.dismiss((prompt, send_all))
            else:
                self.query_one("#prompt-input", Input).focus()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#send-btn", Button).press()
