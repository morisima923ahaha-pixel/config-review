# Config再鑑アシスタント（NX-OS）

Cisco NX-OS の **現行の running-config** と **これから投入する Config** から、
**投入後の想定 Config** を作り、**何が変わるか（差分）** を表示するツールです。
Config 投入前のダブルチェック（再鑑）の手助けを目的にしています。

> ⚠️ ツールが出すのは、NX-OS の動きをもとにした「予想」です。
> 主な動きは Cisco DevNet Sandbox の Nexus 9000v（NX-OS 10.4(2)）で確かめていますが、機種やバージョンで違うことがあります。
> 最終的な判断は、必ず人が行ってください。

## できること
- 投入 Config を「文字列の足し算」ではなく、NX-OS の動きに合わせて反映する
  - `no 〇〇` で行を消す／`description` などは上書き／`interface` の中は階層ごとに反映
  - `switchport trunk allowed vlan add / remove` を計算して 1 行にまとめる
  - `vlan 30` を作ると、先頭の `vlan 1,10,20` の一覧の行も更新する
  - `ip address ... secondary` は primary を上書きしない
  - `no shutdown`・`no switchport`・`no ip redirects`・`no cdp enable` は `no` の形のまま残す
  - `vrf member` で VRF が変わると、その interface の `ip address` などの L3 の設定を消す
  - `channel-group` を入れると、その番号の `interface port-channel` を作る
- 実機ではエラーになって入らないはずの投入を見つけて、赤い【エラー】で知らせる（想定 Config には入れない）
  - L2 のポートに `ip address`、feature を有効にしていない `interface Vlan10`、secondary が残ったままの primary の削除など
- 投入 Config の書き方のゆれをそろえる
  - `conf t`・`end`・`copy run start` などの行を読み飛ばす
  - インデントのない形（`exit` 入り）も読める
  - `int e1/1`・`int po10` などの省略形、`interface Ethernet1/1-4` の範囲指定
- 差分は、どこの設定かわかるように親の行（`interface Ethernet1/1` など）をつけて表示する
- 画面（GUI）とコマンド（CLI）の両方で使える。**Python の標準ライブラリだけ**で動く（追加のパッケージ不要）

## 使い方

### 画面で使う
`start-gui.bat` をダブルクリック、またはコマンドで：
```
uv run config-review-gui
```
1. 左に現行の running-config、右に投入する Config を貼り付ける（「ファイルを開く…」でも可）
2. 「▶ 比較する」（Ctrl+Enter）
3. 下のタブで「差分」「投入後の想定 Config」「メモ（読みかえた内容）」を確認

### コマンドで使う
```
uv run config-review samples/nxos_running.txt samples/nxos_change.txt
```

### 出力の例
```
-hostname LAB-NX01
+hostname LAB-NX02
-vlan 1,10,20
+vlan 1,10,20,30
+vlan 30
+  name GUEST
 interface Ethernet1/1
-  switchport trunk allowed vlan 10,20
+  switchport trunk allowed vlan 10,20,30
```

## 開発
```
uv sync
uv run pytest -q
```

| ファイル | 役割 |
|---|---|
| `src/config_review/parser.py` | Config をインデントから親子のツリーにする |
| `src/config_review/normalize.py` | 投入 Config の書き方のゆれをそろえる |
| `src/config_review/apply.py` | 投入 Config を反映して、想定 Config を作る |
| `src/config_review/checks.py` | 実機ではエラーになるはずの投入を見つける |
| `src/config_review/vlan.py` | VLAN の一覧（`10,20-22`）の計算 |
| `src/config_review/diff.py` | 現行と想定の差分を作る |
| `src/config_review/compare.py` | 上の流れをまとめた入り口（CLI と GUI が使う） |
| `src/config_review/gui.py` | 画面（tkinter） |

## まだ対応していないこと
- `banner motd` のような複数行の設定
- `router bgp` の下の `neighbor` → `address-family` のような、インデントのない深い階層
- interface 以外のコマンドの省略形（`desc`・`sw` など）
- 機種や NX-OS のバージョンによる既定値の違い

テスト用の Config は架空のものです（IP アドレスは RFC 5737 の例示用アドレス）。
