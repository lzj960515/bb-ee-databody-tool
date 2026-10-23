"""主窗口与弹窗共用的颜色、字体和 ttk 样式。"""
from __future__ import annotations

import tkinter as tk
from tkinter import font, ttk


BACKGROUND = "#F4F6FA"
SURFACE = "#FFFFFF"
INK = "#142337"
TEXT = "#26384C"
MUTED = "#64748B"
BORDER = "#DCE3EC"
ACCENT = "#0B897B"
ACCENT_HOVER = "#087568"
ACCENT_SOFT = "#E3F3EF"


def configure_theme(root: tk.Tk) -> str:
    """初始化整套桌面样式，并返回实际可用的中文字体。"""
    available = set(font.families(root))
    family = next((name for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
                   if name in available), "TkDefaultFont")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkTooltipFont"):
        font.nametofont(name, root=root).configure(family=family, size=10)
    root.configure(background=BACKGROUND)
    root.option_add("*TCombobox*Listbox.font", (family, 10))
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", SURFACE)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BACKGROUND, foreground=TEXT, font=(family, 10),
                    bordercolor=BORDER, lightcolor=SURFACE, darkcolor=BORDER)
    style.configure("TFrame", background=BACKGROUND)
    style.configure("TLabel", background=BACKGROUND, foreground=TEXT)
    style.configure("Header.TFrame", background=INK)
    style.configure("Header.TLabel", background=INK, foreground=SURFACE)
    style.configure("HeaderTitle.TLabel", background=INK, foreground=SURFACE, font=(family, 22, "bold"))
    style.configure("HeaderSubtitle.TLabel", background=INK, foreground="#C6D3E2", font=(family, 10))
    style.configure("Title.TLabel", foreground=INK, font=(family, 21, "bold"))
    style.configure("Subtitle.TLabel", foreground=MUTED, font=(family, 10))
    style.configure("Chain.TLabel", foreground=ACCENT, font=(family, 11, "bold"))
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("Card.TLabel", background=SURFACE, foreground=TEXT)
    style.configure("CardTitle.TLabel", background=SURFACE, foreground=INK, font=(family, 12, "bold"))
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("Selection.TLabel", background=SURFACE, foreground=INK, font=(family, 14, "bold"))
    style.configure("Compact.Selection.TLabel", font=(family, 11, "bold"))
    style.configure("TLabelframe", background=SURFACE, bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=SURFACE, foreground=MUTED, font=(family, 10, "bold"))
    style.configure("Card.TLabelframe", background=SURFACE)
    style.configure("Card.TLabelframe.Label", background=SURFACE, foreground=MUTED)

    style.configure("TButton", background=SURFACE, foreground=TEXT, padding=(14, 8),
                    borderwidth=1, bordercolor=BORDER, relief="flat", focusthickness=0)
    style.map("TButton", background=[("disabled", BACKGROUND), ("pressed", ACCENT_SOFT), ("active", "#EDF2F7")],
              foreground=[("disabled", "#94A3B8")], bordercolor=[("focus", ACCENT), ("active", "#B7C7D7")])
    style.configure("Accent.TButton", background=ACCENT, foreground=SURFACE, bordercolor=ACCENT,
                    font=(family, 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", "#C6DAD6"), ("pressed", "#065F55"), ("active", ACCENT_HOVER)],
              foreground=[("disabled", "#F4FAF8"), ("!disabled", SURFACE)],
              bordercolor=[("disabled", "#C6DAD6"), ("!disabled", ACCENT)])
    style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT, bordercolor=BORDER,
                    insertcolor=INK, padding=(9, 7), relief="flat")
    style.map("TEntry", bordercolor=[("focus", ACCENT)],
              fieldbackground=[("readonly", "#EDF2F7"), ("disabled", BACKGROUND)],
              foreground=[("disabled", MUTED), ("readonly", MUTED)])
    style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE, foreground=TEXT,
                    arrowcolor=ACCENT, bordercolor=BORDER, padding=(8, 6), arrowsize=14)
    style.map("TCombobox", fieldbackground=[("disabled", BACKGROUND), ("readonly", SURFACE)],
              foreground=[("disabled", MUTED), ("readonly", TEXT)],
              background=[("active", ACCENT_SOFT), ("readonly", SURFACE)],
              bordercolor=[("focus", ACCENT)], selectbackground=[("readonly", SURFACE)],
              selectforeground=[("readonly", TEXT)])

    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                    borderwidth=0, relief="flat", rowheight=34)
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", SURFACE)])
    style.configure("Treeview.Heading", background="#EAF0F6", foreground=INK,
                    font=(family, 10, "bold"), padding=(10, 9), relief="flat", borderwidth=0)
    style.map("Treeview.Heading", background=[("active", "#DFE8F1")])
    style.configure("TScrollbar", background="#C5D0DB", troughcolor=BACKGROUND, borderwidth=0,
                    arrowcolor=MUTED, arrowsize=12, relief="flat")
    style.map("TScrollbar", background=[("active", "#9AAEC0"), ("pressed", "#8298AB")])
    style.configure("TPanedwindow", background=BACKGROUND)
    style.configure("Sash", sashthickness=6, background=BACKGROUND)
    style.configure("TSeparator", background=BORDER)
    style.configure("TNotebook", background=BACKGROUND, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(22, 10), background="#E8EDF4", foreground=MUTED, borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", SURFACE), ("active", ACCENT_SOFT)],
              foreground=[("selected", ACCENT), ("active", INK)])
    return family
