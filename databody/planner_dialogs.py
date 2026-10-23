"""选择多个双重目标；只编辑路线，不写入存档。"""
import tkinter as tk
from tkinter import font, ttk

from .dialogs import _replace_text, _show_modal, _text_view
from .planner import BuildPlanner


class TargetsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, planner: BuildPlanner, targets: tuple[int, ...]):
        super().__init__(parent)
        self.withdraw()
        self.title('组合双重策略目标')
        self.parent = parent.winfo_toplevel()
        self.planner = planner
        self.selected = set(targets)
        self.result = None
        self.search = tk.StringVar(self)
        self.count = tk.StringVar(self)
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text='选择想同时玩的双重策略', style='Title.TLabel').grid(
            row=0, column=0, columnspan=2, sticky='w', padx=20, pady=(16, 8))
        self.entry = ttk.Entry(self, textvariable=self.search)
        self.entry.grid(row=1, column=0, sticky='ew', padx=(20, 10), pady=(0, 10))
        ttk.Label(self, text='点击“选择”列勾选，或双击策略切换。', style='Muted.TLabel').grid(
            row=1, column=1, sticky='w')
        table = ttk.Frame(self)
        table.grid(row=2, column=0, sticky='nsew', padx=(20, 10))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=('picked', 'name', 'category'), show='headings', selectmode='browse')
        for name, title, width in [('picked', '选择', 54), ('name', '双重策略', 200), ('category', '元素', 160)]:
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=width, stretch=name != 'picked')
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scroll.set)
        detail, self.description = _text_view(self, font.nametofont('TkDefaultFont'), 14)
        detail.grid(row=2, column=1, sticky='nsew', padx=(0, 20))
        self.tree.bind('<<TreeviewSelect>>', self._show_strategy)
        self.tree.bind('<ButtonRelease-1>', self._click)
        self.tree.bind('<Double-1>', self._toggle_current)
        actions = ttk.Frame(self, padding=20)
        actions.grid(row=3, column=0, columnspan=2, sticky='ew')
        actions.columnconfigure(0, weight=1)
        ttk.Label(actions, textvariable=self.count).grid(row=0, column=0, sticky='w')
        ttk.Button(actions, text='取消', command=self.destroy).grid(row=0, column=1, padx=8)
        ttk.Button(actions, text='规划所选组合', command=self._apply, style='Accent.TButton').grid(row=0, column=2)
        self.search.trace_add('write', self._filter)
        self._filter()

    def _filter(self, *_args):
        query = self.search.get().strip().casefold()
        self.tree.delete(*self.tree.get_children())
        for strategy in self.planner.strategies.values():
            searchable = strategy['name'] + strategy['category'] + strategy['description']
            if strategy['is_combined'] and query in searchable.casefold():
                self.tree.insert('', 'end', iid=str(strategy['id']), values=(
                    '✓' if strategy['id'] in self.selected else '○', strategy['name'], strategy['category']))
        self.count.set(f'已选 {len(self.selected)} 个目标 · 冲突与缺少前置会在路线中提示')

    def _click(self, event):
        if self.tree.identify_column(event.x) == '#1':
            item = self.tree.identify_row(event.y)
            if item:
                self._toggle(int(item))

    def _toggle_current(self, _event):
        selection = self.tree.selection()
        if selection:
            self._toggle(int(selection[0]))

    def _toggle(self, strategy_id):
        if strategy_id in self.selected:
            self.selected.remove(strategy_id)
        else:
            self.selected.add(strategy_id)
        self._filter()

    def _show_strategy(self, _event):
        selected = self.tree.selection()
        if selected:
            strategy = self.planner.strategies[int(selected[0])]
            _replace_text(self.description, f"{strategy['name']}\n\n{strategy['description']}\n\n"
                          '这会成为规划目标，系统会安排四个继承槽和剩余局内路线。')

    def _apply(self):
        if self.selected:
            self.result = tuple(sorted(self.selected))
            self.destroy()
        else:
            self.count.set('请至少选择一个双重策略目标')

    def show(self):
        _show_modal(self, self.parent, (1080, 740), self.entry)
        return self.result
