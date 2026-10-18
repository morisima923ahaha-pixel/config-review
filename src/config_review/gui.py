"""Config 再鑑アシスタントの画面（tkinter）。

tkinter は Python に最初から入っている画面の部品なので、追加のインストールはいらない。
画面は上下 2 段：
  上：「現行の running-config」と「投入する Config」を貼り付ける欄
  下：「差分」「投入後の想定 Config」「読みかえのメモ」のタブ
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from config_review.compare import CompareResult, compare

TITLE = "Config再鑑アシスタント"
CODE_FONT = ("Consolas", 10)
SAMPLES = Path(__file__).resolve().parents[2] / "samples"

# 差分の色（GitHub の差分表示に近い色）
COLORS = {
    "removed": {"background": "#ffebe9", "foreground": "#82071e"},
    "added": {"background": "#dafbe1", "foreground": "#116329"},
    "context": {"foreground": "#57606a"},
}


def read_text_file(path: Path) -> str:
    """テキストファイルを読む。UTF-8 で読めなければ Shift_JIS（Windows の日本語）で読む。

    Tera Term のログなど、Windows で保存したファイルは Shift_JIS のことがあるため。
    """
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp932", errors="replace")


def summarize(result: CompareResult) -> str:
    """画面下に出す「何行変わるか」のまとめ。"""
    removed = sum(1 for line in result.diff if line.startswith("-"))
    added = sum(1 for line in result.diff if line.startswith("+"))
    if not result.diff:
        return "差分はありません（投入しても Config は変わりません）"
    text = f"消える行：{removed}　増える行：{added}"
    if result.notes:
        text += f"　／　読みかえのメモが {len(result.notes)} 件あります（「メモ」タブ）"
    return text


class ConfigInput(ttk.Frame):
    """見出し・「ファイルを開く」ボタン・入力欄をまとめた部品。"""

    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master, padding=4)
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text=title, font=("", 10, "bold")).pack(side="left")
        ttk.Button(header, text="クリア", command=self.clear).pack(side="right")
        ttk.Button(header, text="ファイルを開く…", command=self.open_file).pack(side="right", padx=4)

        self.text = ScrolledText(self, font=CODE_FONT, wrap="none", undo=True, height=14)
        self.text.pack(fill="both", expand=True, pady=(4, 0))

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)

    def clear(self) -> None:
        self.set("")

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("テキストファイル", "*.txt *.log *.cfg *.conf"), ("すべてのファイル", "*.*")],
        )
        if path:
            self.set(read_text_file(Path(path)))


class App(ttk.Frame):
    def __init__(self, master: tk.Tk | tk.Toplevel) -> None:
        super().__init__(master, padding=8)
        master.title(TITLE)
        master.geometry("1200x800")
        master.minsize(800, 560)
        self.pack(fill="both", expand=True)
        self.result: CompareResult | None = None

        # ---- 上段：2 つの入力欄 ----
        inputs = ttk.PanedWindow(self, orient="horizontal")
        inputs.pack(fill="both", expand=True)
        self.current = ConfigInput(inputs, "① 現行の running-config")
        self.changes = ConfigInput(inputs, "② 投入する Config")
        inputs.add(self.current, weight=1)
        inputs.add(self.changes, weight=1)

        # ---- 中段：ボタン ----
        buttons = ttk.Frame(self, padding=(0, 6))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="▶ 比較する（Ctrl+Enter）", command=self.run).pack(side="left")
        ttk.Button(buttons, text="サンプルを読み込む", command=self.load_samples).pack(side="left", padx=6)
        ttk.Button(buttons, text="結果を保存…", command=self.save_result).pack(side="right")
        ttk.Button(buttons, text="結果をコピー", command=self.copy_result).pack(side="right", padx=6)
        self.status = ttk.Label(buttons, text="①と②を貼り付けて「比較する」を押してください")
        self.status.pack(side="left", padx=12)

        # ---- 下段：結果のタブ ----
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        self.diff_view = self._add_tab("差分")
        self.expected_view = self._add_tab("投入後の想定 Config")
        self.notes_view = self._add_tab("メモ")
        for tag, options in COLORS.items():
            self.diff_view.tag_configure(tag, **options)

        legend = ttk.Label(
            self,
            text="差分の見方：赤い「-」の行は消える行、緑の「+」の行は増える行、灰色の行は変わらない親の行（どこの設定かを示す）",
            foreground=COLORS["context"]["foreground"],
        )
        legend.pack(fill="x", pady=(4, 0))

        master.bind("<Control-Return>", lambda event: self.run())

    def _add_tab(self, title: str) -> ScrolledText:
        view = ScrolledText(self.tabs, font=CODE_FONT, wrap="none", state="disabled")
        self.tabs.add(view, text=title)
        return view

    @staticmethod
    def _show(view: ScrolledText, lines: list[tuple[str, str | None]]) -> None:
        """結果の欄に行を書き込む。結果は読むだけなので、書き込んだら編集できないようにする。"""
        view.configure(state="normal")
        view.delete("1.0", "end")
        for text, tag in lines:
            view.insert("end", text + "\n", tag or ())
        view.configure(state="disabled")

    def run(self) -> None:
        try:
            self.result = compare(self.current.get(), self.changes.get())
        except Exception as error:  # 想定外の書き方でも、画面が落ちないようにする
            messagebox.showerror(TITLE, f"比較できませんでした。\n\n{type(error).__name__}: {error}", parent=self)
            return

        tags = {"-": "removed", "+": "added", " ": "context"}
        diff_lines = [(line, tags.get(line[:1])) for line in self.result.diff]
        if not diff_lines:
            diff_lines = [("差分はありません（投入しても Config は変わりません）", None)]
        self._show(self.diff_view, diff_lines)
        self._show(self.expected_view, [(line, None) for line in self.result.expected.splitlines()])
        notes = self.result.notes or ["読みかえはありません"]
        self._show(self.notes_view, [("※ " + note, None) for note in notes])

        self.status.configure(text=summarize(self.result))
        self.tabs.select(self.diff_view)

    def result_text(self) -> str:
        """いま選んでいるタブの内容（コピー・保存用）。"""
        if self.result is None:
            return ""
        view = self.tabs.nametowidget(self.tabs.select())
        return view.get("1.0", "end-1c")

    def copy_result(self) -> None:
        text = self.result_text()
        if not text:
            messagebox.showinfo(TITLE, "先に「比較する」を押してください。", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text="表示中のタブの内容をコピーしました")

    def save_result(self) -> None:
        text = self.result_text()
        if not text:
            messagebox.showinfo(TITLE, "先に「比較する」を押してください。", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".txt", filetypes=[("テキストファイル", "*.txt")]
        )
        if path:
            Path(path).write_text(text + "\n", encoding="utf-8")
            self.status.configure(text=f"保存しました：{path}")

    def load_samples(self) -> None:
        if not SAMPLES.is_dir():
            messagebox.showinfo(TITLE, f"サンプルのフォルダが見つかりません：{SAMPLES}", parent=self)
            return
        self.current.set(read_text_file(SAMPLES / "nxos_running.txt"))
        self.changes.set(read_text_file(SAMPLES / "nxos_change.txt"))
        self.run()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
