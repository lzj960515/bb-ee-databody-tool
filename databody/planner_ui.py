"""流派选择、四槽继承配置与成型路线的桌面页面。"""
from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import font, ttk
import webbrowser

from .body_types import BodyRequest
from .dialogs import _replace_text, _text_view
from .planner import BuildPlanner
from .planner_dialogs import TargetsDialog
from .planner_types import BuildPlan
from .theme import ACCENT
from .ui_types import StrategySelection
from .widgets import ScrollableFrame, StrategySlot


class PlannerPanel(ttk.Frame):
    def __init__(self, parent: tk.Misc, planner: BuildPlanner, body_colors: list[dict],
                 on_change: Callable[[], None]):
        super().__init__(parent, padding=(0, 12, 0, 0))
        self.planner = planner
        self.body_colors = body_colors
        self.on_change = on_change
        self.characters = list(planner.characters.values())
        self.build_id = planner.builds[0].id
        self.targets = planner.builds[0].targets
        self.plan: BuildPlan | None = None
        self._updating = False
        self.search = tk.StringVar(self)
        self.list_mode = tk.StringVar(self, '推荐流派')
        self.element = tk.StringVar(self, '全部元素')
        self.list_count = tk.StringVar(self)
        self.title_text = tk.StringVar(self)
        self.summary_text = tk.StringVar(self)
        self.chain_text = tk.StringVar(self)
        self.validation_text = tk.StringVar(self)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_character_controls()
        self._build_workspace()
        self.search.trace_add('write', self._filter_builds)
        self.list_mode.trace_add('write', self._filter_builds)
        self.element.trace_add('write', self._filter_builds)
        self._filter_builds()
        self.after_idle(self._initialize)

    def _initialize(self):
        self._set_default_donors()
        self.reset_recommendation()

    def _build_character_controls(self):
        row = ttk.Frame(self)
        row.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        ttk.Label(row, text='本局想玩', style='Subtitle.TLabel').pack(side='left', padx=(0, 10))
        self.character_combo = ttk.Combobox(row, state='readonly', width=20,
                                            values=[c['name'] for c in self.characters])
        self.character_combo.pack(side='left')
        self.character_combo.current(0)
        self.character_combo.bind('<<ComboboxSelected>>', self._character_changed)
        ttk.Label(row, text='数据体颜色', style='Subtitle.TLabel').pack(side='left', padx=(24, 10))
        self.color_combo = ttk.Combobox(row, state='readonly', width=17,
            values=[f"{c['name']} · {c['score']} 分" for c in self.body_colors])
        self.color_combo.pack(side='left')
        self.color_combo.current(0)
        ttk.Label(row, text='规划可直接浏览，保存前再选择存档。', style='Muted.TLabel').pack(side='right')

    def _build_workspace(self):
        panes = ttk.Panedwindow(self, orient='horizontal')
        panes.grid(row=1, column=0, sticky='nsew')
        library = ttk.Frame(panes, padding=(0, 0, 16, 0), width=275)
        content = ttk.Frame(panes, padding=(16, 0, 0, 0), width=810)
        panes.add(library, weight=1)
        panes.add(content, weight=4)
        self._build_library(library)
        self._build_details(content)

    def _build_library(self, panel):
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(4, weight=1)
        ttk.Label(panel, text='选择你的玩法', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 10))
        self.search_entry = ttk.Entry(panel, textvariable=self.search)
        self.search_entry.grid(row=1, column=0, sticky='ew', pady=(0, 8))
        ttk.Combobox(panel, state='readonly', textvariable=self.list_mode,
                     values=['推荐流派', '全部双重策略', '全部路线']).grid(row=2, column=0, sticky='ew', pady=(0, 8))
        ttk.Combobox(panel, state='readonly', textvariable=self.element,
                     values=['全部元素', '火系', '冰系', '雷系', '毒系', '暗系', '光系', '刃系']).grid(
                         row=3, column=0, sticky='ew', pady=(0, 12))
        table = ttk.Frame(panel)
        table.grid(row=4, column=0, sticky='nsew')
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.build_list = ttk.Treeview(table, show='tree', selectmode='browse')
        self.build_list.column('#0', width=245, minwidth=180)
        self.build_list.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(table, command=self.build_list.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.build_list.configure(yscrollcommand=scroll.set)
        self.build_list.bind('<<TreeviewSelect>>', self._select_build)
        ttk.Label(panel, textvariable=self.list_count, style='Muted.TLabel').grid(row=5, column=0, sticky='w', pady=(10, 0))
        ttk.Label(panel, text='100 项双重策略均有前置路线\n组合目标时自动检查默认规则冲突',
                  style='Muted.TLabel').grid(row=6, column=0, sticky='w', pady=(8, 0))

    def _build_details(self, panel):
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)
        self.title_label = ttk.Label(panel, textvariable=self.title_text, style='Title.TLabel', wraplength=780)
        self.title_label.grid(row=0, column=0, sticky='w')
        self.summary_label = ttk.Label(panel, textvariable=self.summary_text, wraplength=780, style='Muted.TLabel')
        self.summary_label.grid(row=1, column=0, sticky='ew', pady=(6, 8))
        self.chain_label = ttk.Label(panel, textvariable=self.chain_text, style='Chain.TLabel', wraplength=780)
        self.chain_label.grid(row=2, column=0, sticky='ew', pady=(0, 12))
        self.detail_tabs = ttk.Notebook(panel)
        self.detail_tabs.grid(row=3, column=0, sticky='nsew')
        self.opening_scroll = ScrollableFrame(self.detail_tabs)
        opening = self.opening_scroll.content
        opening.configure(padding=14)
        route = ttk.Frame(self.detail_tabs, padding=14)
        reference = ttk.Frame(self.detail_tabs, padding=14)
        self.detail_tabs.add(self.opening_scroll, text='01  开局继承')
        self.detail_tabs.add(route, text='02  成型路线')
        self.detail_tabs.add(reference, text='03  条件与资料')
        self._build_opening(opening)
        self._build_route(route)
        self._build_reference(reference)
        panel.bind('<Configure>', self._resize)

    def _build_opening(self, panel):
        panel.columnconfigure(0, weight=1)
        panel.columnconfigure(1, weight=1)
        panel.rowconfigure(0, weight=1)
        self.donor_combos = []
        self.slots: list[StrategySlot] = []
        strategies = list(self.planner.strategies.values())
        for index in range(2):
            body = ttk.LabelFrame(panel, text=f'继承数据体 {index + 1}', padding=12)
            body.grid(row=0, column=index, sticky='nsew', padx=(0, 7) if index == 0 else (7, 0))
            body.columnconfigure(0, weight=1, uniform='slots')
            body.columnconfigure(1, weight=1, uniform='slots')
            body.rowconfigure(2, weight=1)
            ttk.Label(body, text='策略载体角色', style='CardMuted.TLabel').grid(row=0, column=0, columnspan=2, sticky='w')
            combo = ttk.Combobox(body, state='readonly', values=[c['name'] for c in self.characters])
            combo.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(5, 12))
            combo.bind('<<ComboboxSelected>>', self._donor_changed)
            self.donor_combos.append(combo)
            for slot_index in range(2):
                slot = StrategySlot(body, f'策略{("一", "二")[slot_index]}', strategies,
                                    compact=True, on_change=self._strategy_changed)
                slot.grid(row=2, column=slot_index, sticky='nsew', padx=(0, 4) if slot_index == 0 else (4, 0))
                self.slots.append(slot)
        self.validation_label = ttk.Label(panel, textvariable=self.validation_text, wraplength=740, justify='left')
        self.validation_label.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(12, 8))
        actions = ttk.Frame(panel)
        actions.grid(row=2, column=0, columnspan=2, sticky='ew')
        ttk.Button(actions, text='恢复推荐配置', command=self.reset_recommendation).pack(side='left')
        ttk.Button(actions, text='组合更多双重目标…', command=self.edit_targets).pack(side='left', padx=(8, 0))

    def _build_route(self, panel):
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        ttk.Label(panel, text='先补齐成型，再逐步强化。每次出现对应策略选项时按顺序选。', style='Muted.TLabel').grid(
            row=0, column=0, sticky='w', pady=(0, 10))
        table = ttk.Frame(panel)
        table.grid(row=1, column=0, sticky='nsew')
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.route_list = ttk.Treeview(table, columns=('step', 'name', 'purpose'), show='headings', height=5)
        for key, title, width in [('step', '顺序', 65), ('name', '策略', 260), ('purpose', '用途', 140)]:
            self.route_list.heading(key, text=title)
            self.route_list.column(key, width=width, minwidth=width, stretch=key == 'name')
        self.route_list.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(table, command=self.route_list.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.route_list.configure(yscrollcommand=scroll.set)
        self.route_list.bind('<<TreeviewSelect>>', self._show_route_step)
        details, self.route_description = _text_view(panel, font.nametofont('TkDefaultFont'), 4)
        details.grid(row=2, column=0, sticky='ew', pady=(10, 0))

    def _build_reference(self, panel):
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)
        body, self.reference_text = _text_view(panel, font.nametofont('TkDefaultFont'), 12)
        body.grid(row=0, column=0, sticky='nsew')
        self.source_buttons = ttk.Frame(panel)
        self.source_buttons.grid(row=1, column=0, sticky='ew', pady=(10, 0))

    def _resize(self, event):
        for label in (self.title_label, self.summary_label, self.chain_label, self.validation_label):
            label.configure(wraplength=max(350, event.width - 36))

    def _filter_builds(self, *_args):
        query = self.search.get().strip().casefold()
        mode, element = self.list_mode.get(), self.element.get()
        self.build_list.delete(*self.build_list.get_children())
        for build in self.planner.builds:
            if mode == '推荐流派' and not build.featured or mode == '全部双重策略' and build.featured:
                continue
            searchable = ' '.join((build.title, build.summary, *build.tags))
            if query not in searchable.casefold() or element != '全部元素' and element not in searchable:
                continue
            self.build_list.insert('', 'end', iid=build.id, text=build.title)
        if self.build_list.exists(self.build_id):
            self.build_list.selection_set(self.build_id)
        self.list_count.set(f'显示 {len(self.build_list.get_children())} 条路线')

    def _select_build(self, _event):
        selected = self.build_list.selection()
        if selected and selected[0] != self.build_id:
            self.build_id = selected[0]
            self.targets = self.planner.build_by_id[self.build_id].targets
            self.reset_recommendation()

    def played_character(self):
        return self.characters[self.character_combo.current()]

    def _set_default_donors(self):
        donors = self.planner.default_donors(self.played_character()['id'])
        character_ids = [c['id'] for c in self.characters]
        for combo, donor in zip(self.donor_combos, donors):
            combo.current(character_ids.index(donor))

    def _character_changed(self, _event):
        self._set_default_donors()
        self._replan()

    def _donor_changed(self, _event):
        self._render_validation()
        self._render_reference()
        self.on_change()

    def _strategy_changed(self, _selection):
        if not self._updating:
            self._replan()

    def reset_recommendation(self):
        build = self.planner.build_by_id[self.build_id]
        starters = self.planner.recommend_start(self.targets, build.starters)
        self._updating = True
        try:
            for index, slot in enumerate(self.slots):
                strategy_id = starters[index] if index < len(starters) else None
                selection = StrategySelection(strategy_id, max(self.planner.strategies[strategy_id]['qualities'])) if strategy_id else None
                slot.set_selection(selection)
        finally:
            self._updating = False
        self._replan()

    def edit_targets(self):
        selected = TargetsDialog(self, self.planner, self.targets).show()
        if selected is not None:
            self.targets = selected
            self.reset_recommendation()

    def _replan(self):
        starts = tuple(slot.selection.strategy_id for slot in self.slots if slot.selection)
        self.plan = self.planner.plan(self.build_id, self.played_character()['id'], starting_ids=starts, targets=self.targets)
        build = self.plan.build
        custom = self.targets != build.targets
        self.title_text.set('自选双重组合' if custom else build.title)
        self.summary_text.set('开局带入四项策略，其余目标按局内路线补齐。' if custom else build.summary)
        target_summary = ' / '.join(self.planner.name(c) for c in self.targets[:3])
        if len(self.targets) > 3:
            target_summary += f' 等 {len(self.targets)} 个（详见条件与资料）'
        self.chain_text.set(('目标：' + target_summary) if custom or not build.chain else '   →   '.join(build.chain))
        self._render_validation()
        self._render_route()
        self._render_reference()
        self.on_change()

    def _donor_ids(self):
        return tuple(self.characters[combo.current()]['id'] for combo in self.donor_combos)

    def validation_errors(self):
        errors = list(self.plan.errors) if self.plan else ['请选择流派']
        try:
            self.planner.validate_donors(self.played_character()['id'], self._donor_ids())
        except ValueError as error:
            errors.append(str(error))
        return errors

    def _render_validation(self):
        if self.plan is None:
            return
        errors = self.validation_errors()
        if errors:
            self.validation_text.set('需要调整：' + errors[0] + (f'（共 {len(errors)} 项，详见条件与资料）' if len(errors) > 1 else ''))
            self.validation_label.configure(foreground='#B45309')
        else:
            active = len(self.plan.activation.active_ids)
            self.validation_text.set(f'开局激活 {active} / 4 项 · 两个数据体一次保存、一次备份。'
                + (' 未激活的策略请先按成型路线补齐。' if active < 4 else ''))
            self.validation_label.configure(foreground=ACCENT)

    def _render_route(self):
        self.route_list.delete(*self.route_list.get_children())
        for index, step in enumerate(self.plan.steps, 1):
            self.route_list.insert('', 'end', iid=str(index - 1), values=(f'{index:02}', self.planner.name(step.strategy_id), step.purpose))
        active_goals = sum(c in self.plan.activation.active_ids for c in self.plan.targets)
        _replace_text(self.route_description, f'目标双重开局已激活 {active_goals} / {len(self.plan.targets)} 项。\n'
                      '选中一行查看完整效果。路线满足前置与默认冲突规则；局内获取仍取决于随机选项。')

    def _show_route_step(self, _event):
        selected = self.route_list.selection()
        if selected:
            step = self.plan.steps[int(selected[0])]
            strategy = self.planner.strategies[step.strategy_id]
            _replace_text(self.route_description, f"{strategy['name']} · {step.purpose}\n{strategy['description']}\n"
                          '以上数值为目录金色基础值；局内实际品质、角色加成和契约可能不同。')

    def _requirements_text(self, labels):
        groups = []
        for label in labels:
            names = [self.planner.name(c) for c in self.planner.label_choices(label)]
            groups.append(' / '.join(names) + ('（任一）' if len(names) > 1 else ''))
        return ' ＋ '.join(groups) if groups else '无额外前置'

    def _render_reference(self):
        lines = []
        errors = self.validation_errors()
        if errors:
            lines.extend(['需要调整的条件', *errors, ''])
        lines.extend(['本局角色：' + self.played_character()['name'], ''])
        lines.extend(self.planner.knowledge.get('character_notes', {}).get(str(self.plan.character_id), []))
        lines.extend(['', '目标策略：继承激活与局内抽取是两套条件'])
        for target in self.targets:
            strategy = self.planner.strategies[target]
            lines.extend(['', strategy['name'], strategy['description'],
                          '继承激活：' + self._requirements_text(strategy['true_pre']),
                          '局内前置：' + self._requirements_text(strategy['pre_labels'])])
        if self.plan.activation.missing_labels:
            lines.extend(['', '开局尚未激活'])
            for strategy_id, labels in self.plan.activation.missing_labels:
                lines.append(self.planner.name(strategy_id) + '：还需 ' + self._requirements_text(labels))
        lines.extend(['', '玩法与限制', *self.plan.notes,
                      '继承角色必须彼此不同，并避开本局使用角色。默认选用无DLC的策略载体；不是传承技能或天赋的强度排名。',
                      '角色、DLC与继承功能仍需在你的游戏中可用。工具只添加数据体，不解锁这些内容。',
                      '', '资料依据（配置规则与实战建议分开核对）'])
        for child in self.source_buttons.winfo_children():
            child.destroy()
        source_ids = self.plan.build.source_ids
        button_index = 0
        for source in self.planner.knowledge.get('sources', []):
            if source['id'] in source_ids:
                lines.extend([source['title'] + '：' + source['note'], source.get('url', '')])
                if source.get('url'):
                    ttk.Button(self.source_buttons, text=source.get('button', '打开参考资料'),
                               command=self._source_command(source['url'])).grid(row=button_index // 2,
                                    column=button_index % 2, sticky='ew', padx=(0, 8), pady=(0, 5))
                    self.source_buttons.columnconfigure(button_index % 2, weight=1)
                    button_index += 1
        lines.extend(['', '当前数据已按游戏配置与脚本静态核验；推荐流派未经本项目逐一实战测试，不保证强度或伤害循环无限。'])
        _replace_text(self.reference_text, '\n'.join(lines))

    @staticmethod
    def _source_command(url):
        def open_source():
            webbrowser.open(url)
        return open_source

    def body_requests(self):
        self._replan()
        errors = self.validation_errors()
        if errors:
            raise ValueError('\n'.join(errors))
        quality = self.body_colors[self.color_combo.current()]['quality']
        requests = []
        for index, donor in enumerate(self._donor_ids()):
            selected = [slot.chosen_strategy() for slot in self.slots[index * 2:index * 2 + 2]]
            requests.append(BodyRequest(donor, tuple(s[0] for s in selected), tuple(s[1] for s in selected), quality))
        return requests

    def confirmation_text(self):
        lines = [self.title_text.get(), '本局使用：' + self.played_character()['name']]
        color = self.body_colors[self.color_combo.current()]
        lines.append(f"数据体颜色：{color['name']}（{color['score']} 分）")
        for index, donor in enumerate(self._donor_ids()):
            names = [slot.chosen_strategy()[2] for slot in self.slots[index * 2:index * 2 + 2]]
            lines.extend(['', f"数据体 {index + 1} · {self.planner.characters[donor]['name']}", *names])
        if self.plan.activation.missing_labels:
            lines.extend(['', '部分策略需要局内补齐前置后才激活，请按成型路线游玩。'])
        return '\n'.join(lines)
