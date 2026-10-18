import tkinter as tk

import pytest

from config_review.compare import read_config_file
from config_review.gui import App


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


def test_read_config_file_falls_back_to_shift_jis(tmp_path):
    path = tmp_path / "log.txt"
    path.write_bytes("description 本社".encode("cp932"))

    assert read_config_file(path) == "description 本社"


def test_invalid_input_shows_error_instead_of_crashing(app, monkeypatch):
    shown = []
    monkeypatch.setattr("config_review.gui.messagebox.showerror", lambda *args, **kwargs: shown.append(args))
    app.current.set("vlan 1,10")
    app.changes.set("vlan 10-2")

    app.run()

    assert shown and "10-2" in shown[0][1]


def test_rejected_lines_are_shown_above_diff(app):
    app.current.set("interface Ethernet1/1\n  switchport mode trunk")
    app.changes.set("interface Ethernet1/1\n  ip address 192.0.2.1/30\n  description UPLINK")

    app.run()

    lines = app.diff_view.get("1.0", "end-1c").splitlines()
    assert lines[0].startswith("【エラー】")
    assert "ip address 192.0.2.1/30" in lines[1]
    assert lines[-1] == "+  description UPLINK"
    assert app.diff_view.tag_ranges("error")
    assert "エラーになるはずの行：1" in app.status.cget("text")
