"""为本地游戏存档选择角色和传承策略的桌面界面。"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from databody.service import DataBodyService, application_directory
from databody.dialogs import BodiesDialog
from .planner import BuildPlanner
from .planner_ui import PlannerPanel
from .theme import configure_theme
from .widgets import StrategySlot


class DataBodyWindow(ttk.Frame):
    """围绕读取、添加和恢复存档组织用户操作。"""

    def __init__(self, root: tk.Tk, service: DataBodyService) -> None:
        super().__init__(root, padding=16)
        self.root = root
        self.service = service
        self.save_choices: list[dict] = []
        self.selected_path: str | None = None
        self.current_save: dict | None = None
        self.characters = service.catalog["characters"]
        self.body_colors = service.catalog["rules"]["body_colors"]
        self.path_text = tk.StringVar(value="尚未选择存档")
        self.count_text = tk.StringVar(value="请选择存档后查看已有数据体。")
        self.status_text = tk.StringVar(value="先选择存档，再选择角色和两个策略。")
        self.backup_text = tk.StringVar()
        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self._build_header()
        self._build_save_selector()
        self._build_modes()
        self._build_actions()
        root.after_idle(self.refresh_saves)

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=(22, 15))
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="苍翼：混沌效应  /  流派工坊", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(
            header, text="选玩法，看路线，带上四项策略出发。    保存前请退出游戏 · 每次写入自动备份", style="HeaderSubtitle.TLabel"
        ).pack(anchor="w", pady=(5, 0))

    def _build_save_selector(self) -> None:
        panel = ttk.LabelFrame(self, text="目标存档", padding=10)
        panel.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        panel.columnconfigure(0, weight=1)
        self.save_combo = ttk.Combobox(panel, state="readonly")
        self.save_combo.grid(row=0, column=0, sticky="ew")
        self.save_combo.bind("<<ComboboxSelected>>", self._select_save)
        ttk.Button(panel, text="刷新列表", command=self.refresh_saves).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(panel, text="选择存档文件…", command=self.browse_save).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(panel, textvariable=self.count_text, style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.view_bodies_button = ttk.Button(
            panel, text="查看已有数据体", command=self.view_bodies, state="disabled", padding=(16, 6)
        )
        self.view_bodies_button.grid(row=1, column=1, columnspan=2, sticky="e", pady=(6, 0))

    def view_bodies(self) -> None:
        if self.current_save is not None:
            BodiesDialog(self.root, self.current_save).show()

    def _build_modes(self) -> None:
        self.mode_tabs = ttk.Notebook(self)
        self.mode_tabs.grid(row=3, column=0, sticky="nsew", pady=(0, 12))
        data_directory = application_directory() / "data"
        rules = json.loads((data_directory / "planner_rules.json").read_text(encoding="utf-8"))
        knowledge = json.loads((data_directory / "builds.json").read_text(encoding="utf-8"))
        planner = BuildPlanner(self.service.catalog, rules, knowledge)
        self.planner_panel = PlannerPanel(self.mode_tabs, planner, self.body_colors, self._refresh_action)
        self.mode_tabs.add(self.planner_panel, text="流派工坊 · 添加两个数据体")
        manual = ttk.Frame(self.mode_tabs, padding=16)
        self.mode_tabs.add(manual, text="自由添加 · 单个数据体")
        self._build_body_editor(manual)
        self.mode_tabs.bind("<<NotebookTabChanged>>", self._mode_changed)

    def _build_body_editor(self, panel) -> None:
        panel.columnconfigure(0, weight=1, uniform="strategy")
        panel.columnconfigure(1, weight=1, uniform="strategy")
        panel.rowconfigure(1, weight=1)
        character_row = ttk.Frame(panel)
        character_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(character_row, text="角色").pack(side="left", padx=(0, 8))
        self.character_combo = ttk.Combobox(
            character_row, values=[character["name"] for character in self.characters], state="readonly", width=28
        )
        self.character_combo.pack(side="left")
        ttk.Label(character_row, text="数据体颜色").pack(side="left", padx=(18, 8))
        self.body_color_combo = ttk.Combobox(
            character_row, values=[f"{color['name']}（{color['score']} 分）" for color in self.body_colors],
            state="readonly", width=20,
        )
        self.body_color_combo.pack(side="left")
        self.body_color_combo.current(0)
        ttk.Label(character_row, text="两种颜色均可继承两项策略。").pack(side="left", padx=(18, 0))
        strategies = self.service.catalog["strategies"]
        self.first_strategy = StrategySlot(panel, "策略一", strategies)
        self.first_strategy.grid(row=1, column=0, sticky="nsew", padx=(0, 5))
        self.second_strategy = StrategySlot(panel, "策略二", strategies)
        self.second_strategy.grid(row=1, column=1, sticky="nsew", padx=(5, 0))

    def _build_actions(self) -> None:
        panel = ttk.Frame(self)
        panel.grid(row=4, column=0, sticky="ew")
        panel.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(panel, textvariable=self.status_text, wraplength=680)
        self.status_label.grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Button(panel, text="恢复备份…", command=self.restore_backup).grid(row=0, column=1, padx=(0, 8))
        self.add_button = ttk.Button(panel, text="添加两个数据体并保存", command=self.add_current_mode,
                                     state="disabled", style="Accent.TButton")
        self.add_button.grid(row=0, column=2)
        backup = ttk.Entry(panel, textvariable=self.backup_text, state="readonly")
        backup.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

    def _mode_changed(self, _event) -> None:
        self._refresh_action()

    def _refresh_action(self) -> None:
        if not hasattr(self, "add_button"):
            return
        planning = self.mode_tabs.index(self.mode_tabs.select()) == 0
        self.add_button.configure(text="添加两个数据体并保存" if planning else "添加数据体并保存")
        ready = self.current_save is not None
        if planning:
            ready = ready and not self.planner_panel.validation_errors()
        self.add_button.configure(state="normal" if ready else "disabled")

    def add_current_mode(self) -> None:
        if self.mode_tabs.index(self.mode_tabs.select()) == 0:
            self.add_build()
        else:
            self.add_body()

    def add_build(self) -> None:
        try:
            if self.current_save is None:
                raise ValueError("请先选择要修改的存档。")
            requests = self.planner_panel.body_requests()
            self._require_game_closed()
            path = str(self.current_save["path"])
            confirmed = messagebox.askokcancel(
                "确认添加两个继承数据体",
                self.planner_panel.confirmation_text() + f"\n\n目标存档：\n{path}\n\n"
                "将一次添加两个数据体，保存前自动备份完整原存档。是否继续？", parent=self.root,
            )
            if not confirmed:
                return
            result = self.service.add_bodies(path, requests)
        except Exception as error:
            self._show_error("添加配套数据体失败", error)
            return
        self._show_saved_result(path, result, "已添加两个配套数据体")

    def refresh_saves(self) -> None:
        try:
            saves = self.service.discover_saves()
        except Exception as error:
            self._show_error("查找存档失败", error)
            return
        self.save_choices = saves
        self.save_combo.configure(values=[save["label"] for save in saves])
        self.save_combo.set("")
        self._clear_loaded_save()
        if saves:
            self.status_text.set(f"找到 {len(saves)} 个存档，请明确选择要修改的存档。")
        else:
            self.status_text.set("未找到存档，请点击“选择存档文件…”手动指定。")

    def _select_save(self, _event: tk.Event) -> None:
        index = self.save_combo.current()
        if index >= 0:
            self._load_save(self.save_choices[index]["path"])

    def browse_save(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="选择游戏存档", filetypes=[("所有文件", "*.*")])
        if path:
            self.save_combo.set("")
            self._load_save(path)

    def _clear_loaded_save(self) -> None:
        self.selected_path = None
        self.current_save = None
        self.path_text.set("尚未选择存档")
        self.count_text.set("请选择存档后查看已有数据体。")
        self.view_bodies_button.configure(state="disabled")
        self.add_button.configure(state="disabled")

    def _load_save(self, path: str) -> bool:
        self._clear_loaded_save()
        self.selected_path = str(Path(path).resolve())
        self.path_text.set(self.selected_path)
        try:
            saved = self.service.load_save(self.selected_path)
        except Exception as error:
            self._show_error("读取存档失败", error)
            self.count_text.set("无法读取该存档的数据体。")
            self.status_text.set("存档读取失败；可点击“恢复备份…”恢复当前选择的存档。")
            return False
        self.current_save = saved
        self.path_text.set(str(saved["path"]))
        if self.save_combo.current() < 0:
            self.save_combo.set(str(saved["path"]))
        self.count_text.set(f"共 {saved['count']} 个数据体，容量 {saved['capacity']} 个。")
        self.view_bodies_button.configure(state="normal")
        self._refresh_action()
        self.status_text.set("存档已载入。可使用推荐流派，也可自由添加单个数据体。")
        return True

    def _require_game_closed(self) -> None:
        if self.service.game_running():
            raise ValueError("检测到游戏仍在运行。请完全退出《苍翼：混沌效应》后重试。")

    def add_body(self) -> None:
        try:
            if self.current_save is None:
                raise ValueError("请先选择要修改的存档。")
            character_index = self.character_combo.current()
            if character_index < 0:
                raise ValueError("请先选择角色。")
            character = self.characters[character_index]
            color_index = self.body_color_combo.current()
            if color_index < 0:
                raise ValueError("请先选择数据体颜色。")
            color = self.body_colors[color_index]
            first = self.first_strategy.chosen_strategy()
            second = self.second_strategy.chosen_strategy()
            self._require_game_closed()
            path = str(self.current_save["path"])
            confirmed = messagebox.askokcancel(
                "确认添加数据体",
                f"角色：{character['name']}\n数据体颜色：{color['name']}（{color['score']} 分）\n"
                f"策略一：{first[2]}\n策略二：{second[2]}\n\n"
                f"目标存档：\n{path}\n\n保存前会自动备份原存档。是否继续？",
                parent=self.root,
            )
            if not confirmed:
                return
            result = self.service.add_body(
                path, character["id"], [first[0], second[0]], [first[1], second[1]], body_quality=color["quality"]
            )
        except Exception as error:
            self._show_error("添加数据体失败", error)
            return
        self._show_saved_result(path, result, f"已添加 {character['name']} 的数据体")

    def _show_saved_result(self, path: str, result: dict, description: str) -> None:
        backup_path = str(result["backup_path"])
        self.backup_text.set(f"最近备份：{backup_path}")
        reloaded = self._load_save(path)
        if reloaded:
            self.status_text.set(f"{description}，现有 {result['count']} 个。")
        else:
            self.status_text.set("添加已完成，但重新读取失败；请重新选择存档查看结果。")
        messagebox.showinfo("数据体已添加", f"保存成功。\n\n原存档备份：\n{backup_path}", parent=self.root)

    def restore_backup(self) -> None:
        try:
            if self.selected_path is None:
                raise ValueError("请先选择要恢复的目标存档。")
            self._require_game_closed()
            path = self.selected_path
            backup_path = filedialog.askopenfilename(
                parent=self.root, title="选择要恢复的存档备份",
                initialdir=str(Path(path).parent.parent / "DataBodyToolBackups"),
                filetypes=[("数据体工具备份", "*.bak")],
            )
            if not backup_path:
                return
            confirmed = messagebox.askokcancel(
                "确认恢复备份",
                f"使用以下备份：\n{backup_path}\n\n恢复到：\n{path}\n\n"
                "目标存档将回到备份时的状态。恢复前会先备份当前存档。是否继续？",
                parent=self.root,
            )
            if not confirmed:
                return
            result = self.service.restore_backup(path, backup_path)
        except Exception as error:
            self._show_error("恢复备份失败", error)
            return
        safety_backup = str(result["backup_path"])
        self.backup_text.set(f"最近备份：{safety_backup}")
        reloaded = self._load_save(path)
        if reloaded:
            self.status_text.set("备份已恢复。")
        else:
            self.status_text.set("备份已恢复，但重新读取失败；请重新选择存档查看结果。")
        messagebox.showinfo(
            "恢复完成", f"目标存档已恢复到所选备份。\n\n恢复前的存档备份：\n{safety_backup}", parent=self.root
        )

    def _show_error(self, title: str, error: Exception) -> None:
        self.status_text.set(f"{title}：{error}")
        messagebox.showerror(title, str(error), parent=self.root)


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    root.title("苍翼：混沌效应 · 流派工坊与数据体工具")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    configure_theme(root)
    width = min(1320, root.winfo_screenwidth() - 80)
    height = min(920, root.winfo_screenheight() - 100)
    root.geometry(f"{width}x{height}")
    root.minsize(min(1080, width), min(760, height))
    try:
        service = DataBodyService()
        DataBodyWindow(root, service)
    except Exception as error:
        messagebox.showerror("工具启动失败", str(error), parent=root)
        root.destroy()
        return
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
