"""为本地游戏存档选择角色和传承策略的桌面界面。"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from databody.service import DataBodyService
from databody.dialogs import BodiesDialog, StrategyDialog, display_text, quality_label
from databody.ui_types import StrategySelection


class StrategySlot(ttk.LabelFrame):
    """主界面只保存已确认的选择；弹窗负责搜索和编辑临时选择。"""

    def __init__(self, parent: tk.Misc, title: str, strategies: list[dict]) -> None:
        super().__init__(parent, text=title, padding=18)
        self.slot_title = title
        self.strategies = strategies
        self.strategy_by_id = {strategy["id"]: strategy for strategy in strategies}
        self.selection: StrategySelection | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.name_text = tk.StringVar(value="尚未添加")
        self.quality_text = tk.StringVar(value="点击下方按钮，在弹窗中搜索和选择策略。")
        self.name_label = ttk.Label(self, textvariable=self.name_text, style="Selection.TLabel", wraplength=390)
        self.name_label.grid(row=0, column=0, sticky="nw")
        self.quality_label = ttk.Label(self, textvariable=self.quality_text, wraplength=390)
        self.quality_label.grid(row=1, column=0, sticky="nw", pady=(10, 16))
        self.choose_button = ttk.Button(self, text=f"添加{title}", command=self.edit_selection, padding=(18, 8))
        self.choose_button.grid(row=3, column=0, sticky="sw")
        self.bind("<Configure>", self._resize_summary)

    def _resize_summary(self, event: tk.Event) -> None:
        width = max(160, event.width - 40)
        self.name_label.configure(wraplength=width)
        self.quality_label.configure(wraplength=width)

    def edit_selection(self) -> None:
        dialog = StrategyDialog(self.winfo_toplevel(), f"选择{self.slot_title}", self.strategies, self.selection)
        selected = dialog.show()
        if selected is None:
            return
        self.selection = selected
        strategy, detail = self._selected_detail()
        self.name_text.set(display_text(detail["name"]))
        self.quality_text.set(f"{display_text(strategy.get('category', ''))}  ·  {quality_label(detail)}")
        self.choose_button.configure(text=f"修改{self.slot_title}")

    def _selected_detail(self) -> tuple[dict, dict]:
        if self.selection is None:
            raise ValueError(f"请先添加{self.slot_title}。")
        strategy = self.strategy_by_id[self.selection.strategy_id]
        detail = next(detail for detail in strategy["quality_details"] if detail["quality"] == self.selection.quality)
        return strategy, detail

    def chosen_strategy(self) -> tuple[int, int, str]:
        _, detail = self._selected_detail()
        name = display_text(detail["name"])
        return self.selection.strategy_id, self.selection.quality, f"{name}（{quality_label(detail)}）"


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
        self.path_text = tk.StringVar(value="尚未选择存档")
        self.count_text = tk.StringVar(value="请选择存档后查看已有数据体。")
        self.status_text = tk.StringVar(value="先选择存档，再选择角色和两个策略。")
        self.backup_text = tk.StringVar()
        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self._build_header()
        self._build_save_selector()
        self._build_existing_bodies()
        self._build_body_editor()
        self._build_actions()
        root.after_idle(self.refresh_saves)

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(header, text="苍翼：混沌效应 · 数据体工具", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header, text="请先退出游戏，再添加或恢复数据体。每次保存都会自动备份原存档。"
        ).pack(anchor="w", pady=(5, 0))
        score = self.service.catalog["rules"]["inherit_score"]
        ttk.Label(
            header,
            text=f"新数据体为 {score} 分，附带角色默认天赋和一级初始继承技能。策略前置条件及互斥仍按游戏规则。",
        ).pack(anchor="w", pady=(3, 0))

    def _build_save_selector(self) -> None:
        panel = ttk.LabelFrame(self, text="目标存档", padding=10)
        panel.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        panel.columnconfigure(0, weight=1)
        self.save_combo = ttk.Combobox(panel, state="readonly")
        self.save_combo.grid(row=0, column=0, sticky="ew")
        self.save_combo.bind("<<ComboboxSelected>>", self._select_save)
        ttk.Button(panel, text="刷新列表", command=self.refresh_saves).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(panel, text="选择存档文件…", command=self.browse_save).grid(row=0, column=2, padx=(8, 0))
        path = ttk.Entry(panel, textvariable=self.path_text, state="readonly")
        path.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(7, 0))

    def _build_existing_bodies(self) -> None:
        panel = ttk.LabelFrame(self, text="已有数据体", padding=14)
        panel.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, textvariable=self.count_text).grid(row=0, column=0, sticky="w")
        self.view_bodies_button = ttk.Button(
            panel, text="查看已有数据体", command=self.view_bodies, state="disabled", padding=(16, 6)
        )
        self.view_bodies_button.grid(row=0, column=1, padx=(16, 0))

    def view_bodies(self) -> None:
        if self.current_save is not None:
            BodiesDialog(self.root, self.current_save).show()

    def _build_body_editor(self) -> None:
        panel = ttk.LabelFrame(self, text="添加数据体", padding=10)
        panel.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
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
        ttk.Label(character_row, text="点击下方按钮，在大窗口中搜索并保存选择。").pack(side="left", padx=(18, 0))
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
        self.add_button = ttk.Button(panel, text="添加数据体并保存", command=self.add_body, state="disabled")
        self.add_button.grid(row=0, column=2)
        backup = ttk.Entry(panel, textvariable=self.backup_text, state="readonly")
        backup.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

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
        self.count_text.set(f"共 {saved['count']} 个数据体，容量 {saved['capacity']} 个。")
        self.view_bodies_button.configure(state="normal")
        self.add_button.configure(state="normal")
        self.status_text.set("存档已载入。选择角色和两个策略后，即可添加数据体。")
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
            first = self.first_strategy.chosen_strategy()
            second = self.second_strategy.chosen_strategy()
            self._require_game_closed()
            path = str(self.current_save["path"])
            confirmed = messagebox.askokcancel(
                "确认添加数据体",
                f"角色：{character['name']}\n策略一：{first[2]}\n策略二：{second[2]}\n\n"
                f"目标存档：\n{path}\n\n保存前会自动备份原存档。是否继续？",
                parent=self.root,
            )
            if not confirmed:
                return
            result = self.service.add_body(
                path, character["id"], [first[0], second[0]], [first[1], second[1]]
            )
        except Exception as error:
            self._show_error("添加数据体失败", error)
            return
        backup_path = str(result["backup_path"])
        self.backup_text.set(f"最近备份：{backup_path}")
        reloaded = self._load_save(path)
        if reloaded:
            self.status_text.set(f"已添加 {character['name']} 的数据体，现有 {result['count']} 个。")
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
    root.title("苍翼：混沌效应 · 数据体工具")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    available_fonts = font.families(root)
    family = "Microsoft YaHei UI" if "Microsoft YaHei UI" in available_fonts else "Segoe UI"
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        font.nametofont(name, root=root).configure(family=family, size=10)
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    style.configure("Title.TLabel", font=(family, 17, "bold"))
    style.configure("Selection.TLabel", font=(family, 14, "bold"))
    style.configure("Treeview", rowheight=25)
    width = min(1120, root.winfo_screenwidth() - 80)
    height = min(720, root.winfo_screenheight() - 100)
    root.geometry(f"{width}x{height}")
    root.minsize(min(920, width), min(620, height))
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
