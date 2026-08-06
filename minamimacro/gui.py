from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from .color_detection import extract_palette_from_image
from .config_store import (
    build_config_payload,
    ensure_config_dir,
    load_config_bundle,
    save_config_bundle,
    settings_from_dict,
)
from .engine import MacroEngine
from .hotkeys import GlobalHotkey
from .models import ActionType, InputAction, MacroSettings
from .recorder import InputRecorder, capture_left_clicks


class MacroApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MinamiMacro")
        self.geometry("760x520")

        self._bg_main = "#181a1f"
        self._bg_panel = "#22252c"
        self._bg_input = "#2a2e36"
        self._bg_list = "#20242b"
        self._fg_main = "#e5e7eb"
        self._fg_muted = "#aab2bf"
        self._accent = "#3b82f6"
        self._accent_active = "#2563eb"

        self._control_regions: list[tuple[int, int, int, int]] = []
        self._focused_text_input_active = False
        self._queue_drag_index: int | None = None
        self._queue_drag_active = False

        self.recorder = InputRecorder(should_record_event=self._should_record_event)
        self.engine = MacroEngine()

        self._status_queue: queue.Queue[str] = queue.Queue()
        self.engine.set_status_callback(self._queue_status)

        self._capture_listener: Any = None
        self._corner_capture_listener: Any = None
        self._pending_corner_index: int | None = None
        self._queue_capture_enabled = False
        self.color_corner_1: tuple[int, int] | None = None
        self.color_corner_2: tuple[int, int] | None = None
        self.color_area: tuple[int, int, int, int] | None = None
        self.color_palette: list[tuple[int, int, int]] = []
        self.color_enabled_vars: list[tk.BooleanVar] = []
        self.color_swatch_widgets: list[tk.Widget] = []
        self.reference_image_path: Path | None = None

        self.hotkey_var = tk.StringVar(value="<ctrl>+<alt>+m")
        self.record_hotkey_var = tk.StringVar(value="<ctrl>+<alt>+r")
        self.cursor_speed_var = tk.StringVar(value="1200")
        self.cursor_speed_variation_var = tk.StringVar(value="0")
        self.action_delay_variation_ms_var = tk.StringVar(value="0")
        self.variation_x_var = tk.StringVar(value="3")
        self.variation_y_var = tk.StringVar(value="4")
        self.loop_delay_var = tk.StringVar(value="0.10")
        self.color_tolerance_var = tk.StringVar(value="15")
        self.delay_until_color_match_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Idle")
        self.target_var = tk.StringVar(value="0 queued pixel actions")
        self.color_area_var = tk.StringVar(value="No area selected")
        self.palette_var = tk.StringVar(value="No image colors loaded")
        self.drop_zone_var = tk.StringVar(value="Drop image")

        self.hotkey = GlobalHotkey(self.hotkey_var.get(), self._handle_hotkey_toggle)
        self.hotkey.start()
        self.record_hotkey = GlobalHotkey(self.record_hotkey_var.get(), self._handle_record_hotkey_toggle)
        self.record_hotkey.start()

        self._apply_dark_theme()
        self._build_ui()
        self.after(100, self._update_gui_capture_state)
        self.after(100, self._drain_status_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_dark_theme(self) -> None:
        self.configure(bg=self._bg_main)

        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=self._bg_main, foreground=self._fg_main)
        style.configure("TFrame", background=self._bg_main)
        style.configure("TLabel", background=self._bg_main, foreground=self._fg_main)
        style.configure("TLabelframe", background=self._bg_panel, bordercolor="#2f3440")
        style.configure("TLabelframe.Label", background=self._bg_panel, foreground=self._fg_main)
        style.configure("TButton", background="#2f3440", foreground=self._fg_main, bordercolor="#3a4150")
        style.map("TButton", background=[("active", self._accent_active), ("pressed", self._accent)])
        style.configure("TEntry", fieldbackground=self._bg_input, foreground=self._fg_main)
        style.configure("TCheckbutton", background=self._bg_panel, foreground=self._fg_main)
        style.map("TCheckbutton", background=[("active", self._bg_panel)])
        style.configure("Vertical.TScrollbar", background="#2f3440", troughcolor="#17191e")

    def _build_ui(self) -> None:
        root_container = ttk.Frame(self)
        root_container.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(root_container, highlightthickness=0, bg=self._bg_main)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(root_container, orient=tk.VERTICAL, command=self._canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        root = ttk.Frame(self._canvas, padding=12)
        self._canvas_window = self._canvas.create_window((0, 0), window=root, anchor="nw")
        root.bind("<Configure>", self._on_scrollable_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Support wheel scrolling on Linux and other platforms.
        self.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.bind_all("<Button-4>", self._on_mousewheel_linux, add="+")
        self.bind_all("<Button-5>", self._on_mousewheel_linux, add="+")

        controls = ttk.LabelFrame(root, text="Recording")
        controls.pack(fill=tk.X, pady=(0, 12))

        self.record_toggle_btn = ttk.Button(controls, text="Start Recording", command=self._toggle_recording)
        self.record_toggle_btn.pack(side=tk.LEFT, padx=6, pady=8)
        ttk.Button(controls, text="Clear", command=self._clear_recording).pack(side=tk.LEFT, padx=6, pady=8)
        ttk.Button(controls, text="Add Sleep Block", command=self._add_sleep_block).pack(side=tk.LEFT, padx=6, pady=8)

        action_list_frame = ttk.Frame(root)
        action_list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        action_list_scrollbar = ttk.Scrollbar(action_list_frame, orient=tk.VERTICAL)
        action_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.action_list = tk.Listbox(
            action_list_frame,
            height=10,
            selectmode=tk.EXTENDED,
            bg=self._bg_list,
            fg=self._fg_main,
            selectbackground=self._accent,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground="#323844",
            highlightcolor=self._accent,
            borderwidth=0,
            yscrollcommand=action_list_scrollbar.set,
        )
        self.action_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        action_list_scrollbar.configure(command=self.action_list.yview)
        self.action_list.bind("<Delete>", self._delete_selected_actions)
        self.action_list.bind("<ButtonPress-1>", self._on_queue_press)
        self.action_list.bind("<B1-Motion>", self._on_queue_drag)
        self.action_list.bind("<ButtonRelease-1>", self._on_queue_release)

        settings_frame = ttk.Frame(root)
        settings_frame.pack(fill=tk.X)

        left = ttk.LabelFrame(settings_frame, text="Target Pixel")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        ttk.Label(left, text="Target:").grid(row=0, column=0, sticky=tk.W, padx=6, pady=6)
        ttk.Label(left, textvariable=self.target_var).grid(row=0, column=1, sticky=tk.W, padx=6, pady=6)
        self.capture_btn = ttk.Button(left, text="Enable Pixel Queue Capture", command=self._toggle_queue_capture)
        self.capture_btn.grid(row=1, column=0, columnspan=2, padx=6, pady=6, sticky=tk.EW)
        ttk.Button(left, text="Clear Queued Pixel Actions", command=self._clear_target_queue).grid(
            row=2, column=0, columnspan=2, padx=6, pady=6, sticky=tk.EW
        )

        ttk.Label(left, text="Queued pixel clicks are merged into the main action queue.").grid(
            row=3, column=0, columnspan=2, sticky=tk.W, padx=6, pady=6
        )

        right = ttk.LabelFrame(settings_frame, text="Playback")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        ttk.Label(right, text="Cursor speed (px/s)").grid(row=0, column=0, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(right, textvariable=self.cursor_speed_var).grid(row=0, column=1, sticky=tk.EW, padx=6, pady=4)

        ttk.Label(right, text="Cursor speed variation (+/- px/s)").grid(row=1, column=0, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(right, textvariable=self.cursor_speed_variation_var).grid(row=1, column=1, sticky=tk.EW, padx=6, pady=4)

        ttk.Label(right, text="Action delay variation (+/- ms)").grid(row=2, column=0, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(right, textvariable=self.action_delay_variation_ms_var).grid(row=2, column=1, sticky=tk.EW, padx=6, pady=4)

        ttk.Label(right, text="Pixel variation X").grid(row=3, column=0, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(right, textvariable=self.variation_x_var).grid(row=3, column=1, sticky=tk.EW, padx=6, pady=4)

        ttk.Label(right, text="Pixel variation Y").grid(row=4, column=0, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(right, textvariable=self.variation_y_var).grid(row=4, column=1, sticky=tk.EW, padx=6, pady=4)

        ttk.Label(right, text="Loop delay (s)").grid(row=5, column=0, sticky=tk.W, padx=6, pady=4)
        ttk.Entry(right, textvariable=self.loop_delay_var).grid(row=5, column=1, sticky=tk.EW, padx=6, pady=4)

        right.grid_columnconfigure(1, weight=1)

        hotkey_frame = ttk.LabelFrame(root, text="Hotkey")
        hotkey_frame.pack(fill=tk.X, pady=(12, 12))
        ttk.Label(hotkey_frame, text="Macro start/stop").grid(row=0, column=0, padx=6, pady=6, sticky=tk.W)
        ttk.Entry(hotkey_frame, textvariable=self.hotkey_var, width=24).grid(row=0, column=1, padx=6, pady=6, sticky=tk.W)
        ttk.Label(hotkey_frame, text="Recording start/stop").grid(row=1, column=0, padx=6, pady=6, sticky=tk.W)
        ttk.Entry(hotkey_frame, textvariable=self.record_hotkey_var, width=24).grid(
            row=1, column=1, padx=6, pady=6, sticky=tk.W
        )
        ttk.Button(hotkey_frame, text="Apply Hotkeys", command=self._apply_hotkeys).grid(
            row=0, column=2, rowspan=2, padx=6, pady=6, sticky=tk.NS
        )

        config_frame = ttk.LabelFrame(root, text="Config")
        config_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Button(config_frame, text="Save Config", command=self._save_config).pack(side=tk.LEFT, padx=6, pady=8)
        ttk.Button(config_frame, text="Load Config", command=self._load_config).pack(side=tk.LEFT, padx=6, pady=8)
        ttk.Button(config_frame, text="Export Config", command=self._export_config).pack(side=tk.LEFT, padx=6, pady=8)
        ttk.Button(config_frame, text="Import Config", command=self._import_config).pack(side=tk.LEFT, padx=6, pady=8)

        color_frame = ttk.LabelFrame(root, text="Color Trigger")
        color_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Button(color_frame, text="Pick Corner 1", command=lambda: self._start_corner_pick(1)).grid(
            row=0, column=0, padx=6, pady=6, sticky=tk.W
        )
        ttk.Button(color_frame, text="Pick Corner 2", command=lambda: self._start_corner_pick(2)).grid(
            row=0, column=1, padx=6, pady=6, sticky=tk.W
        )
        ttk.Label(color_frame, textvariable=self.color_area_var).grid(row=0, column=2, padx=6, pady=6, sticky=tk.W)

        upload_and_drop = ttk.Frame(color_frame)
        upload_and_drop.grid(row=1, column=0, columnspan=2, padx=6, pady=6, sticky=tk.W)

        ttk.Button(upload_and_drop, text="Upload Reference Image", command=self._load_palette_image).pack(
            side=tk.LEFT
        )

        self.drop_zone = tk.Label(
            upload_and_drop,
            textvariable=self.drop_zone_var,
            relief=tk.GROOVE,
            bd=1,
            width=16,
            height=2,
            bg=self._bg_input,
            fg=self._fg_main,
            activebackground=self._bg_input,
            activeforeground=self._fg_main,
            cursor="hand2",
        )
        self.drop_zone.pack(side=tk.LEFT, padx=(8, 0))
        self.drop_zone.bind("<Button-1>", lambda _event: self._load_palette_image())
        self._setup_image_drop_zone()

        ttk.Label(color_frame, textvariable=self.palette_var).grid(row=1, column=2, padx=6, pady=6, sticky=tk.W)

        ttk.Label(color_frame, text="Color tolerance").grid(row=2, column=0, padx=6, pady=6, sticky=tk.W)
        ttk.Entry(color_frame, textvariable=self.color_tolerance_var, width=10).grid(
            row=2, column=1, padx=6, pady=6, sticky=tk.W
        )

        ttk.Label(color_frame, text="Loaded colors (tick to enable):").grid(
            row=3, column=0, padx=6, pady=(2, 4), sticky=tk.W
        )
        self.color_swatch_frame = ttk.Frame(color_frame)
        self.color_swatch_frame.grid(row=4, column=0, columnspan=3, padx=6, pady=(0, 6), sticky=tk.EW)

        ttk.Checkbutton(
            color_frame,
            text="Delay next inputs until this color trigger executes",
            variable=self.delay_until_color_match_var,
        ).grid(row=5, column=0, columnspan=3, padx=6, pady=6, sticky=tk.W)

        ttk.Button(color_frame, text="Add Color Trigger To Queue", command=self._add_color_trigger_to_queue).grid(
            row=6, column=0, padx=6, pady=6, sticky=tk.W
        )

        color_frame.grid_columnconfigure(2, weight=1)

        macro_controls = ttk.Frame(root)
        macro_controls.pack(fill=tk.X)
        ttk.Button(macro_controls, text="Start Macro", command=self._start_macro).pack(side=tk.LEFT, padx=6)
        ttk.Button(macro_controls, text="Stop Macro", command=self._stop_macro).pack(side=tk.LEFT, padx=6)
        ttk.Label(macro_controls, textvariable=self.status_var).pack(side=tk.RIGHT, padx=6)

    def _on_scrollable_frame_configure(self, _event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self._canvas.itemconfigure(self._canvas_window, width=event.width)

    def _is_pointer_over_widget(self, widget: tk.Widget) -> bool:
        if not widget.winfo_ismapped():
            return False
        pointer_x = self.winfo_pointerx()
        pointer_y = self.winfo_pointery()
        left = widget.winfo_rootx()
        top = widget.winfo_rooty()
        right = left + widget.winfo_width()
        bottom = top + widget.winfo_height()
        return left <= pointer_x <= right and top <= pointer_y <= bottom

    def _is_pointer_inside_window(self) -> bool:
        pointer_x = self.winfo_pointerx()
        pointer_y = self.winfo_pointery()
        return self.winfo_rootx() <= pointer_x <= self.winfo_rootx() + self.winfo_width() and self.winfo_rooty() <= pointer_y <= self.winfo_rooty() + self.winfo_height()

    def _on_mousewheel(self, event: tk.Event) -> None:
        if not self._is_pointer_inside_window():
            return
        delta = int(getattr(event, "delta", 0))
        if delta == 0:
            return
        wheel_units = int(-1 * (delta / 120))
        if self._is_pointer_over_widget(self.action_list):
            self.action_list.yview_scroll(wheel_units, "units")
            return
        self._canvas.yview_scroll(wheel_units, "units")

    def _on_mousewheel_linux(self, event: tk.Event) -> None:
        if not self._is_pointer_inside_window():
            return
        event_num = int(getattr(event, "num", 0))
        if self._is_pointer_over_widget(self.action_list):
            if event_num == 4:
                self.action_list.yview_scroll(-1, "units")
            elif event_num == 5:
                self.action_list.yview_scroll(1, "units")
            return
        if event_num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event_num == 5:
            self._canvas.yview_scroll(1, "units")

    def _start_corner_pick(self, corner_index: int) -> None:
        if self._queue_capture_enabled:
            self.status_var.set("Disable pixel queue capture before picking color area corners")
            return

        if self._corner_capture_listener is not None:
            self._corner_capture_listener.stop()
            self._corner_capture_listener = None

        self._pending_corner_index = corner_index
        self.status_var.set(f"Click anywhere to set corner {corner_index}")

        def _on_capture(x: int, y: int) -> None:
            self.after(0, lambda: self._set_corner_if_valid(x, y))

        self._corner_capture_listener = capture_left_clicks(_on_capture)

    def _set_corner_if_valid(self, x: int, y: int) -> None:
        if self._is_point_inside_gui(x, y):
            self.status_var.set("Ignored GUI click while waiting for corner pick")
            return

        if self._pending_corner_index == 1:
            self.color_corner_1 = (x, y)
            self.status_var.set(f"Corner 1 set to ({x}, {y})")
        elif self._pending_corner_index == 2:
            self.color_corner_2 = (x, y)
            self.status_var.set(f"Corner 2 set to ({x}, {y})")

        self._stop_corner_capture()
        self._update_color_area_from_corners()

    def _stop_corner_capture(self) -> None:
        if self._corner_capture_listener is not None:
            self._corner_capture_listener.stop()
        self._corner_capture_listener = None
        self._pending_corner_index = None

    def _update_color_area_from_corners(self) -> None:
        if self.color_corner_1 is None or self.color_corner_2 is None:
            if self.color_corner_1 is not None:
                self.color_area_var.set(f"Corner 1: ({self.color_corner_1[0]}, {self.color_corner_1[1]}), Corner 2: not set")
            elif self.color_corner_2 is not None:
                self.color_area_var.set(f"Corner 1: not set, Corner 2: ({self.color_corner_2[0]}, {self.color_corner_2[1]})")
            else:
                self.color_area_var.set("No area selected")
            return

        x1, y1 = self.color_corner_1
        x2, y2 = self.color_corner_2
        side = max(abs(x2 - x1), abs(y2 - y1))
        if side == 0:
            self.color_area = None
            self.color_area_var.set("Corners overlap, pick a different second corner")
            return

        x2 = x1 + side if x2 >= x1 else x1 - side
        y2 = y1 + side if y2 >= y1 else y1 - side
        area = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        self.color_area = area
        self.color_area_var.set(f"Area: ({area[0]}, {area[1]}) to ({area[2]}, {area[3]})")

    def _load_palette_image(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select reference image",
            filetypes=[("All files", "*.*"), ("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif;*.tiff")],
        )
        if not path:
            return

        self._apply_palette_image(path)

    def _setup_image_drop_zone(self) -> None:
        # If tkdnd is available on the system, enable native file drops.
        try:
            self.tk.call("package", "require", "tkdnd")
        except tk.TclError:
            self.drop_zone_var.set("Drop/click")
            return

        self.drop_zone.drop_target_register("DND_Files")
        self.drop_zone.dnd_bind("<<Drop>>", self._on_drop_zone_drop)
        self.drop_zone_var.set("Drop image")

    def _on_drop_zone_drop(self, event: tk.Event) -> str:
        data = str(getattr(event, "data", "")).strip()
        if not data:
            return "break"

        paths = self.tk.splitlist(data)
        if not paths:
            return "break"

        self._apply_palette_image(paths[0])
        return "break"

    def _apply_palette_image(self, path: str) -> None:
        image_path = Path(path)
        if not image_path.exists():
            messagebox.showerror("Image error", "Dropped file does not exist")
            return

        try:
            colors = extract_palette_from_image(image_path, max_colors=12)
        except Exception as exc:
            messagebox.showerror(
                "Image error",
                f"Could not decode this file into image colors: {exc}",
            )
            return

        if not colors:
            messagebox.showerror("Image error", "No colors found in image")
            return

        self.color_palette = colors
        self.color_enabled_vars = [tk.BooleanVar(value=True) for _ in self.color_palette]
        self._refresh_color_swatch_panel()
        self.reference_image_path = image_path
        self.palette_var.set(f"Loaded {len(colors)} colors from image ({len(self._selected_palette_colors())} enabled)")
        self.drop_zone_var.set("Drop image")
        self.status_var.set("Reference colors loaded")

    def _refresh_color_swatch_panel(self) -> None:
        for widget in self.color_swatch_widgets:
            widget.destroy()
        self.color_swatch_widgets.clear()

        if not self.color_palette:
            empty_label = ttk.Label(self.color_swatch_frame, text="No colors loaded")
            empty_label.grid(row=0, column=0, sticky=tk.W)
            self.color_swatch_widgets.append(empty_label)
            return

        columns = 3
        for idx, color in enumerate(self.color_palette):
            row = idx // columns
            col = idx % columns
            container = ttk.Frame(self.color_swatch_frame)
            container.grid(row=row, column=col, padx=4, pady=3, sticky=tk.W)

            swatch = tk.Label(
                container,
                width=2,
                height=1,
                bg=f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
                relief=tk.RIDGE,
                bd=1,
            )
            swatch.pack(side=tk.LEFT)

            check = ttk.Checkbutton(
                container,
                text=f"RGB {color}",
                variable=self.color_enabled_vars[idx],
            )
            check.pack(side=tk.LEFT, padx=(4, 0))

            self.color_swatch_widgets.extend([container, swatch, check])

    def _selected_palette_colors(self) -> list[tuple[int, int, int]]:
        selected: list[tuple[int, int, int]] = []
        for idx, color in enumerate(self.color_palette):
            if idx < len(self.color_enabled_vars) and self.color_enabled_vars[idx].get():
                selected.append(color)
        return selected

    def _add_color_trigger_to_queue(self) -> None:
        if self.color_area is None:
            messagebox.showerror("Color trigger", "Select a square area first")
            return

        if not self.color_palette:
            messagebox.showerror("Color trigger", "Upload a reference image first")
            return

        selected_colors = self._selected_palette_colors()
        if not selected_colors:
            messagebox.showerror("Color trigger", "Enable at least one loaded color")
            return

        try:
            tolerance = max(0, int(self.color_tolerance_var.get()))
        except ValueError:
            messagebox.showerror("Color trigger", "Color tolerance must be an integer")
            return

        self.recorder.actions.append(
            InputAction(
                delay=0.0,
                action_type=ActionType.COLOR_TRIGGER,
                payload={
                    "area": list(self.color_area),
                    "colors": [list(color) for color in selected_colors],
                    "tolerance": tolerance,
                    "block_until_match": self.delay_until_color_match_var.get(),
                },
            )
        )
        self._refresh_action_list()
        self.status_var.set("Color trigger added to queue")

    def _queue_status(self, message: str) -> None:
        self._status_queue.put(message)

    def _update_gui_capture_state(self) -> None:
        self.update_idletasks()
        control_regions: list[tuple[int, int, int, int]] = []
        for widget in self._iter_widgets(self):
            if not self._is_recording_control_widget(widget):
                continue
            if not widget.winfo_ismapped():
                continue
            left = widget.winfo_rootx()
            top = widget.winfo_rooty()
            right = left + widget.winfo_width()
            bottom = top + widget.winfo_height()
            control_regions.append((left, top, right, bottom))

        self._control_regions = control_regions

        focused_widget = self.focus_get()
        self._focused_text_input_active = bool(focused_widget and self._is_text_input_widget(focused_widget))
        self.after(100, self._update_gui_capture_state)

    def _iter_widgets(self, parent: tk.Misc) -> list[tk.Misc]:
        widgets: list[tk.Misc] = []
        stack = list(parent.winfo_children())
        while stack:
            widget = stack.pop()
            widgets.append(widget)
            stack.extend(widget.winfo_children())
        return widgets

    def _is_recording_control_widget(self, widget: tk.Misc) -> bool:
        class_name = widget.winfo_class()
        return class_name in {
            "TButton",
            "Button",
            "TEntry",
            "Entry",
            "TCheckbutton",
            "Checkbutton",
            "Listbox",
            "Scrollbar",
            "TScrollbar",
            "Text",
            "Spinbox",
            "TCombobox",
            "Combobox",
            "Scale",
            "TScale",
        }

    def _is_text_input_widget(self, widget: tk.Misc) -> bool:
        return widget.winfo_class() in {
            "TEntry",
            "Entry",
            "Text",
            "Spinbox",
            "TCombobox",
            "Combobox",
        }

    def _point_inside_control_region(self, x: int, y: int) -> bool:
        for left, top, right, bottom in self._control_regions:
            if left <= x <= right and top <= y <= bottom:
                return True
        return False

    def _should_record_event(self, action_type: ActionType, payload: dict) -> bool:
        if action_type in (ActionType.MOUSE_CLICK, ActionType.MOUSE_SCROLL):
            return not self._point_inside_control_region(int(payload.get("x", 0)), int(payload.get("y", 0)))
        if action_type in (ActionType.KEY_DOWN, ActionType.KEY_UP):
            return not self._focused_text_input_active
        return True

    def _drain_status_queue(self) -> None:
        while not self._status_queue.empty():
            self.status_var.set(self._status_queue.get())
        self.after(100, self._drain_status_queue)

    def _refresh_action_list(self) -> None:
        self.action_list.delete(0, tk.END)
        for i, action in enumerate(self.recorder.actions, start=1):
            self.action_list.insert(
                tk.END,
                f"........ {i:03d} | {action.action_type.value:12s} | delay={action.delay:.3f}s | {action.payload}",
            )
        self.target_var.set(f"{self._queued_target_count()} queued pixel actions")

    def _on_queue_press(self, event: tk.Event) -> str | None:
        # Only begin drag-reorder when pointer is in the left "8 dots" handle area.
        if int(getattr(event, "x", 0)) > 64:
            self._queue_drag_index = None
            self._queue_drag_active = False
            return None

        index = int(self.action_list.nearest(int(getattr(event, "y", 0))))
        if index < 0 or index >= len(self.recorder.actions):
            return None

        self._queue_drag_index = index
        self._queue_drag_active = True
        self.action_list.selection_clear(0, tk.END)
        self.action_list.selection_set(index)
        self.action_list.activate(index)
        return "break"

    def _on_queue_drag(self, event: tk.Event) -> str | None:
        if not self._queue_drag_active or self._queue_drag_index is None:
            return None

        target_index = int(self.action_list.nearest(int(getattr(event, "y", 0))))
        if target_index < 0 or target_index >= len(self.recorder.actions):
            return "break"

        if target_index == self._queue_drag_index:
            return "break"

        action = self.recorder.actions.pop(self._queue_drag_index)
        self.recorder.actions.insert(target_index, action)
        self._queue_drag_index = target_index

        self._refresh_action_list()
        self.action_list.selection_clear(0, tk.END)
        self.action_list.selection_set(target_index)
        self.action_list.activate(target_index)
        self.status_var.set(f"Moved action to position {target_index + 1}")
        return "break"

    def _on_queue_release(self, _event: tk.Event) -> str | None:
        if not self._queue_drag_active:
            return None
        self._queue_drag_active = False
        self._queue_drag_index = None
        return "break"

    def _queued_target_count(self) -> int:
        return sum(1 for action in self.recorder.actions if action.action_type == ActionType.TARGET_CLICK)

    def _delete_selected_actions(self, _event: tk.Event | None = None) -> str | None:
        selected = list(self.action_list.curselection())
        if not selected:
            return None
        for index in sorted(selected, reverse=True):
            if 0 <= index < len(self.recorder.actions):
                del self.recorder.actions[index]
        self._refresh_action_list()
        self.status_var.set(f"Deleted {len(selected)} action(s)")
        return "break"

    def _toggle_recording(self) -> None:
        if self.recorder.is_running:
            self._stop_recording()
        else:
            self._start_recording()

    def _handle_record_hotkey_toggle(self) -> None:
        self.after(0, self._toggle_recording)

    def _start_recording(self) -> None:
        self.recorder.start()
        self.record_toggle_btn.configure(text="Stop Recording")
        self.status_var.set("Recording inputs")

    def _stop_recording(self) -> None:
        self.recorder.stop()
        self.record_toggle_btn.configure(text="Start Recording")
        self._refresh_action_list()
        self.status_var.set(f"Recorded {len(self.recorder.actions)} actions")

    def _clear_recording(self) -> None:
        self.recorder.clear()
        self.record_toggle_btn.configure(text="Start Recording")
        self._refresh_action_list()
        self.status_var.set("Recording cleared")

    def _add_sleep_block(self) -> None:
        milliseconds = simpledialog.askinteger(
            "Add sleep block",
            "Sleep duration in milliseconds:",
            parent=self,
            minvalue=0,
            initialvalue=500,
        )
        if milliseconds is None:
            return

        self.recorder.actions.append(
            InputAction(
                delay=0.0,
                action_type=ActionType.SLEEP,
                payload={"milliseconds": int(milliseconds)},
            )
        )
        self._refresh_action_list()
        self.status_var.set(f"Added sleep block: {milliseconds} ms")

    def _toggle_queue_capture(self) -> None:
        if self._queue_capture_enabled:
            self._stop_queue_capture()
            return

        self.status_var.set("Queue capture enabled: each left click adds a loop target")

        def _on_capture(x: int, y: int) -> None:
            self.after(0, lambda: self._add_target_pixel(x, y))

        self._capture_listener = capture_left_clicks(_on_capture)
        self._queue_capture_enabled = True
        self.capture_btn.configure(text="Disable Pixel Queue Capture")

    def _stop_queue_capture(self) -> None:
        if self._capture_listener is not None:
            self._capture_listener.stop()
            self._capture_listener = None
        self._queue_capture_enabled = False
        self.capture_btn.configure(text="Enable Pixel Queue Capture")
        self.status_var.set("Queue capture disabled")

    def _add_target_pixel(self, x: int, y: int) -> None:
        if self._is_point_inside_gui(x, y):
            self.status_var.set("Ignored click on GUI while queue capture is enabled")
            return

        self.recorder.actions.append(
            InputAction(
                delay=0.0,
                action_type=ActionType.TARGET_CLICK,
                payload={"x": x, "y": y},
            )
        )
        self._refresh_action_list()
        self.status_var.set(f"Queued pixel action ({x}, {y})")

    def _is_point_inside_gui(self, x: int, y: int) -> bool:
        return self._point_inside_control_region(x, y)

    def _clear_target_queue(self) -> None:
        self.recorder.actions = [
            action for action in self.recorder.actions if action.action_type != ActionType.TARGET_CLICK
        ]
        self._refresh_action_list()
        self.status_var.set("Queued pixel actions removed")

    def _read_settings(self) -> MacroSettings:
        try:
            speed = float(self.cursor_speed_var.get())
            speed_variation = max(0.0, float(self.cursor_speed_variation_var.get()))
            action_delay_variation_ms = max(0.0, float(self.action_delay_variation_ms_var.get()))
            variation_x = max(0, int(self.variation_x_var.get()))
            variation_y = max(0, int(self.variation_y_var.get()))
            loop_delay = max(0.0, float(self.loop_delay_var.get()))
        except ValueError as exc:
            raise ValueError(
                "Enter valid numeric values for speed/speed variation/action delay variation/pixel variation/loop delay"
            ) from exc

        return MacroSettings(
            cursor_speed=speed,
            cursor_speed_variation=speed_variation,
            action_delay_variation_ms=action_delay_variation_ms,
            variation_x=variation_x,
            variation_y=variation_y,
            loop_delay=loop_delay,
        )

    def _config_payload(self) -> dict[str, Any]:
        settings = self._read_settings()
        payload = build_config_payload(self.recorder.actions, settings, self.hotkey_var.get().strip())
        payload["record_hotkey"] = self.record_hotkey_var.get().strip()
        payload["color_config"] = {
            "corner_1": list(self.color_corner_1) if self.color_corner_1 is not None else None,
            "corner_2": list(self.color_corner_2) if self.color_corner_2 is not None else None,
            "area": list(self.color_area) if self.color_area is not None else None,
            "palette": [list(color) for color in self.color_palette],
            "palette_enabled": [var.get() for var in self.color_enabled_vars],
            "tolerance": int(self.color_tolerance_var.get() or 15),
            "block_until_match": self.delay_until_color_match_var.get(),
        }
        return payload

    def _apply_config_payload(self, payload: dict[str, Any], reference_image_path: Path | None = None) -> None:
        settings = settings_from_dict(dict(payload.get("settings", {})))

        self.cursor_speed_var.set(str(settings.cursor_speed))
        self.cursor_speed_variation_var.set(str(settings.cursor_speed_variation))
        self.action_delay_variation_ms_var.set(str(settings.action_delay_variation_ms))
        self.variation_x_var.set(str(settings.variation_x))
        self.variation_y_var.set(str(settings.variation_y))
        self.loop_delay_var.set(str(settings.loop_delay))

        raw_actions = payload.get("actions", [])
        loaded_actions: list[InputAction] = []
        for item in raw_actions:
            try:
                loaded_actions.append(
                    InputAction(
                        delay=float(item.get("delay", 0.0)),
                        action_type=ActionType(item["action_type"]),
                        payload=dict(item.get("payload", {})),
                    )
                )
            except Exception:
                continue

        self.recorder.actions = loaded_actions
        self._refresh_action_list()

        hotkey = str(payload.get("hotkey", "")).strip()
        if hotkey:
            self.hotkey_var.set(hotkey)
            self.hotkey.update_hotkey(hotkey, self._handle_hotkey_toggle)

        record_hotkey = str(payload.get("record_hotkey", "")).strip()
        if record_hotkey:
            self.record_hotkey_var.set(record_hotkey)
            self.record_hotkey.update_hotkey(record_hotkey, self._handle_record_hotkey_toggle)

        color_config = payload.get("color_config", {}) if isinstance(payload.get("color_config", {}), dict) else {}
        corner_1 = color_config.get("corner_1")
        corner_2 = color_config.get("corner_2")
        area = color_config.get("area")
        palette = color_config.get("palette", [])
        palette_enabled = color_config.get("palette_enabled", [])

        self.color_corner_1 = tuple(corner_1) if isinstance(corner_1, list) and len(corner_1) == 2 else None
        self.color_corner_2 = tuple(corner_2) if isinstance(corner_2, list) and len(corner_2) == 2 else None
        self.color_area = tuple(area) if isinstance(area, list) and len(area) == 4 else None
        self.color_palette = [tuple(color[:3]) for color in palette if isinstance(color, list) and len(color) >= 3]
        self.color_enabled_vars = []
        for idx in range(len(self.color_palette)):
            enabled = True
            if isinstance(palette_enabled, list) and idx < len(palette_enabled):
                enabled = bool(palette_enabled[idx])
            self.color_enabled_vars.append(tk.BooleanVar(value=enabled))
        self._refresh_color_swatch_panel()

        self.color_tolerance_var.set(str(int(color_config.get("tolerance", 15))))
        self.delay_until_color_match_var.set(bool(color_config.get("block_until_match", True)))

        if self.color_area is not None:
            self.color_area_var.set(
                f"Area: ({self.color_area[0]}, {self.color_area[1]}) to ({self.color_area[2]}, {self.color_area[3]})"
            )
        else:
            self._update_color_area_from_corners()

        if self.color_palette:
            selected_count = len(self._selected_palette_colors())
            self.palette_var.set(f"Loaded {len(self.color_palette)} colors from image ({selected_count} enabled)")
        else:
            self.palette_var.set("No image colors loaded")

        self.reference_image_path = reference_image_path

    def _save_config(self) -> None:
        name = simpledialog.askstring("Save config", "Config name:", parent=self)
        if not name:
            return
        folder_name = name.strip().replace(" ", "_")
        if not folder_name:
            return
        config_dir = ensure_config_dir()
        bundle_dir = config_dir / folder_name

        try:
            payload = self._config_payload()
            save_config_bundle(bundle_dir, payload, self.reference_image_path)
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("Save failed", f"Could not save config: {exc}")
            return

        self.status_var.set(f"Saved config bundle to {bundle_dir.name}")

    def _load_config(self) -> None:
        config_dir = ensure_config_dir()
        path_str = filedialog.askdirectory(
            parent=self,
            title="Load config bundle",
            initialdir=str(config_dir),
        )
        if not path_str:
            return

        path = Path(path_str)
        try:
            payload, image_path = load_config_bundle(path)
            self._apply_config_payload(payload, image_path)
        except Exception as exc:
            messagebox.showerror("Load failed", f"Could not load config: {exc}")
            return

        self.status_var.set(f"Loaded config bundle from {path.name}")

    def _export_config(self) -> None:
        target_root = filedialog.askdirectory(
            parent=self,
            title="Choose export folder",
        )
        if not target_root:
            return

        name = simpledialog.askstring("Export config", "Bundle folder name:", parent=self)
        if not name:
            return
        folder_name = name.strip().replace(" ", "_")
        if not folder_name:
            return

        bundle_dir = Path(target_root) / folder_name

        try:
            payload = self._config_payload()
            save_config_bundle(bundle_dir, payload, self.reference_image_path)
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("Export failed", f"Could not export config: {exc}")
            return

        self.status_var.set(f"Config exported to {bundle_dir}")

    def _import_config(self) -> None:
        path_str = filedialog.askdirectory(
            parent=self,
            title="Import config bundle",
        )
        if not path_str:
            return

        path = Path(path_str)
        try:
            payload, image_path = load_config_bundle(path)
            self._apply_config_payload(payload, image_path)
        except Exception as exc:
            messagebox.showerror("Import failed", f"Could not import config: {exc}")
            return

        self.status_var.set(f"Imported config bundle from {path.name}")

    def _start_macro(self) -> None:
        try:
            settings = self._read_settings()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self.engine.update(self.recorder.actions, settings)
        self.engine.start()

    def _stop_macro(self) -> None:
        self.engine.stop()

    def _handle_hotkey_toggle(self) -> None:
        self.after(0, self._toggle_macro)

    def _toggle_macro(self) -> None:
        if self.engine.is_running:
            self._stop_macro()
        else:
            self._start_macro()

    def _apply_hotkeys(self) -> None:
        macro_hotkey = self.hotkey_var.get().strip()
        record_hotkey = self.record_hotkey_var.get().strip()
        if not macro_hotkey or not record_hotkey:
            messagebox.showerror("Invalid hotkey", "Hotkeys cannot be empty")
            return

        try:
            self.hotkey.update_hotkey(macro_hotkey, self._handle_hotkey_toggle)
            self.record_hotkey.update_hotkey(record_hotkey, self._handle_record_hotkey_toggle)
        except Exception as exc:
            messagebox.showerror("Invalid hotkey", f"Could not parse hotkey: {exc}")
            return

        self.status_var.set(f"Hotkeys set: macro={macro_hotkey}, recording={record_hotkey}")

    def _on_close(self) -> None:
        self._stop_corner_capture()
        self._stop_queue_capture()
        self.recorder.stop()
        self.engine.stop()
        self.engine.close()
        self.hotkey.stop()
        self.record_hotkey.stop()
        self.destroy()
