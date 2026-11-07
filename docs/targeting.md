# Reliable targeting

Mouse tools take coordinates in the **returned screenshot**, never desktop or
window coordinates. A 1920×1200 display returned as 1280×800 has valid coordinates
`x=0..1279`, `y=0..799`. MousePilot maps them to the desktop automatically.

Screenshots include `valid_coordinates`, explicit coordinate spaces, and a null
`cursor.image` when the cursor is outside the capture. Action results distinguish
`target_image`, `target_desktop`, and `cursor_desktop`. `executed: true` means
input was sent; it does not prove that a window closed or a button worked.

## Focus a window

`focus_window` first requests native activation. If Windows refuses, it may send
one stationary click on a visible title bar or straight resize border. Native hit
testing verifies the target belongs to that window and is not editor content,
caption buttons, or resize corners. Ownership and geometry are checked again
before clicking, and success requires confirmed foreground focus. A border click
uses no drag motion. The pointer moves; capture again after activation.

If no safe frame point is visible, MousePilot can send Alt+Escape once, then
request the exact target window and verify its foreground state. This may briefly
activate another window; it does not type text or press Enter.

Results report `focus_method` and `activation_click`. Set `allow_input=false`
(or CLI `focus WINDOW_ID --no-input`) for API-only activation without clicks or shortcuts.
Windows restrictions can still prevent activation.
On failure, follow the error's visual targeting guidance instead of repeating
`focus_window` or attempting `capture_window` before focus is established.

## Capture a specific window

Use `list_windows` to select a window ID, then `get_window_info(window_id)` for
its current desktop `x`, `y`, `width`, `height`, foreground/minimized state,
and monitor IDs. `display_id` is the monitor with the largest overlap;
`display_ids` includes every intersected monitor. These dimensions are desktop
units (physical pixels on Windows, points on macOS), not click coordinates.
`list_windows` also provides `position_desktop` and `size_desktop`; its
`bounds` array is `[left, top, right, bottom]`, never `[x, y, width, height]`.

Call `focus_window`, then `capture_window(window_id)`. The returned image is the
visible desktop region clipped to that window and the desktop bounds. Other
windows overlapping it can appear; this does not capture hidden window content.
Partly offscreen windows are clipped, so use returned image pixels rather than
adding window offsets yourself. Capture does not activate or restore windows.

Window screenshots and their derived crops/previews reject input after the
window moves, resizes, minimizes, closes, changes identity or loses foreground
focus. Focus and capture again before continuing. Checks cannot prevent a UI
change in the short interval between validation and input.

```sh
mousepilot --device windows window-info WINDOW_ID
mousepilot --device windows window-capture WINDOW_ID --output captures/window.png
```

## Prefer named controls on Windows

1. Call `list_windows`, then `focus_window` with the intended window ID.
2. Capture `current_screen` for the monitor containing that window.
3. Call `list_elements(window_id, screenshot_id)`.
4. Pick the named control, such as `Close`, and pass its `element_id` to
   `click_element`.
5. Capture again to verify the result.

Discovery returns an annotated screenshot with numbered boxes, names, roles,
and image bounds. It uses Windows UI Automation, without OCR or reading field
values. Coverage depends on the application. An empty result or an unavailable provider
returns a fresh window screenshot with `interaction_mode="visual"` and explicit
preview/click/type guidance. A partial list may expose window buttons while
custom editor fields are absent; use the image for those missing fields.
Discovery never clicks or types automatically. A control that fails click-time
revalidation remains an error and is not automatically clicked by coordinates. Focus and screenshot selection
remain explicit; discovery does not silently activate another window.

Element references expire after 120 seconds and retain at most 512 observations.
Clicking rechecks window identity, foreground focus, control identity, bounds,
and the control at the target point before sending a native mouse click. A
changed or covered control is rejected; discover it again. UI changes between
the final check and input remain possible.

Window IDs are temporary observation tokens. A different ID in the next window
listing does **not** establish that the application reopened.

## Preview visual targets

For custom controls or macOS, call `preview_target(x, y, screenshot_id)` first.
It returns a fresh screenshot marked with a crosshair and a magnified detail.
It never moves the mouse or clicks. Use the **new** screenshot ID and
`target_image` for the eventual click. The magnified detail has no actionable
coordinate system; use `crop_screen` for an actionable zoomed screenshot.

`list_windows(screenshot_id=...)` also returns clipped `image_bounds` alongside
its desktop bounds. Those bounds describe the window, not individual buttons.
Do not infer an exact Close location solely from the window's right edge.

CLI equivalents:

```sh
mousepilot --device windows preview 400 200 --frame SCREENSHOT_ID
mousepilot --device windows elements WINDOW_ID --frame SCREENSHOT_ID
mousepilot --device windows element-click ELEMENT_ID
```

Out-of-bounds errors report the valid screenshot range and send no input.
On backend input errors, stop and inspect the device state rather than retrying
nearby coordinates. If the model cannot see images, fix the client image path
before attempting visual targeting; see [llama.cpp setup](llama-cpp.md).
