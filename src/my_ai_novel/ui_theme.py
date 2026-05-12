from __future__ import annotations

import tkinter as tk
from tkinter import ttk


APP_BG = "#f3f6fb"
PANEL_BG = "#ffffff"
TEXT_BG = "#fbfcfe"
BORDER = "#d7deea"
PRIMARY = "#2563eb"
PRIMARY_DARK = "#1d4ed8"
PRIMARY_SOFT = "#dbeafe"
BUTTON_BG = "#eef4ff"
BUTTON_HOVER = "#dbeafe"
BUTTON_PRESSED = "#bfdbfe"
TEXT = "#172033"
MUTED = "#5f6f89"
STATUS_BG = "#e8eef9"
NAV_WIDTH = 168


def load_customtkinter():
    try:
        import customtkinter as ctk
    except ImportError as exc:
        raise RuntimeError(
            "CustomTkinter 未安装。请先运行：python -m pip install -r requirements.txt"
        ) from exc
    return ctk


def create_root(title: str) -> tk.Tk:
    ctk = load_customtkinter()
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    root.title(title)
    root.geometry("1220x800")
    root.minsize(1080, 680)
    return root


def apply_ttk_theme(root: tk.Tk) -> None:
    root.configure(fg_color=APP_BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", font=("Microsoft YaHei UI", 10), foreground=TEXT)
    style.configure("TFrame", background=APP_BG)
    style.configure("Panel.TFrame", background=PANEL_BG)
    style.configure("Header.TFrame", background=PANEL_BG)
    style.configure("TLabel", background=APP_BG, foreground=TEXT)
    style.configure("Panel.TLabel", background=PANEL_BG, foreground=TEXT)
    style.configure("Title.TLabel", background=PANEL_BG, foreground=TEXT, font=("Microsoft YaHei UI", 15, "bold"))
    style.configure("Subtitle.TLabel", background=PANEL_BG, foreground=MUTED, font=("Microsoft YaHei UI", 9))
    style.configure("Muted.TLabel", background=APP_BG, foreground=MUTED)
    style.configure("Status.TLabel", background=STATUS_BG, foreground=TEXT, padding=(10, 6))
    style.configure("TButton", padding=(10, 6), borderwidth=0, relief="flat", background=BUTTON_BG)
    style.map(
        "TButton",
        background=[("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER), ("!disabled", BUTTON_BG)],
        relief=[("pressed", "flat"), ("active", "flat"), ("!disabled", "flat")],
        foreground=[("disabled", MUTED), ("!disabled", TEXT)],
    )
    style.configure("Primary.TButton", foreground="#ffffff", background=PRIMARY)
    style.map("Primary.TButton", background=[("pressed", PRIMARY_DARK), ("active", PRIMARY_DARK)])
    style.configure("TEntry", fieldbackground="#ffffff", bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.configure("TCombobox", fieldbackground="#ffffff", bordercolor=BORDER)
    style.configure("TNotebook", background=APP_BG, borderwidth=0, tabmargins=(8, 8, 8, 0))
    style.layout("Hidden.TNotebook.Tab", [])
    style.configure("Hidden.TNotebook", background=APP_BG, borderwidth=0, tabmargins=0)
    style.layout(
        "TNotebook.Tab",
        [
            (
                "Notebook.tab",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Notebook.padding",
                            {
                                "side": "top",
                                "sticky": "nswe",
                                "children": [("Notebook.label", {"side": "top", "sticky": ""})],
                            },
                        )
                    ],
                },
            )
        ],
    )
    style.configure(
        "TNotebook.Tab",
        padding=(18, 9),
        background=BUTTON_BG,
        foreground=TEXT,
        borderwidth=0,
        relief="flat",
        focuscolor=APP_BG,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", PRIMARY), ("active", PRIMARY_SOFT), ("!selected", BUTTON_BG)],
        foreground=[("selected", "#ffffff"), ("active", PRIMARY_DARK), ("!selected", TEXT)],
        padding=[("selected", (18, 9)), ("active", (18, 9))],
        relief=[("selected", "flat"), ("active", "flat"), ("!selected", "flat")],
    )
    style.configure("TPanedwindow", background=APP_BG)


def create_navigation_button(parent: tk.Widget, text: str, command) -> tk.Widget:
    ctk = load_customtkinter()
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        width=140,
        height=38,
        corner_radius=10,
        anchor="w",
        border_width=0,
        fg_color="transparent",
        hover_color=BUTTON_HOVER,
        text_color=TEXT,
        font=("Microsoft YaHei UI", 13),
    )


def set_navigation_button_selected(button: tk.Widget, selected: bool) -> None:
    if selected:
        button.configure(fg_color=PRIMARY, hover_color=PRIMARY_DARK, text_color="#ffffff")
    else:
        button.configure(fg_color="transparent", hover_color=BUTTON_HOVER, text_color=TEXT)


def style_text_widget(widget: tk.Text) -> None:
    widget.configure(
        background=TEXT_BG,
        foreground=TEXT,
        insertbackground=TEXT,
        relief="solid",
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=PRIMARY,
        padx=8,
        pady=6,
        font=("Microsoft YaHei UI", 10),
    )


def style_listbox(widget: tk.Listbox) -> None:
    widget.configure(
        background="#ffffff",
        foreground=TEXT,
        selectbackground=PRIMARY,
        selectforeground="#ffffff",
        relief="solid",
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=PRIMARY,
        font=("Microsoft YaHei UI", 10),
        activestyle="none",
    )


def apply_interaction_cues(widget: tk.Widget) -> None:
    if isinstance(widget, ttk.Button):
        widget.configure(cursor="hand2")
    elif isinstance(widget, ttk.Notebook):
        widget.configure(cursor="hand2")
    elif isinstance(widget, ttk.Combobox):
        widget.configure(cursor="hand2")
