"""Map selection screen."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from microciv.constants import DEFAULT_MAP_SIZE, DEFAULT_TURN_LIMIT
from microciv.game.enums import MapDifficulty, PlaybackMode, PolicyType
from microciv.game.models import GameConfig, GameState
from microciv.tui.presenters.game_session import build_state_from_config
from microciv.tui.presenters.state_machine import ScreenRoute
from microciv.tui.widgets.map_preview import MapPreview

TURN_LIMIT_OPTIONS = (30, 50, 80, 100, 150)
MAP_SIZE_OPTIONS = tuple(range(4, 11))
AI_TYPE_OPTIONS = (PolicyType.BASELINE, PolicyType.EXPERT, PolicyType.CUSTOM)
PLAYBACK_OPTIONS = (PlaybackMode.NORMAL, PlaybackMode.SPEED)


class SetupScreen(Screen[None]):
    """Shared configuration screen for Play and Autoplay."""

    BINDINGS = [Binding("q", "quit", "Quit")]

    DEFAULT_CSS = """
    SetupScreen {
        background: #111111;
        color: #f3ead7;
    }

    #setup-root {
        width: 1fr;
        height: 1fr;
        padding: 1 2;
        background: #111111;
    }

    #setup-title {
        width: 1fr;
        height: auto;
        content-align: center middle;
        color: #f2dfb4;
        text-style: bold;
        margin-bottom: 1;
    }

    #setup-main {
        width: 1fr;
        height: 1fr;
        background: #111111;
    }

    #setup-preview {
        width: 1fr;
        height: 1fr;
        padding: 1 1 1 0;
        align: center middle;
        background: #111111;
    }

    #setup-options {
        width: 40;
        height: 1fr;
        padding: 1 0 0 2;
        background: #111111;
    }

    #setup-options Button {
        width: 1fr;
        min-height: 3;
        margin-bottom: 1;
        border: none;
        background: #1d1c18;
        color: #f7efdd;
    }

    #setup-options Button:hover {
        background: #2b2822;
    }

    #setup-options Button:disabled {
        background: #171614;
        color: #7f7a71;
    }

    #setup-custom-input {
        width: 1fr;
        margin-bottom: 1;
        border: tall #3a372e;
        background: #151412;
        color: #f3ead7;
    }

    .setup-note {
        color: #a9b7be;
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        *,
        autoplay: bool,
        initial_config: GameConfig | None = None,
    ) -> None:
        super().__init__()
        self.route = ScreenRoute.SETUP_AUTOPLAY if autoplay else ScreenRoute.SETUP_PLAY
        self._autoplay = autoplay
        self._map_size = initial_config.map_size if initial_config else DEFAULT_MAP_SIZE
        self._turn_limit = initial_config.turn_limit if initial_config else DEFAULT_TURN_LIMIT
        self._difficulty = initial_config.map_difficulty if initial_config else MapDifficulty.NORMAL
        self._policy_type = initial_config.policy_type if autoplay and initial_config else PolicyType.BASELINE
        self._playback_mode = (
            initial_config.playback_mode if autoplay and initial_config else PlaybackMode.NORMAL
        )
        self._custom_goal = ""
        self._seed = initial_config.seed if initial_config else 0
        self._preview_state: GameState = self._build_preview_state()
        self._setup_refresh_serial = 0
        self._preview_widget: MapPreview | None = None

    def compose(self):
        title = "MAP SELECT"
        with Vertical(id="setup-root"):
            yield Static(title, id="setup-title")
            with Horizontal(id="setup-main"):
                with Vertical(id="setup-preview"):
                    self._preview_widget = MapPreview(
                        self._preview_state,
                        id="setup-map-preview",
                        settle_before_first_paint=True,
                    )
                    yield self._preview_widget
                with Vertical(id="setup-options"):
                    yield from self._compose_option_widgets()

    def action_quit(self) -> None:
        self.app.exit()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "setup-custom-input":
            self._custom_goal = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        assert button_id is not None

        if button_id == "setup-difficulty":
            self._difficulty = MapDifficulty.HARD if self._difficulty is MapDifficulty.NORMAL else MapDifficulty.NORMAL
            self._refresh_preview(recreate=False)
        elif button_id == "setup-map-size":
            index = MAP_SIZE_OPTIONS.index(self._map_size)
            self._map_size = MAP_SIZE_OPTIONS[(index + 1) % len(MAP_SIZE_OPTIONS)]
            self._refresh_preview(recreate=False)
        elif button_id == "setup-turn-limit":
            index = TURN_LIMIT_OPTIONS.index(self._turn_limit)
            self._turn_limit = TURN_LIMIT_OPTIONS[(index + 1) % len(TURN_LIMIT_OPTIONS)]
            self._schedule_setup_refresh(refresh_preview=False)
        elif button_id == "setup-ai-type":
            index = AI_TYPE_OPTIONS.index(self._policy_type)
            self._policy_type = AI_TYPE_OPTIONS[(index + 1) % len(AI_TYPE_OPTIONS)]
            self._schedule_setup_refresh(refresh_preview=False)
        elif button_id == "setup-playback":
            index = PLAYBACK_OPTIONS.index(self._playback_mode)
            self._playback_mode = PLAYBACK_OPTIONS[(index + 1) % len(PLAYBACK_OPTIONS)]
            self._schedule_setup_refresh(refresh_preview=False)
        elif button_id == "setup-recreate":
            self._refresh_preview(recreate=True)
        elif button_id == "setup-menu":
            self.app.return_to_menu()
        elif button_id == "setup-start":
            config = self._build_start_config()
            if config is None:
                return
            self.app.start_session(config)

    def _refresh_preview(self, *, recreate: bool) -> None:
        if recreate:
            self._seed += 1
        self._preview_state = self._build_preview_state()
        self._schedule_setup_refresh(refresh_preview=True)

    def _build_preview_state(self) -> GameState:
        preview_config = GameConfig.for_play(
            map_size=self._map_size,
            turn_limit=self._turn_limit,
            map_difficulty=self._difficulty,
            seed=self._seed,
        )
        return build_state_from_config(preview_config)

    def _build_start_config(self) -> GameConfig | None:
        if self._autoplay:
            if self._policy_type is not PolicyType.BASELINE:
                return None
            return GameConfig.for_autoplay(
                map_size=self._map_size,
                turn_limit=self._turn_limit,
                map_difficulty=self._difficulty,
                policy_type=self._policy_type,
                playback_mode=self._playback_mode,
                seed=self._seed,
            )
        return GameConfig.for_play(
            map_size=self._map_size,
            turn_limit=self._turn_limit,
            map_difficulty=self._difficulty,
            seed=self._seed,
        )

    def _note_text(self) -> str:
        if not self._autoplay:
            return ""
        if self._policy_type is PolicyType.BASELINE:
            return ""
        if self._policy_type is PolicyType.EXPERT:
            return "Phase 1: Baseline only."
        return "Phase 1: Baseline only."

    def _schedule_setup_refresh(self, *, refresh_preview: bool) -> None:
        self._setup_refresh_serial += 1
        refresh_serial = self._setup_refresh_serial
        self.call_next(self._apply_setup_refresh, refresh_serial, refresh_preview)

    def _apply_setup_refresh(self, refresh_serial: int, refresh_preview: bool) -> None:
        if refresh_serial != self._setup_refresh_serial or not self.is_mounted:
            return
        self.call_next(self._replace_option_children, refresh_serial, refresh_preview)

    async def _replace_option_children(self, refresh_serial: int, refresh_preview: bool) -> None:
        if refresh_serial != self._setup_refresh_serial or not self.is_mounted or not self.query("#setup-options"):
            return
        options = self.query_one("#setup-options", Vertical)
        await options.remove_children()
        if refresh_serial != self._setup_refresh_serial or not self.is_mounted or not options.is_mounted:
            return
        await options.mount_all(list(self._compose_option_widgets()))
        if refresh_preview:
            self.call_after_refresh(self._refresh_preview_after_layout, refresh_serial)

    def _refresh_preview_after_layout(self, refresh_serial: int) -> None:
        if refresh_serial != self._setup_refresh_serial or not self.is_mounted:
            return
        if self._preview_widget is None or not self._preview_widget.is_mounted:
            return
        self._preview_widget.set_state(self._preview_state)

    def _compose_option_widgets(self):
        widgets: list[Button | Input | Static] = [
            Button(f"Map Difficulty : {self._difficulty.value.title()}", id="setup-difficulty"),
            Button(f"Map Size : {self._map_size}", id="setup-map-size"),
            Button(f"Turn Limit : {self._turn_limit}", id="setup-turn-limit"),
        ]
        if self._autoplay:
            widgets.append(Button(f"AI Type : {self._policy_type.value.title()}", id="setup-ai-type"))
            custom_input = Input(
                value=self._custom_goal,
                placeholder="Custom goal",
                id="setup-custom-input",
            )
            custom_input.display = self._policy_type is PolicyType.CUSTOM
            widgets.append(custom_input)
            widgets.append(Button(f"Playback : {self._playback_mode.value.title()}", id="setup-playback"))
        widgets.extend(
            [
                Button(
                    "Start",
                    id="setup-start",
                    disabled=self._autoplay and self._policy_type is not PolicyType.BASELINE,
                ),
                Button("Recreate", id="setup-recreate"),
                Button("Menu", id="setup-menu"),
                Static(self._note_text(), classes="setup-note", id="setup-note"),
            ]
        )
        return widgets
