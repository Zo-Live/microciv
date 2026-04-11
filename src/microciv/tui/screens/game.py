"""Main play and autoplay screen."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Button, Static

from microciv.constants import (
    DEFAULT_AUTOPLAY_INTERVAL_MS,
    DEFAULT_SPEED_REFRESH_MS,
    DEFAULT_SPEED_REFRESH_TURNS,
)
from microciv.game.actions import Action, validate_action
from microciv.game.enums import ActionType, BuildingType, OccupantType, PlaybackMode, ResourceType, TechType
from microciv.tui.presenters.game_session import GameSession, selected_city_id_for_coord
from microciv.tui.presenters.state_machine import ScreenRoute
from microciv.tui.screens.game_menu import GameMenuScreen
from microciv.tui.widgets.action_panel import ResourceButton
from microciv.tui.widgets.map_view import MapView
from microciv.tui.widgets.metric_panel import MetricPanel

PANEL_DEFAULT = "default"
PANEL_TERRAIN = "terrain"
PANEL_CITY = "city"
PANEL_BUILD_CONFIRM = "build_confirm"
PANEL_RESEARCH_CONFIRM = "research_confirm"

RESOURCE_BUILDING_MAP: dict[ResourceType, BuildingType] = {
    ResourceType.FOOD: BuildingType.FARM,
    ResourceType.WOOD: BuildingType.LUMBER_MILL,
    ResourceType.ORE: BuildingType.MINE,
    ResourceType.SCIENCE: BuildingType.LIBRARY,
}

RESOURCE_LABELS: dict[ResourceType, str] = {
    ResourceType.FOOD: "Food",
    ResourceType.WOOD: "Wood",
    ResourceType.ORE: "Ore",
    ResourceType.SCIENCE: "Science",
}


class GameScreen(Screen[None]):
    """Shared game screen for manual play and autoplay."""

    route = ScreenRoute.GAME

    BINDINGS = [
        Binding("m", "open_menu", "Menu"),
        Binding("q", "quit", "Quit"),
    ]

    DEFAULT_CSS = """
    GameScreen {
        background: #111111;
        color: #f3ead7;
    }

    #game-root {
        width: 1fr;
        height: 1fr;
        padding: 1;
    }

    #game-map-shell {
        width: 1fr;
        height: 1fr;
        padding-right: 1;
        align: center middle;
    }

    #game-side-shell {
        width: 30;
        height: 1fr;
        padding-left: 1;
    }

    #game-context-shell {
        width: 1fr;
        height: 1fr;
        margin-top: 1;
    }

    #game-context-shell Button {
        width: 1fr;
        min-height: 3;
        margin-bottom: 1;
        border: none;
        background: #1d1c18;
        color: #f7efdd;
    }

    #game-context-shell Button:hover {
        background: #2b2822;
    }

    #game-context-shell Button.-selected {
        background: #2a2921;
        color: #fef8e7;
    }

    .context-row {
        width: 1fr;
        height: auto;
    }

    .terrain-choice-row {
        width: 1fr;
        height: auto;
        grid-size: 2;
        grid-columns: 1fr 1fr;
        grid-gutter: 1 0;
    }

    .terrain-choice-row Button {
        width: 1fr;
        min-width: 0;
    }

    .context-row ResourceButton {
        width: 1fr;
    }

    .context-label {
        color: #f2dfb4;
        text-style: bold;
        margin-bottom: 1;
    }

    .context-note {
        color: #a9b7be;
        margin-top: 1;
        height: auto;
    }

    .tech-button {
        width: 1fr;
        margin-bottom: 1;
        border: none;
        background: #171614;
        color: #f7efdd;
    }

    .tech-button.-unlocked {
        color: #f2dfb4;
        text-style: bold;
        background: #1e1c19;
    }
    """

    def __init__(self, session: GameSession) -> None:
        super().__init__()
        self.session = session
        self._autoplay_timer: Timer | None = None
        self._panel_mode = PANEL_DEFAULT
        self._terrain_choice = ActionType.BUILD_CITY
        self._pending_building: BuildingType | None = None
        self._pending_tech: TechType | None = None

    def compose(self):
        state = self.session.state
        with Horizontal(id="game-root"):
            with Vertical(id="game-map-shell"):
                yield MapView(
                    state,
                    selected_coord=state.selection.selected_coord,
                    interactive=self.session.policy is None,
                    id="game-map",
                )
            with Vertical(id="game-side-shell"):
                yield MetricPanel(
                    score=state.score,
                    turn=state.turn,
                    turn_limit=state.config.turn_limit,
                    info_lines=self._metric_info_lines(),
                    autoplay=self.session.policy is not None,
                    id="game-metric-panel",
                )
                if self.session.policy is None:
                    with Vertical(id="game-context-shell"):
                        yield from self._compose_manual_context()

    def on_mount(self) -> None:
        if self.session.policy is not None:
            self._start_autoplay()

    def on_unmount(self) -> None:
        self._stop_autoplay()

    def action_open_menu(self) -> None:
        self.app.push_screen(GameMenuScreen())

    def action_quit(self) -> None:
        self.app.exit()

    def on_map_view_tile_selected(self, message: MapView.TileSelected) -> None:
        if self.session.policy is not None:
            return
        self._handle_tile_click(message.coord)

    def on_resource_button_pressed(self, message: ResourceButton.Pressed) -> None:
        resource_type = message.resource_type
        self._pending_building = RESOURCE_BUILDING_MAP[resource_type]
        self._pending_tech = None
        self._panel_mode = PANEL_BUILD_CONFIRM
        self.refresh(layout=True, recompose=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        assert button_id is not None
        if button_id == "action-skip":
            self._apply_action(Action.skip())
            return
        if button_id == "action-cancel":
            self._cancel_panel()
            return
        if button_id == "action-build":
            self._apply_primary_panel_action()
            return
        if button_id == "action-choice-city":
            self._terrain_choice = ActionType.BUILD_CITY
            self.refresh(layout=True, recompose=True)
            return
        if button_id == "action-choice-road":
            self._terrain_choice = ActionType.BUILD_ROAD
            self.refresh(layout=True, recompose=True)
            return
        if button_id.startswith("tech-"):
            tech = TechType(button_id.removeprefix("tech-"))
            city_id = self.session.state.selection.selected_city_id
            if city_id is None:
                return
            city = self.session.state.cities.get(city_id)
            if city is None:
                return
            network = self.session.state.networks[city.network_id]
            if tech in network.unlocked_techs:
                return
            self._pending_tech = tech
            self._pending_building = None
            self._panel_mode = PANEL_RESEARCH_CONFIRM
            self.refresh(layout=True, recompose=True)

    def _compose_manual_context(self):
        if self._panel_mode == PANEL_TERRAIN:
            choices = self._terrain_choices()
            if len(choices) == 2:
                with Grid(classes="terrain-choice-row"):
                    yield Button("City", id="action-choice-city", classes=self._choice_class(ActionType.BUILD_CITY))
                    yield Button("Road", id="action-choice-road", classes=self._choice_class(ActionType.BUILD_ROAD))
            elif ActionType.BUILD_CITY in choices:
                yield Button("City", id="action-choice-city", classes="-selected")
            elif ActionType.BUILD_ROAD in choices:
                yield Button("Road", id="action-choice-road", classes="-selected")
            yield Button("Build", id="action-build")
            yield Button("Cancel", id="action-cancel")
            return

        if self._panel_mode == PANEL_CITY:
            city_id = self.session.state.selection.selected_city_id
            if city_id is None:
                yield Button("Skip", id="action-skip")
                return
            city = self.session.state.cities[city_id]
            network = self.session.state.networks[city.network_id]
            yield Static("Resources", classes="context-label")
            with Horizontal(classes="context-row"):
                yield ResourceButton(ResourceType.FOOD, network.resources.food, id="resource-food")
                yield ResourceButton(ResourceType.WOOD, network.resources.wood, id="resource-wood")
            with Horizontal(classes="context-row"):
                yield ResourceButton(ResourceType.ORE, network.resources.ore, id="resource-ore")
                yield ResourceButton(ResourceType.SCIENCE, network.resources.science, id="resource-science")
            yield Static("Tech", classes="context-label")
            for tech in TechType:
                classes = "tech-button -unlocked" if tech in network.unlocked_techs else "tech-button"
                yield Button(tech.value.title(), id=f"tech-{tech.value}", classes=classes)
            yield Button("Cancel", id="action-cancel")
            return

        if self._panel_mode == PANEL_BUILD_CONFIRM:
            city_id = self.session.state.selection.selected_city_id
            count = 0
            if city_id is not None and self._pending_building is not None:
                city = self.session.state.cities[city_id]
                count = city.buildings.for_type(self._pending_building)
            yield Static("Build", classes="context-label")
            with Horizontal(classes="context-row"):
                if self._pending_building is not None:
                    resource_type = _resource_type_for_building(self._pending_building)
                    yield ResourceButton(resource_type, count, id="build-confirm-resource", interactive=False)
            yield Static(f"count: {count}", classes="context-note")
            yield Button("Build", id="action-build")
            yield Button("Cancel", id="action-cancel")
            return

        if self._panel_mode == PANEL_RESEARCH_CONFIRM:
            label = self._pending_tech.value.title() if self._pending_tech is not None else "Research"
            yield Static(label, classes="context-label")
            yield Button("Research", id="action-build")
            yield Button("Cancel", id="action-cancel")
            return

        yield Button("Skip", id="action-skip")

    def _choice_class(self, action_type: ActionType) -> str:
        return "-selected" if self._terrain_choice is action_type else ""

    def _metric_info_lines(self) -> list[str]:
        state = self.session.state
        if self.session.policy is None:
            return [state.message] if state.message else []
        info_lines = [f"mode: {state.config.playback_mode.value}   ai: {state.config.policy_type.value}"]
        if state.message:
            info_lines.append(f"tip: {state.message}")
        return info_lines

    def _handle_tile_click(self, coord: tuple[int, int]) -> None:
        state = self.session.state
        if state.selection.selected_coord == coord and self._panel_mode in {PANEL_DEFAULT, PANEL_TERRAIN, PANEL_CITY}:
            self._clear_selection()
            self.refresh(layout=True, recompose=True)
            return

        state.message = ""
        state.selection.selected_coord = coord
        state.selection.selected_city_id = selected_city_id_for_coord(state, coord)
        self._pending_building = None
        self._pending_tech = None

        tile = state.board[coord]
        if tile.occupant is OccupantType.CITY:
            self._panel_mode = PANEL_CITY
        else:
            choices = self._terrain_choices()
            self._panel_mode = PANEL_TERRAIN if choices else PANEL_DEFAULT
            if choices:
                self._terrain_choice = choices[0]
        self.refresh(layout=True, recompose=True)

    def _terrain_choices(self) -> list[ActionType]:
        coord = self.session.state.selection.selected_coord
        if coord is None:
            return []
        choices: list[ActionType] = []
        if validate_action(self.session.state, Action.build_city(coord)).is_valid:
            choices.append(ActionType.BUILD_CITY)
        if validate_action(self.session.state, Action.build_road(coord)).is_valid:
            choices.append(ActionType.BUILD_ROAD)
        return choices

    def _cancel_panel(self) -> None:
        if self._panel_mode in {PANEL_BUILD_CONFIRM, PANEL_RESEARCH_CONFIRM}:
            self._panel_mode = PANEL_CITY
        elif self._panel_mode == PANEL_CITY:
            self._clear_selection()
        elif self._panel_mode == PANEL_TERRAIN:
            self._clear_selection()
        else:
            self._clear_selection()
        self.refresh(layout=True, recompose=True)

    def _clear_selection(self) -> None:
        self.session.state.message = ""
        self.session.state.selection.clear()
        self._panel_mode = PANEL_DEFAULT
        self._pending_building = None
        self._pending_tech = None

    def _apply_primary_panel_action(self) -> None:
        state = self.session.state
        if self._panel_mode == PANEL_TERRAIN:
            coord = state.selection.selected_coord
            if coord is None:
                return
            action = Action.build_city(coord) if self._terrain_choice is ActionType.BUILD_CITY else Action.build_road(coord)
            self._apply_action(action)
            return
        if self._panel_mode == PANEL_BUILD_CONFIRM:
            city_id = state.selection.selected_city_id
            if city_id is None or self._pending_building is None:
                return
            self._apply_action(Action.build_building(city_id, self._pending_building))
            return
        if self._panel_mode == PANEL_RESEARCH_CONFIRM:
            city_id = state.selection.selected_city_id
            if city_id is None or self._pending_tech is None:
                return
            self._apply_action(Action.research_tech(city_id, self._pending_tech))

    def _apply_action(self, action: Action) -> None:
        result = self.session.engine.apply_action(action)
        if result.success:
            self._clear_selection()
        self.query_one("#game-map", MapView).set_state(
            self.session.state,
            self.session.state.selection.selected_coord,
            interactive=self.session.policy is None,
        )
        self.refresh(layout=True, recompose=True)
        if self.session.state.is_game_over:
            self._stop_autoplay()
            self.app.complete_session(self.session)

    def _start_autoplay(self) -> None:
        interval_seconds = (
            DEFAULT_SPEED_REFRESH_MS / 1000
            if self.session.state.config.playback_mode is PlaybackMode.SPEED
            else DEFAULT_AUTOPLAY_INTERVAL_MS / 1000
        )
        self._autoplay_timer = self.set_interval(interval_seconds, self._advance_autoplay)

    def _stop_autoplay(self) -> None:
        if self._autoplay_timer is not None:
            self._autoplay_timer.stop()
            self._autoplay_timer = None

    def _advance_autoplay(self) -> None:
        if self.session.policy is None:
            return
        if self.session.state.is_game_over:
            self._stop_autoplay()
            self.app.complete_session(self.session)
            return

        steps = DEFAULT_SPEED_REFRESH_TURNS if self.session.state.config.playback_mode is PlaybackMode.SPEED else 1
        for _ in range(steps):
            if self.session.state.is_game_over:
                break
            action = self.session.policy.select_action(self.session.state)
            self.session.engine.apply_action(action)
            self._clear_selection()
            if self.session.state.config.playback_mode is not PlaybackMode.SPEED:
                break

        self.query_one("#game-map", MapView).set_state(
            self.session.state,
            self.session.state.selection.selected_coord,
            interactive=self.session.policy is None,
        )
        self.refresh(layout=True, recompose=True)
        if self.session.state.is_game_over:
            self._stop_autoplay()
            self.app.complete_session(self.session)


def _resource_type_for_building(building_type: BuildingType) -> ResourceType:
    if building_type is BuildingType.FARM:
        return ResourceType.FOOD
    if building_type is BuildingType.LUMBER_MILL:
        return ResourceType.WOOD
    if building_type is BuildingType.MINE:
        return ResourceType.ORE
    return ResourceType.SCIENCE
