"""Main-thread Cocoa event loop and local macOS menu controls."""

import signal
import threading


def call_main(function):
    if threading.current_thread() is threading.main_thread():
        return function()
    from PyObjCTools import AppHelper

    done = threading.Event()
    result = {}

    def invoke():
        try:
            result["value"] = function()
        except Exception as exc:
            result["error"] = exc
        finally:
            done.set()

    AppHelper.callAfter(invoke)
    if not done.wait(5):
        raise RuntimeError("macOS main thread did not respond")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def run(controller, server, tray):
    import AppKit
    import Foundation
    import objc
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    class MenuActions(Foundation.NSObject):
        @objc.IBAction
        def pause_(self, sender):
            controller.desktop.stopped.set()
            controller.desktop.release_all()

        @objc.IBAction
        def resume_(self, sender):
            controller.desktop.stopped.clear()

        @objc.IBAction
        def permissions_(self, sender):
            controller.desktop.request_permissions()

        @objc.IBAction
        def quit_(self, sender):
            controller.desktop.stopped.set()
            threading.Thread(target=shutdown, daemon=True).start()

    def shutdown():
        server.shutdown()
        AppHelper.callAfter(AppHelper.stopEventLoop)

    target = MenuActions.alloc().init()
    item = None
    if tray:
        item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        item.button().setTitle_("MousePilot")
        menu = AppKit.NSMenu.alloc().init()
        for title, action in [
            ("Pause input", "pause:"),
            ("Resume input", "resume:"),
            ("Grant permissions…", "permissions:"),
            ("Quit MousePilot", "quit:"),
        ]:
            entry = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            entry.setTarget_(target)
            menu.addItem_(entry)
        item.setMenu_(menu)

    def terminate(signum, frame):
        controller.desktop.stopped.set()
        threading.Thread(target=shutdown, daemon=True).start()

    previous_term = signal.signal(signal.SIGTERM, terminate)
    worker = threading.Thread(target=server.serve_forever, daemon=True, name="mousepilot-http")
    worker.start()
    try:
        AppHelper.runEventLoop(installInterrupt=True)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        server.shutdown()
        worker.join(timeout=5)
        if item:
            AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(item)
