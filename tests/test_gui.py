import tkinter as tk

import pytest

from config_review.gui import App, read_text_file


@pytest.fixture(scope="module")
def root():
    # Tk() を何度も作り直すと、ときどき初期化に失敗するので、1 つだけ作って使い回す
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"画面を表示できない環境：{error}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(root):
    window = tk.Toplevel(root)
    window.withdraw()
    yield App(window)
    window.destroy()


def test_compare_button_shows_colored_diff(app):
    app.current.set("interface Ethernet1/1\n  shutdown")
    app.changes.set("int e1/1\nno shutdown")

    app.run()

    assert app.diff_view.get("1.0", "end-1c").splitlines() == [
        " interface Ethernet1/1",
        "-  shutdown",
        "+  no shutdown",
    ]
    assert app.diff_view.tag_ranges("removed")
    assert app.diff_view.tag_ranges("added")
    assert "消える行：1" in app.status.cget("text")


def test_notes_tab_shows_normalization(app):
    app.current.set("hostname A")
    app.changes.set("conf t\nhostname B\nend")

    app.run()

    assert "conf t" in app.notes_view.get("1.0", "end-1c")


def test_no_difference_message(app):
    app.current.set("hostname A")
    app.changes.set("hostname A")

    app.run()

    assert "差分はありません" in app.diff_view.get("1.0", "end-1c")


def test_samples_can_be_loaded(app):
    app.load_samples()

    assert "+hostname LAB-NX02" in app.diff_view.get("1.0", "end-1c")


def test_read_text_file_falls_back_to_shift_jis(tmp_path):
    path = tmp_path / "log.txt"
    path.write_bytes("description 本社".encode("cp932"))

    assert read_text_file(path) == "description 本社"
