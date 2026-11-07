# notam-fireworks

[skyinfo.jp](https://www.skyinfo.jp/) に掲載された FIREWORKS の NOTAM を蓄積し、
年ごとの KMZ（1/1〜12/31）を GitHub Actions で自動更新します。

- `update_fireworks.py`: 取得・解析・KMZ 生成
- `data/fireworks_YYYY.json`: 年別の履歴
- `kmz/fireworks_YYYY.kmz`: 年別の KMZ（月別フォルダ）
- `fireworks.kml`: 全年の KMZ をまとめる親ファイル

更新は 1 日 2 回（JST 06:17 / 18:17）。Actions タブの「Run workflow」で手動実行もできます。

## Google Earth Pro への登録

1. メニューの「追加」→「ネットワークリンク」を開く
2. リンクに `fireworks.kml` の raw URL を入力する
   `https://raw.githubusercontent.com/<ユーザー名>/<リポジトリ名>/main/fireworks.kml`
3. 「更新」タブの時間ベースの更新を「定期的」「1 時間」にする

一度登録すれば、新しい年の KMZ も自動で追加されます。

## データの扱い

- `E)FIREWORKS` で始まる NOTAM だけを抽出します（進入方式変更などの関連 NOTAM は対象外）
- 年と月は開始日時（JST）で振り分けます
- 最大号数は G 項の高さから「開花高度 + 開花半径」が収まる最大の号数として推定した目安です
- 取り消された NOTAM は履歴に残ります（差し替え `NOTAMR` は新しい内容に置き換えます）
- サイトのページを通常どおり表示して読み取るため、ヘッドレス Chrome を使っています
