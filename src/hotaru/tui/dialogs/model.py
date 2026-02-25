"""Model and agent selection dialogs."""

from typing import Any, Dict, List, Optional, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, ListItem, ListView, Static

from .base import DialogBase


class ModelSelectDialog(DialogBase):
    """Model selection dialog grouped by provider."""

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    ModelSelectDialog > Container {
        width: 70;
    }

    ModelSelectDialog .provider-section {
        margin-bottom: 1;
    }

    ModelSelectDialog .provider-name {
        text-style: bold;
        color: $text-muted;
    }

    ModelSelectDialog ListView {
        height: auto;
        max-height: 20;
    }

    ModelSelectDialog ListItem {
        padding: 0 1;
    }
    """

    def __init__(
        self,
        providers: Dict[str, List[Dict[str, Any]]],
        current_model: Optional[Tuple[str, str]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.providers = providers
        self.current_model = current_model
        self._model_options: List[Tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        items = []
        self._model_options = []
        for provider_id, models in self.providers.items():
            items.append(
                ListItem(
                    Static(f"── {provider_id} ──", classes="provider-name"),
                    disabled=True,
                )
            )
            for model in models:
                model_id = model.get("id", "")
                model_name = model.get("name", model_id)
                is_current = (
                    self.current_model
                    and self.current_model[0] == provider_id
                    and self.current_model[1] == model_id
                )
                label = f"{'● ' if is_current else '  '}{model_name}"
                option_index = len(self._model_options)
                self._model_options.append((provider_id, model_id))
                items.append(
                    ListItem(Static(label), id=f"model-option-{option_index}")
                )

        yield Container(
            Static("Select Model", classes="dialog-title"),
            ListView(*items, id="models-list"),
            Horizontal(
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="dialog-buttons",
            ),
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not event.item or not event.item.id:
            return
        if not event.item.id.startswith("model-option-"):
            return
        try:
            index = int(event.item.id.split("-")[-1])
        except ValueError:
            return
        if 0 <= index < len(self._model_options):
            self.dismiss(self._model_options[index])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class AgentSelectDialog(DialogBase):
    """Agent selection dialog."""

    DEFAULT_CSS = DialogBase.DEFAULT_CSS + """
    AgentSelectDialog > Container {
        width: 70;
    }

    AgentSelectDialog ListView {
        height: auto;
        max-height: 20;
    }
    """

    def __init__(
        self,
        agents: List[Dict[str, Any]],
        current_agent: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.agents = agents
        self.current_agent = current_agent

    def compose(self) -> ComposeResult:
        items = []
        for agent in self.agents:
            name = agent.get("name", "")
            description = agent.get("description", "")
            marker = "● " if name == self.current_agent else "  "
            label = Text()
            label.append(f"{marker}{name}", style="bold")
            if description:
                label.append(f"\n  {description}", style="dim")
            items.append(ListItem(Static(label), id=f"agent-{name}"))

        yield Container(
            Static("Select Agent", classes="dialog-title"),
            ListView(*items, id="agents-list") if items else Static("No agents found"),
            Horizontal(
                Button("Cancel", variant="default", id="cancel-btn"),
                classes="dialog-buttons",
            ),
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id and event.item.id.startswith("agent-"):
            self.dismiss(event.item.id[6:])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)
