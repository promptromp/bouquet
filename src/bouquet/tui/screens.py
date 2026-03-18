"""Modal screens for the Bouquet TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


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
