"""用于选择策略和查看数据体的独立大窗口。"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import font, ttk
from typing import Any

from .ui_types import StrategySelection


QUALITY_NAMES = {1: "白色", 2: "蓝色", 3: "紫色", 4: "金色", 5: "红色"}


def display_text(value: Any) -> str:
    """保留游戏文案，移除 Unity 富文本标记。"""
    text = str(value or "")
    return re.sub(r"</?(?:color|size|b|i|u)(?:=[^>]*)?>", "", text)


def quality_label(detail: dict) -> str:
    """同时说明保存的品质和游戏中不同于该品质的显示颜色。"""
    quality = detail["quality"]
    name = QUALITY_NAMES[quality]
    display_quality = detail["display_quality"]
    if display_quality == quality:
        return name
    return f"{name}（显示{QUALITY_NAMES[display_quality]}）"


def _saved_strategy_text(value: Any) -> str:
    text = display_text(value)
    return re.sub(
        r"（品质\s+([1-5])）$",
        lambda match: f"（{QUALITY_NAMES[int(match.group(1))]}）",
        text,
    )


def _show_modal(
    dialog: tk.Toplevel, parent: tk.Misc, size: tuple[int, int], focus: tk.Widget
) -> None:
    dialog.transient(parent)
    dialog.update_idletasks()
    screen_width = dialog.winfo_screenwidth()
    screen_height = dialog.winfo_screenheight()
    width = min(size[0], screen_width - 80)
    height = min(size[1], screen_height - 100)
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    x = max(20, min(x, screen_width - width - 20))
    y = max(20, min(y, screen_height - height - 60))
    dialog.geometry(f"{width}x{height}+{x}+{y}")
    dialog.minsize(min(820, width), min(520, height))
    dialog.deiconify()
    dialog.wait_visibility()
    dialog.grab_set()
    focus.focus_set()
    parent.wait_window(dialog)


def _text_view(parent: tk.Misc, text_font: font.Font, height: int) -> tuple[ttk.Frame, tk.Text]:
    panel = ttk.Frame(parent)
    panel.columnconfigure(0, weight=1)
    panel.rowconfigure(0, weight=1)
    text = tk.Text(
        panel, height=height, width=1, wrap="word", font=text_font,
        relief="solid", borderwidth=1, padx=12, pady=10, spacing1=3, spacing3=7,
        state="disabled", takefocus=False,
    )
    text.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(panel, orient="vertical", command=text.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    text.configure(yscrollcommand=scrollbar.set)
    return panel, text


def _replace_text(widget: tk.Text, content: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", content)
    widget.configure(state="disabled")
    widget.yview_moveto(0)


class StrategyDialog(tk.Toplevel):
    """在弹窗内编辑临时选择，点击保存后才向主窗口返回结果。"""

    def __init__(
        self, parent: tk.Misc, title: str, strategies: list[dict],
        initial: StrategySelection | None = None,
    ) -> None:
        super().__init__(parent)
        self.withdraw()
        self.parent = parent.winfo_toplevel()
        self.title(title)
        self.strategies = strategies
        self.strategies_by_id = {strategy["id"]: strategy for strategy in strategies}
        self.draft: StrategySelection | None = None
        self.result: StrategySelection | None = None
        self.quality_values: list[int] = []
        self.search_text = tk.StringVar(self)
        self.count_text = tk.StringVar(self)
        self.name_text = tk.StringVar(self, "请选择策略")
        self.category_text = tk.StringVar(self, "从左侧列表选择，右侧查看品质和完整说明。")
        self.heading_font = font.nametofont("TkDefaultFont").copy()
        self.heading_font.configure(size=16, weight="bold")
        self.description_font = font.nametofont("TkDefaultFont").copy()
        self.description_font.configure(size=12)
        self.list_font = font.nametofont("TkDefaultFont").copy()
        self.list_font.configure(size=11)
        ttk.Style(self).configure(
            "Dialog.Treeview", font=self.list_font,
            rowheight=max(30, self.list_font.metrics("linespace") + 8),
        )
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_content()
        self._build_actions()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", self._cancel)
        if initial is not None:
            strategy = self.strategies_by_id.get(initial.strategy_id)
            if strategy is not None and initial.quality in strategy["qualities"]:
                self.draft = initial
                self._render_selection()
        self.search_text.trace_add("write", self._filter_strategies)
        self._filter_strategies()

    def _build_content(self) -> None:
        content = ttk.Panedwindow(self, orient="horizontal")
        content.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 10))
        choices = ttk.Frame(content, padding=(0, 0, 12, 0), width=430)
        details = ttk.Frame(content, padding=(12, 0, 0, 0), width=530)
        content.add(choices, weight=4)
        content.add(details, weight=5)
        choices.columnconfigure(0, weight=1)
        choices.rowconfigure(2, weight=1)
        ttk.Label(choices, text="搜索策略名称、类别或流派").grid(row=0, column=0, sticky="w")
        self.search_entry = ttk.Entry(choices, textvariable=self.search_text)
        self.search_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 10))
        self.strategy_list = ttk.Treeview(
            choices, columns=("name", "category"), show="headings", selectmode="browse",
            style="Dialog.Treeview",
        )
        self.strategy_list.heading("name", text="策略名称")
        self.strategy_list.heading("category", text="类别")
        self.strategy_list.column("name", width=275, minwidth=190)
        self.strategy_list.column("category", width=100, minwidth=75, stretch=False)
        self.strategy_list.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(choices, orient="vertical", command=self.strategy_list.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.strategy_list.configure(yscrollcommand=scrollbar.set)
        self.strategy_list.bind("<<TreeviewSelect>>", self._select_strategy)
        ttk.Label(choices, textvariable=self.count_text).grid(row=3, column=0, sticky="w", pady=(8, 0))

        details.columnconfigure(0, weight=1)
        details.rowconfigure(4, weight=1)
        self.name_label = ttk.Label(details, textvariable=self.name_text, font=self.heading_font, wraplength=480)
        self.name_label.grid(row=0, column=0, sticky="ew")
        self.category_label = ttk.Label(details, textvariable=self.category_text, wraplength=480)
        self.category_label.grid(row=1, column=0, sticky="ew", pady=(6, 16))
        quality_row = ttk.Frame(details)
        quality_row.grid(row=2, column=0, sticky="ew", pady=(0, 18))
        ttk.Label(quality_row, text="策略品质").pack(side="left", padx=(0, 12))
        self.quality_combo = ttk.Combobox(quality_row, state="disabled", width=23)
        self.quality_combo.pack(side="left")
        self.quality_combo.bind("<<ComboboxSelected>>", self._select_quality)
        ttk.Label(details, text="策略说明").grid(row=3, column=0, sticky="w", pady=(0, 7))
        description_panel, self.description = _text_view(details, self.description_font, height=12)
        description_panel.grid(row=4, column=0, sticky="nsew")
        _replace_text(self.description, "选中策略后，这里会显示当前品质对应的完整效果。")
        details.bind("<Configure>", self._resize_details)

    def _build_actions(self) -> None:
        actions = ttk.Frame(self, padding=(16, 6, 16, 16))
        actions.grid(row=1, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Label(
            actions, text="保存选择后返回主窗口；点击“添加数据体并保存”时才会写入存档。",
            wraplength=610,
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Button(actions, text="取消", command=self._cancel, width=12).grid(row=0, column=1, padx=(0, 10))
        self.save_button = ttk.Button(actions, text="保存选择", command=self._save, state="disabled", width=14)
        self.save_button.grid(row=0, column=2)

    def _resize_details(self, event: tk.Event) -> None:
        width = max(event.width - 24, 180)
        self.name_label.configure(wraplength=width)
        self.category_label.configure(wraplength=width)

    def _filter_strategies(self, *_args: Any) -> None:
        query = self.search_text.get().strip().casefold()
        self.strategy_list.delete(*self.strategy_list.get_children())
        for strategy in self.strategies:
            name = display_text(strategy["name"])
            category = display_text(strategy.get("category", ""))
            searchable = " ".join((name, category, display_text(strategy.get("faction", ""))))
            if query and query not in searchable.casefold():
                continue
            item = str(strategy["id"])
            self.strategy_list.insert("", "end", iid=item, values=(name, category))
            if self.draft is not None and self.draft.strategy_id == strategy["id"]:
                self.strategy_list.selection_set(item)
                self.strategy_list.see(item)
        count = len(self.strategy_list.get_children())
        self.count_text.set(f"显示 {count} / {len(self.strategies)} 项策略")

    def _select_strategy(self, _event: tk.Event) -> None:
        selected = self.strategy_list.selection()
        if not selected:
            return
        strategy_id = int(selected[0])
        if self.draft is not None and self.draft.strategy_id == strategy_id:
            return
        strategy = self.strategies_by_id[strategy_id]
        self.draft = StrategySelection(strategy_id, max(strategy["qualities"]))
        self._render_selection()

    def _select_quality(self, _event: tk.Event) -> None:
        index = self.quality_combo.current()
        if self.draft is None or index < 0:
            return
        self.draft = StrategySelection(self.draft.strategy_id, self.quality_values[index])
        self._render_selection()

    def _render_selection(self) -> None:
        if self.draft is None:
            return
        strategy = self.strategies_by_id[self.draft.strategy_id]
        details = {detail["quality"]: detail for detail in strategy["quality_details"]}
        self.quality_values = sorted(strategy["qualities"])
        labels = [quality_label(details[quality]) for quality in self.quality_values]
        self.quality_combo.configure(values=labels, state="readonly")
        self.quality_combo.current(self.quality_values.index(self.draft.quality))
        detail = details[self.draft.quality]
        self.name_text.set(display_text(detail["name"]))
        category = display_text(strategy.get("category", ""))
        faction = display_text(strategy.get("faction", ""))
        self.category_text.set(" · ".join(value for value in (category, faction) if value))
        _replace_text(self.description, display_text(detail["description"]))
        self.save_button.configure(state="normal")

    def _save(self) -> None:
        if self.draft is None:
            return
        self.result = self.draft
        self.destroy()

    def _cancel(self, _event: tk.Event | None = None) -> str:
        self.result = None
        self.destroy()
        return "break"

    def show(self) -> StrategySelection | None:
        _show_modal(self, self.parent, (1050, 720), self.search_entry)
        return self.result


class BodiesDialog(tk.Toplevel):
    """展示已读取的存档快照；查看和筛选不会调用存档服务。"""

    def __init__(self, parent: tk.Misc, save: dict) -> None:
        super().__init__(parent)
        self.withdraw()
        self.parent = parent.winfo_toplevel()
        self.title("已有数据体")
        self.bodies = [
            {
                "uid": body["uid"],
                "character_name": display_text(body["character_name"]),
                "strategies": [_saved_strategy_text(strategy) for strategy in body["strategies"]],
            }
            for body in save["bodies"]
        ]
        self.search_text = tk.StringVar(self)
        self.count_text = tk.StringVar(self)
        self.selection_text = tk.StringVar(self, "选择一行，在下方查看两项策略的完整文本。")
        self.path_text = tk.StringVar(self, str(save["path"]))
        self.detail_font = font.nametofont("TkDefaultFont").copy()
        self.detail_font.configure(size=12)
        self.list_font = font.nametofont("TkDefaultFont").copy()
        self.list_font.configure(size=11)
        ttk.Style(self).configure(
            "Dialog.Treeview", font=self.list_font,
            rowheight=max(30, self.list_font.metrics("linespace") + 8),
        )
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_search(save)
        self._build_table()
        self._build_details()
        ttk.Button(self, text="关闭", command=self.destroy, width=14).grid(
            row=3, column=0, sticky="e", padx=16, pady=(0, 16)
        )
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", self._close)
        self.search_text.trace_add("write", self._filter_bodies)
        self._filter_bodies()

    def _build_search(self, save: dict) -> None:
        panel = ttk.Frame(self, padding=(16, 16, 16, 10))
        panel.grid(row=0, column=0, sticky="ew")
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text=f"共 {save['count']} 个数据体，容量 {save['capacity']} 个。").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(panel, textvariable=self.path_text, state="readonly").grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(7, 12)
        )
        ttk.Label(panel, text="搜索角色或策略").grid(row=2, column=0, sticky="w")
        self.search_entry = ttk.Entry(panel, textvariable=self.search_text)
        self.search_entry.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        ttk.Label(panel, textvariable=self.count_text).grid(row=3, column=1, padx=(16, 0))

    def _build_table(self) -> None:
        panel = ttk.Frame(self)
        panel.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 10))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)
        self.body_list = ttk.Treeview(
            panel, columns=("character", "first", "second", "uid"),
            show="headings", selectmode="browse", style="Dialog.Treeview", height=10,
        )
        for column, title, width in (
            ("character", "角色", 150), ("first", "策略一", 350),
            ("second", "策略二", 350), ("uid", "编号", 230),
        ):
            self.body_list.heading(column, text=title)
            self.body_list.column(column, width=width, minwidth=width, stretch=False)
        self.body_list.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(panel, orient="vertical", command=self.body_list.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(panel, orient="horizontal", command=self.body_list.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.body_list.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.body_list.bind("<<TreeviewSelect>>", self._select_body)

    def _build_details(self) -> None:
        panel = ttk.LabelFrame(self, text="所选数据体", padding=10)
        panel.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))
        panel.columnconfigure(0, weight=1)
        self.selection_label = ttk.Label(panel, textvariable=self.selection_text, wraplength=1080)
        self.selection_label.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        details_panel, self.details = _text_view(panel, self.detail_font, height=5)
        details_panel.grid(row=1, column=0, sticky="ew")
        panel.bind("<Configure>", self._resize_details)

    def _resize_details(self, event: tk.Event) -> None:
        self.selection_label.configure(wraplength=max(event.width - 28, 200))

    def _filter_bodies(self, *_args: Any) -> None:
        previous = self.body_list.selection()
        query = self.search_text.get().strip().casefold()
        self.body_list.delete(*self.body_list.get_children())
        for index, body in enumerate(self.bodies):
            strategies = body["strategies"]
            searchable = " ".join([body["character_name"], *strategies])
            if query and query not in searchable.casefold():
                continue
            first = strategies[0] if strategies else "—"
            second = strategies[1] if len(strategies) > 1 else "—"
            self.body_list.insert(
                "", "end", iid=str(index), values=(body["character_name"], first, second, body["uid"])
            )
        count = len(self.body_list.get_children())
        self.count_text.set(f"显示 {count} / {len(self.bodies)} 个")
        if previous and self.body_list.exists(previous[0]):
            self.body_list.selection_set(previous[0])
            self.body_list.see(previous[0])
        else:
            self.selection_text.set("选择一行，在下方查看两项策略的完整文本。")
            _replace_text(self.details, "")

    def _select_body(self, _event: tk.Event) -> None:
        selected = self.body_list.selection()
        if not selected:
            return
        body = self.bodies[int(selected[0])]
        strategies = body["strategies"]
        first = strategies[0] if strategies else "—"
        second = strategies[1] if len(strategies) > 1 else "—"
        self.selection_text.set(f"{body['character_name']}  ·  编号 {body['uid']}")
        _replace_text(self.details, f"策略一：{first}\n\n策略二：{second}")

    def _close(self, _event: tk.Event) -> str:
        self.destroy()
        return "break"

    def show(self) -> None:
        _show_modal(self, self.parent, (1180, 740), self.search_entry)
