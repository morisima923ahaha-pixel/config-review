import sys
from pathlib import Path

from config_review.parser import parse_config, to_text


def main() -> None:
    """Config ファイルを読み込み、ツリーとして解釈した結果を表示する（動作確認用）。"""
    if len(sys.argv) != 2:
        print("使い方: config-review <running-config のファイル>")
        sys.exit(1)

    config_text = Path(sys.argv[1]).read_text(encoding="utf-8")
    print(to_text(parse_config(config_text)))
