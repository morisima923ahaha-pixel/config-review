"""Web 版（web/）のテスト。

ブラウザで動かす確認は別にしている（Pyodide とブラウザが要るので）。ここでは、ネットにつながずに確かめられること：
  - 画面に出す内容が、tkinter 版（gui.py）と同じになるか
  - 公開するフォルダに、要るファイルが全部入り、要らないファイルが入らないか
  - 安全のための決まり（ほかのサイトから読み込まない、innerHTML を使わない など）が守られているか
"""

import ast
import json
import sys
import tarfile
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from config_review.compare import compare, read_config_file

REPO = Path(__file__).parent.parent
WEB = REPO / "web"
DEMO = REPO / "samples" / "demo"
sys.path.insert(0, str(WEB))

import bridge  # noqa: E402
import build_site  # noqa: E402

CURRENT = read_config_file(next(DEMO.glob("0_*.txt")))
SCENES = sorted(p for p in DEMO.glob("*.txt") if not p.name.startswith("0_"))

# 差分なし・読みかえのメモあり・エラーと要確認あり、も含める
EXTRA_CASES = [
    ("hostname A", "hostname A"),
    ("hostname A", "conf t\nhostname B\nend"),
    ("interface Ethernet1/1\n  switchport", "interface Ethernet1/1\n  ip address 192.0.2.1/24\nno feature lacp"),
]
CASES = [(CURRENT, read_config_file(p)) for p in SCENES] + EXTRA_CASES


# ---- tkinter 版と同じ表示になるか ----

@pytest.fixture(scope="module")
def gui():
    # tkinter のない環境でも、このファイルのほかのテストは動くようにする
    # （Windows の test.yml では tkinter があるので、ここも必ず動く）
    return pytest.importorskip("config_review.gui")


@pytest.mark.parametrize("current, changes", CASES)
def test_summary_is_same_as_gui(gui, current, changes):
    result = compare(current, changes)
    assert bridge.summarize(result) == gui.summarize(result)


@pytest.mark.parametrize("current, changes", CASES)
def test_problem_lines_are_same_as_gui(gui, current, changes):
    result = compare(current, changes)
    # gui.py の _problem_view_lines は self.result しか使わないので、画面を作らずに呼べる
    assert bridge.problem_view_lines(result) == gui.App._problem_view_lines(SimpleNamespace(result=result))


@pytest.mark.parametrize("current, changes", CASES)
def test_view_has_everything_the_gui_shows(gui, current, changes):
    result = compare(current, changes)
    view = json.loads(bridge.view(current, changes))

    assert view["ok"] is True
    diff = [tuple(line) for line in view["diff"]]
    problems = gui.App._problem_view_lines(SimpleNamespace(result=result))
    assert diff[: len(problems)] == problems
    tags = {"-": "removed", "+": "added", " ": "context"}
    expected_diff = [(line, tags.get(line[:1])) for line in result.diff] or [(bridge.NO_DIFF, None)]
    assert diff[len(problems):] == expected_diff
    assert view["expected"] == result.expected.splitlines()
    assert view["notes"] == ["※ " + note for note in (result.notes or ["読みかえはありません"])]
    assert view["alert"] == bool(result.problems)


def test_view_returns_message_for_unreadable_input():
    view = json.loads(bridge.view("hostname A", "vlan 10-2"))
    assert view["ok"] is False
    assert view["message"].startswith("比較できませんでした。")
    assert "10-2" in view["message"]


def test_read_file_falls_back_to_shift_jis(tmp_path):
    path = tmp_path / "sjis.txt"
    path.write_bytes("  description 日本語\n".encode("cp932"))
    assert bridge.read_file(str(path)) == "  description 日本語\n"


# ---- 公開するフォルダの中身 ----

def test_python_files_are_all_modules_except_gui():
    modules = build_site.python_files()
    assert "gui.py" not in modules
    assert set(modules) == {p.name for p in (REPO / "src" / "config_review").glob("*.py")} - {"gui.py"}


def test_modules_do_not_import_anything_outside_the_site():
    """ブラウザに送らない gui.py や、Pyodide にない tkinter を、ほかのファイルが読み込んでいないか。"""
    modules = build_site.python_files()
    files = [REPO / "src" / "config_review" / name for name in modules] + [WEB / "bridge.py"]
    for path in files:
        name = path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module
            elif isinstance(node, ast.Import):
                imported = node.names[0].name
            else:
                continue
            assert not imported.startswith("tkinter"), f"{name} が tkinter を読み込んでいる"
            if imported.startswith("config_review."):
                assert imported.split(".")[1] + ".py" in modules, f"{name} が {imported} を読み込んでいる"


