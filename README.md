# minamimacro

A simple Python macro GUI client with recording and playback for keyboard/mouse input.

## Features

- Record and replay keyboard and mouse input
- Capture multiple target pixels directly into the main action queue
- Adjustable cursor speed for macro mouse movement
- Cursor speed variation per move
- Random click variation around target pixel (X/Y range)
- Configurable global hotkey to start/stop the macro
- Configurable global hotkey to start/stop recording
- Save and load local configs from the project configs folder
- Export and import bundled config folders (config.json + optional image)
- Delete selected queue entries with Del
- Color recognition trigger from a square area defined by two picked corners
- Upload an image to extract recognition colors
- Queue color triggers that can block later inputs until matched
- Add sleep blocks in milliseconds to pause queue execution

## Install

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python run.py
```

## Wayland Note

On Wayland, synthetic keyboard injection is restricted. The app auto-tries a uinput backend for key playback.

If keystrokes still do not execute, ensure uinput is enabled and your user can access it:

```bash
sudo modprobe uinput
sudo usermod -aG input "$USER"
```

Then log out and log back in.

If uinput cannot be used, the app falls back to pynput keyboard injection, which may be blocked by Wayland.

## Usage

1. Use the single Start Recording / Stop Recording toggle button to record keyboard/mouse actions.
2. Click Enable Pixel Queue Capture.
3. While capture is enabled, each left click outside the GUI is appended as a queued pixel click action in the main action list.
4. Click Disable Pixel Queue Capture when done.
5. Configure:
	 - Cursor speed (pixels per second)
	 - Cursor speed variation (+/- px/s)
	 - Pixel variation X/Y for randomized target clicks
	 - Loop delay
6. Set your macro and recording global hotkeys (example: `<ctrl>+<alt>+m` and `<ctrl>+<alt>+r`) and click Apply Hotkeys.
7. Use Save Config / Load Config for local presets in the configs folder.
8. Use Export Config / Import Config to move bundled config folders between folders or machines.
9. Start the macro from the button or by using your global hotkey.
10. Select one or more queue items and press Del to remove them.
10. Use Add Sleep Block to insert a millisecond pause action in the queue.
11. For color-based execution:
	 - Click Pick Corner 1 and then Pick Corner 2 to define the square region.
	 - Click Upload Reference Image to extract colors used for recognition (file picker accepts any file type).
	 - Tick on/off the loaded color squares to choose which colors are used for recognition.
	 - Set Color tolerance and choose whether to delay later inputs until color match.
	 - Click Add Color Trigger To Queue to insert this condition in the macro queue.

## Config Files

- Local configs are stored in the configs folder.
- Each config is stored as a bundle folder containing config.json and optional reference image(s).

All code licensed under MIT.
