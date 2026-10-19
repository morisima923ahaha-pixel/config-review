# デモの場面

どの場面も、左（① 現行の running-config）は共通の `running-config.txt` です。
右（② 投入する Config）に場面のファイルを「ファイルを開く…」で読み込んで、「▶ 比較する」を押します。
Config はすべて架空です（IP アドレスは例示用の 192.0.2.0/24・198.51.100.0/24）。

| 場面 | ファイル | 見どころ |
|---|---|---|
| 1 | `1_物理インターフェースの設定変更.txt` | `description`・`switchport access vlan` は上書きされ、古い行が消える。`shutdown` は `no shutdown` に置き換わる |
| 2 | `2_ポートチャネルの追加.txt` | `interface Ethernet1/3-4` の範囲指定を 1 つずつに分けて反映する。新しい `port-channel10` は show run と同じく Ethernet より前に出る |
| 3 | `3_allowed_vlanの追加.txt` | `allowed vlan add 30` を計算して `10,20,30` の 1 行にする。`add` を消して比べると、10 と 20 が消える（通信断）のがわかる |
| 4 | `4_vrfの変更でipが消える.txt` | 投入は `vrf member` の 1 行だけなのに、`ip address` が消える（NX-OS の動き。Nexus 9000v で確認） |
| 5 | `5_L2のポートにip_address.txt` | L2 のポートに `ip address` は実機ではエラーになるので、赤い【エラー】で知らせて想定 Config には入れない |

- 1・2 は「ふつうの変更が正しく反映される」例、3〜5 は「見落としやすい・間違えやすい」例です
- 場面のファイルの先頭の `!` の行は説明のコメントで、ツールは読み飛ばします
