"""单体编辑与流派规划共用的策略选择卡片。"""
from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import ttk

from .dialogs import StrategyDialog, display_text, quality_label
from .ui_types import StrategySelection
from .theme import BACKGROUND


class ScrollableFrame(ttk.Frame):
    """在小窗口保留内容的自然高度，操作按钮由外层窗口固定显示。"""
    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=BACKGROUND, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self, command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = ttk.Frame(self.canvas)
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.content.bind("<Configure>", self._content_changed)
        self._wheel_binding = self.winfo_toplevel().bind("<MouseWheel>", self._wheel, add="+")
        self.bind("<Destroy>", self._destroyed)

    def _resize(self, event):
        self.canvas.itemconfigure(self.item, width=event.width)

    def _content_changed(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _wheel(self, event):
        if str(event.widget).startswith(str(self.content)) and event.widget.winfo_class() not in ("TCombobox", "Text", "Treeview"):
            self.canvas.yview_scroll(-int(event.delta / 120), "units")
            return "break"

    def _destroyed(self, event):
        if event.widget is self:
            self.winfo_toplevel().unbind("<MouseWheel>", self._wheel_binding)


class StrategySlot(ttk.LabelFrame):
    """保存已确认的选择；弹窗只编辑临时选择，取消时不触发变更。"""

    def __init__(self, parent: tk.Misc, title: str, strategies: list[dict], *,
                 on_change: Callable[[StrategySelection | None], None] | None = None,
                 compact: bool = False) -> None:
        padding = 12 if compact else 18
        super().__init__(parent, text=title, padding=padding, style="Card.TLabelframe")
        self.slot_title = title
        self.strategies = strategies
        self.strategy_by_id = {strategy["id"]: strategy for strategy in strategies}
        self.selection: StrategySelection | None = None
        self.on_change = on_change
        self._padding = padding
        self._compact = compact
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.name_text = tk.StringVar(self)
        self.quality_text = tk.StringVar(self)
        name_style = "Compact.Selection.TLabel" if compact else "Selection.TLabel"
        self.name_label = ttk.Label(self, textvariable=self.name_text, style=name_style, wraplength=390)
        self.name_label.grid(row=0, column=0, sticky="nw")
        self.quality_label = ttk.Label(self, textvariable=self.quality_text, style="CardMuted.TLabel", wraplength=390)
        self.quality_label.grid(row=1, column=0, sticky="nw", pady=(6, 10) if compact else (10, 16))
        self.choose_button = ttk.Button(self, command=self.edit_selection, padding=(12, 6) if compact else (18, 8))
        self.choose_button.grid(row=3, column=0, sticky="sw")
        self.bind("<Configure>", self._resize_summary)
        self.set_selection(None)

    def _resize_summary(self, event: tk.Event) -> None:
        width = max(120, event.width - self._padding * 2 - 4)
        self.name_label.configure(wraplength=width)
        self.quality_label.configure(wraplength=width)

    def edit_selection(self) -> None:
        dialog = StrategyDialog(self.winfo_toplevel(), f"选择{self.slot_title}", self.strategies, self.selection)
        selected = dialog.show()
        if selected is not None:
            self.set_selection(selected)

    def set_selection(self, selection: StrategySelection | None) -> None:
        """应用推荐或手工选择，复用同一套显示与变更通知。"""
        if selection is None:
            name = "尚未添加"
            description = "点击按钮选择策略。" if self._compact else "点击下方按钮，在弹窗中搜索和选择策略。"
            action = "添加"
        else:
            strategy, detail = self._selection_detail(selection)
            name = display_text(detail["name"])
            description = f"{display_text(strategy.get('category', ''))}  ·  {quality_label(detail)}"
            action = "修改"
        changed = selection != self.selection
        self.selection = selection
        self.name_text.set(name)
        self.quality_text.set(description)
        self.choose_button.configure(text=f"{action}{self.slot_title}")
        if changed and self.on_change is not None:
            self.on_change(selection)

    def _selection_detail(self, selection: StrategySelection) -> tuple[dict, dict]:
        strategy = self.strategy_by_id.get(selection.strategy_id)
        if strategy is None:
            raise ValueError(f"{self.slot_title}所选策略不存在。")
        detail = next((detail for detail in strategy["quality_details"]
                       if detail["quality"] == selection.quality), None)
        if detail is None:
            raise ValueError(f"{self.slot_title}所选策略品质不可用。")
        return strategy, detail

    def _selected_detail(self) -> tuple[dict, dict]:
        if self.selection is None:
            raise ValueError(f"请先添加{self.slot_title}。")
        return self._selection_detail(self.selection)

    def chosen_strategy(self) -> tuple[int, int, str]:
        _, detail = self._selected_detail()
        name = display_text(detail["name"])
        return self.selection.strategy_id, self.selection.quality, f"{name}（{quality_label(detail)}）"