def test_copy_app_puts_needed_files(tmp_path):
    out = tmp_path / "site"
    build_site.prepare_output(out)
    build_site.copy_app(out)

    for name in build_site.WEB_FILES:
        assert (out / name).is_file()
    assert sorted(p.name for p in (out / "py" / "config_review").iterdir()) == build_site.python_files()
    assert sorted(p.name for p in (out / "demo").iterdir()) == sorted(p.name for p in DEMO.glob("*.txt"))

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["modules"] == build_site.python_files()
    assert manifest["demo"]["current"].startswith("0_")
    assert manifest["demo"]["scenes"] == [p.name for p in SCENES]
    assert manifest["pyodide"] == build_site.PYODIDE_VERSION


def test_copy_app_does_not_publish_private_files(tmp_path):
    out = tmp_path / "site"
    build_site.prepare_output(out)
    build_site.copy_app(out)
    names = {p.name for p in out.rglob("*")}
    assert "gui.py" not in names
    assert "引き継ぎメモ.md" not in names
    assert not any(name.endswith((".md", ".bat", ".toml", ".lock")) for name in names)


def test_prepare_output_refuses_to_delete_other_folders(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "important.txt").write_text("消さないで", encoding="utf-8")
    with pytest.raises(ValueError):
        build_site.prepare_output(other)
    assert (other / "important.txt").exists()


def test_prepare_output_refuses_a_folder_that_only_has_a_manifest(tmp_path):
    """manifest.json という名前のファイルは、ほかのフォルダにもありうる。目印のファイルがなければ消さない。"""
    other = tmp_path / "other"
    other.mkdir()
    (other / "manifest.json").write_text("{}", encoding="utf-8")
    (other / "important.txt").write_text("消さないで", encoding="utf-8")
    with pytest.raises(ValueError):
        build_site.prepare_output(other)
    assert (other / "important.txt").exists()


def test_prepare_output_clears_a_previous_build(tmp_path):
    out = tmp_path / "site"
    build_site.prepare_output(out)
    build_site.copy_app(out)
    (out / "old.txt").write_text("前の残り", encoding="utf-8")
    build_site.prepare_output(out)
    assert list(out.iterdir()) == [out / build_site.MARKER]  # 前の残りは消えて、目印だけ


def test_pyodide_with_wrong_hash_is_rejected(tmp_path):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        info = tarfile.TarInfo("package/pyodide.js")
        archive.addfile(info, io.BytesIO(b""))
    with pytest.raises(ValueError, match="ハッシュが違います"):
        build_site.add_pyodide(tmp_path, data.getvalue())
    assert not (tmp_path / "pyodide").exists()


def make_tgz(members: dict[str, bytes | None]) -> bytes:
    """npm の形（package/ の下）の tgz を作る。中身が None のものはリンクにする。"""
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(f"package/{name}")
            if content is None:
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                archive.addfile(info)
            else:
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
    return data.getvalue()


def test_pyodide_files_are_extracted(tmp_path, monkeypatch):
    monkeypatch.setattr(build_site, "verify_pyodide", lambda data: None)
    build_site.add_pyodide(tmp_path, make_tgz({name: name.encode() for name in build_site.PYODIDE_FILES}))
    assert sorted(p.name for p in (tmp_path / "pyodide").iterdir()) == sorted(build_site.PYODIDE_FILES)
    assert (tmp_path / "pyodide" / "pyodide.js").read_bytes() == b"pyodide.js"


def test_pyodide_link_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(build_site, "verify_pyodide", lambda data: None)
    members = {name: b"x" for name in build_site.PYODIDE_FILES} | {"pyodide.js": None}
    with pytest.raises(ValueError, match="ふつうのファイルではありません"):
        build_site.add_pyodide(tmp_path, make_tgz(members))


def test_pyodide_missing_file_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(build_site, "verify_pyodide", lambda data: None)
    with pytest.raises(ValueError, match="ありません"):
        build_site.add_pyodide(tmp_path, make_tgz({"pyodide.js": b"x"}))


# ---- 安全のための決まり ----

def test_page_loads_scripts_only_from_its_own_site():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in html
    assert "connect-src 'self'" in html
    assert "unsafe-eval'" not in html.replace("wasm-unsafe-eval'", "")
    assert "unsafe-inline" not in html
    # src="..." と href="..."（リンク以外）は、自分のサイトの中だけ
    for tag in ("<script", "<link"):
        for part in html.split(tag)[1:]:
            attrs = part.split(">")[0]
            assert "http" not in attrs, f"{tag}{attrs}> がほかのサイトから読み込んでいる"


def test_app_never_puts_config_into_html():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in app.splitlines() if not line.lstrip().startswith("//"))
    for risky in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert risky not in code, f"app.js が {risky} を使っている"


def test_pyodide_is_loaded_from_the_site_not_a_cdn():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'indexURL: new URL("pyodide/", document.baseURI).href' in app
    assert "cdn.jsdelivr" not in app
    assert build_site.PYODIDE_TARBALL.startswith("https://registry.npmjs.org/pyodide/-/pyodide-")
    assert build_site.PYODIDE_VERSION in build_site.PYODIDE_TARBALL
