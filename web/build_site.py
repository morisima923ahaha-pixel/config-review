"""GitHub Pages に置く Web 版のフォルダを組み立てる。

使い方: uv run python web/build_site.py <出力先のフォルダ>
（GitHub Actions の pages.yml も、手元で確かめるときも、これを使う）

組み立てたフォルダの中身：
  index.html・app.js・style.css・bridge.py・favicon.svg   web/ の画面
  py/config_review/*.py                      ツールの本体（gui.py 以外。tkinter はブラウザで使えないため）
  demo/*.txt                                 samples/demo/ の架空の Config
  pyodide/                                   ブラウザの中で Python を動かす Pyodide の本体
  manifest.json                              画面が読み込むファイルの一覧（ここで自動で作る）

Python のコードはリポジトリの中でコピーせず、組み立てるときにだけ集める。直すのは src/ の 1 か所で済む。
Pyodide は CDN から読み込まず、npm の公式の置き場所から取ってきて、ハッシュが決めた値と同じか確かめてから同梱する。
ページを開いてもほかのサイトにつながらないので、CDN が書き換えられても入力した Config を盗まれない。
"""

import base64
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"
PACKAGE = REPO / "src" / "config_review"
DEMO = REPO / "samples" / "demo"

# Pyodide を新しくするときは、3 つとも変える（ハッシュは `npm view pyodide@<版> dist.integrity` の sha512- のあと）
PYODIDE_VERSION = "0.29.5"
PYODIDE_TARBALL = f"https://registry.npmjs.org/pyodide/-/pyodide-{PYODIDE_VERSION}.tgz"
PYODIDE_SHA512 = "TkYrUv9m8QmfImADKRmpwZulL48E0uUaBSO+dvRQKyAJc0qh9gu7jn8btyHPh3NZm1r2IH2YrJhIr7Q2B9urAw=="
# 標準ライブラリしか使わないので、本体のこれだけでよい（追加のパッケージは読み込まない）
PYODIDE_FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]

WEB_FILES = ["index.html", "app.js", "style.css", "bridge.py", "favicon.svg"]
EXCLUDED_MODULES = {"gui.py"}  # tkinter を使うので、ブラウザでは動かない
# 組み立てたフォルダの目印。これがあるフォルダだけを、組み立て直すときに消してよいとみなす
MARKER = ".config-review-site"
MARKER_TEXT = "web/build_site.py が組み立てたフォルダ（組み立て直すと中身はすべて消える）\n"


def python_files() -> list[str]:
    """ブラウザで読み込むツールのファイル。足したファイルも自動で入るように、除く方だけを決めておく。"""
    return sorted(p.name for p in PACKAGE.glob("*.py") if p.name not in EXCLUDED_MODULES)


def demo_files() -> tuple[str, list[str]]:
    """デモの現行 Config（0_ で始まる 1 つ）と、場面のファイル（1_〜）。"""
    current = [p.name for p in DEMO.glob("0_*.txt")]
    if len(current) != 1:
        raise ValueError(f"samples/demo/ に 0_ で始まる現行 Config が 1 つではありません：{current}")
    scenes = sorted(p.name for p in DEMO.glob("*.txt") if not p.name.startswith("0_"))
    return current[0], scenes


def verify_pyodide(data: bytes) -> None:
    """取ってきた Pyodide が、決めた版と同じものか（途中で書き換えられていないか）を確かめる。"""
    digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if digest != PYODIDE_SHA512:
        raise ValueError(f"Pyodide {PYODIDE_VERSION} のハッシュが違います（{digest}）。使わずに止めます")


def download_pyodide() -> bytes:
    with urllib.request.urlopen(PYODIDE_TARBALL, timeout=120) as response:
        return response.read()


def prepare_output(out: Path) -> None:
    """出力先を空にする。まちがえてほかのフォルダを消さないよう、空のフォルダか、目印のある前に組み立てたフォルダだけを消す。"""
    if out.exists():
        marker = out / MARKER
        built_before = marker.is_file() and marker.read_text(encoding="utf-8") == MARKER_TEXT
        if any(out.iterdir()) and not built_before:
            raise ValueError(f"{out} は空ではなく、前に組み立てたフォルダでもないので、消さずに止めます")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARKER).write_text(MARKER_TEXT, encoding="utf-8")


def copy_app(out: Path) -> None:
    """Pyodide 以外（画面・ツールの本体・デモ・一覧）を置く。"""
    for name in WEB_FILES:
        shutil.copy2(WEB / name, out / name)

    (out / "py" / "config_review").mkdir(parents=True)
    modules = python_files()
    for name in modules:
        shutil.copy2(PACKAGE / name, out / "py" / "config_review" / name)

    (out / "demo").mkdir()
    current, scenes = demo_files()
    for name in [current, *scenes]:
        shutil.copy2(DEMO / name, out / "demo" / name)

    manifest = {
        "modules": modules,
        "demo": {"current": current, "scenes": scenes},
        "pyodide": PYODIDE_VERSION,
        # どの commit から作ったページかを画面の下に出す（GitHub Actions では GITHUB_SHA に入っている）
        "commit": os.environ.get("GITHUB_SHA", "local")[:7],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def add_pyodide(out: Path, data: bytes) -> None:
    verify_pyodide(data)
    (out / "pyodide").mkdir()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for name in PYODIDE_FILES:
            # npm の tgz は package/ の下に入っている。名前を決めて取り出すので、ほかの場所には書き込まない
            try:
                info = archive.getmember(f"package/{name}")
            except KeyError:
                raise ValueError(f"Pyodide の tgz に {name} がありません") from None
            if not info.isfile():  # リンクなど、ふつうのファイル以外は使わない
                raise ValueError(f"Pyodide の tgz の {name} が、ふつうのファイルではありません")
            (out / "pyodide" / name).write_bytes(archive.extractfile(info).read())


def build(out: Path, pyodide_data: bytes) -> None:
    prepare_output(out)
    copy_app(out)
    add_pyodide(out, pyodide_data)


def main() -> None:
    if len(sys.argv) != 2:
        print("使い方: python web/build_site.py <出力先のフォルダ>")
        sys.exit(1)
    out = Path(sys.argv[1]).resolve()
    build(out, download_pyodide())
    print(f"組み立てました：{out}")


if __name__ == "__main__":
    main()
