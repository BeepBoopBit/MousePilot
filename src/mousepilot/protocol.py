"""Validated wire commands shared by the manual client and MCP adapter."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 1
VERSION = "0.1.0b0"
Coordinate = Annotated[int, Field(strict=True, ge=-100000, le=100000)]
Key = Literal[
    "enter",
    "tab",
    "escape",
    "backspace",
    "delete",
    "left",
    "right",
    "up",
    "down",
    "home",
    "end",
    "pageup",
    "pagedown",
    "space",
]
Button = Literal["left", "right", "middle"]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Info(Command):
    command: Literal["info"] = "info"


class DisplayList(Command):
    command: Literal["displays"] = "displays"
    aliases: dict[
        Annotated[str, Field(min_length=1, max_length=40)],
        Annotated[str, Field(min_length=1, max_length=128)],
    ] = Field(default_factory=dict, max_length=32)


class Overview(DisplayList):
    command: Literal["overview"] = "overview"
    width: Annotated[int, Field(ge=400, le=2560)] = 1600
    height: Annotated[int, Field(ge=300, le=1600)] = 1000


class Screen(DisplayList):
    command: Literal["screen"] = "screen"
    display_id: str = "primary"
    width: Annotated[int, Field(ge=100, le=8192)] = 1280
    grid: bool = False
    cursor_marker: bool = False


class Crop(Command):
    command: Literal["crop"] = "crop"
    frame: str
    x: Coordinate
    y: Coordinate
    width: Annotated[int, Field(ge=1, le=100000)]
    height: Annotated[int, Field(ge=1, le=100000)]
    output_width: Annotated[int, Field(ge=100, le=4096)] = 1280


class WindowList(Command):
    command: Literal["windows"] = "windows"
    title: Annotated[str, Field(max_length=200)] = ""
    frame: str | None = None


class WindowReference(Command):
    window_id: str


class Focus(WindowReference):
    command: Literal["focus"] = "focus"
    allow_input: bool = True


class WindowInfo(WindowReference):
    command: Literal["window_info"] = "window_info"


class WindowCapture(WindowReference):
    command: Literal["window_capture"] = "window_capture"
    width: Annotated[int, Field(ge=100, le=8192)] = 1280
    grid: bool = False
    cursor_marker: bool = False


class Point(Command):
    x: Coordinate
    y: Coordinate
    frame: str
    dry_run: bool = False


class Move(Point):
    command: Literal["move"] = "move"


class Click(Point):
    command: Literal["click"] = "click"
    button: Button = "left"
    count: Annotated[int, Field(ge=1, le=2)] = 1


class Scroll(Command):
    command: Literal["scroll"] = "scroll"
    steps: Annotated[int, Field(ge=-20, le=20)]
    axis: Literal["vertical", "horizontal"] = "vertical"


class TypeText(Command):
    command: Literal["type"] = "type"
    text: Annotated[str, Field(min_length=1, max_length=2000)]


class PressKey(Command):
    command: Literal["key"] = "key"
    key: Key


class Hotkey(Command):
    command: Literal["hotkey"] = "hotkey"
    keys: Annotated[list[str], Field(min_length=2, max_length=5)]


class Drag(Command):
    command: Literal["drag"] = "drag"
    from_x: Coordinate
    from_y: Coordinate
    to_x: Coordinate
    to_y: Coordinate
    frame: str
    to_frame: str | None = None
    duration: Annotated[float, Field(ge=0.1, le=5)] = 0.5
    button: Button = "left"


class Preview(Command):
    command: Literal["preview"] = "preview"
    frame: str
    x: Coordinate
    y: Coordinate
    radius: Annotated[int, Field(ge=16, le=300)] = 80


class ElementList(Command):
    command: Literal["elements"] = "elements"
    window_id: str
    frame: str
    limit: Annotated[int, Field(ge=1, le=150)] = 80


class ElementClick(Command):
    command: Literal["element_click"] = "element_click"
    element_id: str
    button: Button = "left"
    count: Annotated[int, Field(ge=1, le=2)] = 1


class Stop(Command):
    command: Literal["stop"] = "stop"


class Resume(Command):
    command: Literal["resume"] = "resume"


COMMANDS = TypeAdapter(
    Annotated[
        Info
        | DisplayList
        | Overview
        | Screen
        | Crop
        | WindowList
        | Focus
        | WindowInfo
        | WindowCapture
        | Move
        | Click
        | Scroll
        | TypeText
        | PressKey
        | Hotkey
        | Drag
        | Preview
        | ElementList
        | ElementClick
        | Stop
        | Resume,
        Field(discriminator="command"),
    ]
)


class ControlError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)
