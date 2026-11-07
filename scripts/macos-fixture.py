"""Dedicated local window for native tests; does not inject input or require TCC."""

import json
import sys
from pathlib import Path

import AppKit as A
import Foundation as F
from PyObjCTools import AppHelper

state = {"clicks": 0, "submits": 0, "drags": 0, "vertical": 0, "horizontal": 0, "double_clicks": 0}
output = Path(sys.argv[1]).expanduser()
app = A.NSApplication.sharedApplication()
app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
# Cocoa routes Command shortcuts through menu key equivalents. A hand-built
# test app needs the standard Edit menu just like a normal application.
main_menu = A.NSMenu.alloc().init()
edit_item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Edit", None, "")
edit_menu = A.NSMenu.alloc().initWithTitle_("Edit")
for title, action, key in [
    ("Select All", "selectAll:", "a"),
    ("Copy", "copy:", "c"),
    ("Cut", "cut:", "x"),
    ("Paste", "paste:", "v"),
]:
    edit_menu.addItem_(A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key))
edit_item.setSubmenu_(edit_menu)
main_menu.addItem_(edit_item)
app.setMainMenu_(main_menu)

window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
    A.NSMakeRect(200, 250, 640, 420),
    A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskResizable,
    A.NSBackingStoreBuffered,
    False,
)
window.setTitle_("MousePilot macOS test target")


class Canvas(A.NSView):
    def acceptsFirstResponder(self):
        return True

    def drawRect_(self, rect):
        A.NSColor.windowBackgroundColor().set()
        A.NSRectFill(rect)
        A.NSColor.systemBlueColor().set()
        A.NSRectFill(A.NSMakeRect(40, 70, 220, 100))

    def mouseDown_(self, event):
        if event.clickCount() == 2:
            state["double_clicks"] += 1

    def mouseDragged_(self, event):
        state["drags"] += 1

    def scrollWheel_(self, event):
        state["vertical"] += event.scrollingDeltaY()
        state["horizontal"] += event.scrollingDeltaX()


class Target(F.NSObject):
    def clicked_(self, sender):
        state["clicks"] += 1

    def submitted_(self, sender):
        state["submits"] += 1

    def tick_(self, timer):
        state["text"] = str(field.stringValue())
        height = A.NSScreen.screens()[0].frame().size.height

        def point(x, y):
            p = window.convertPointToScreen_((x, y))
            return [round(p.x), round(height - p.y)]

        state["targets"] = {
            "input": point(200, 315),
            "button": point(120, 235),
            "drag": point(100, 120),
            "drag_end": point(210, 120),
        }
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(output)


canvas = Canvas.alloc().initWithFrame_(A.NSMakeRect(0, 0, 640, 420))
window.setContentView_(canvas)
target = Target.alloc().init()
field = A.NSTextField.alloc().initWithFrame_(A.NSMakeRect(40, 300, 540, 30))
field.setPlaceholderString_("MousePilot types here without Enter")
field.setTarget_(target)
field.setAction_("submitted:")
canvas.addSubview_(field)
button = A.NSButton.alloc().initWithFrame_(A.NSMakeRect(40, 220, 160, 30))
button.setTitle_("Test click")
button.setBezelStyle_(A.NSBezelStyleRounded)
button.setTarget_(target)
button.setAction_("clicked:")
canvas.addSubview_(button)
timer = F.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
    0.1, target, "tick:", None, True
)
window.makeKeyAndOrderFront_(None)
app.activateIgnoringOtherApps_(True)
AppHelper.runEventLoop()
