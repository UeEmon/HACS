# HACS 開発引き継ぎ書

作成日：2026-10-13（日本時間）  
対象リポジトリ：https://github.com/UeEmon/HACS  
対象ブランチ：`main`  
本書作成前の基準コミット：`ac132010b5032c40673696f02c1c1a41d178c318`  
ライセンス：Apache-2.0

## 1. 引き継ぎ時点の結論

HACS（HF Aircraft Calling System）は、航空機の4桁機番号から航空機用SELCALと互換性を意図した呼び出し音声を生成するWebアプリです。16音・32音、鍵付きのコード対応、プリセット、内部ループバック、無線機・航空機側受信装置エミュレータ、ホスト音声／シリアルPTTドライバを実装しています。

**次の開発の中心は、対象無線機の仕様確定と、Web本体からホストサービスを経由して接続・送信を操作する機能です。** 現在のWeb画面は機器設定の保存・JSON出力までで、実機への接続・切断・直接送信は行いません。ホストCLIには実出力機能がありますが、実機試験は未実施です。

この引き継ぎでは既存データ・秘密情報の移送や実送信は実施していません。秘密鍵・管理トークンは本書・Gitリポジトリに含めません。

## 2. 決定済み仕様

| 項目 | 決定内容 |
|---|---|
| 名称 | HACS。互換対象の名称SELCALをシステム名に使用しない |
| 対象 | 航空機用SELCALの送信側。受信は試験用エミュレータ |
| 機番号 | 半角数字4桁、0000〜9999。先頭の0を保持 |
| 呼び出し方式 | 従来16音／SELCAL 32。明示的に選択 |
| 音声 | 48 kHz、16 bit、モノラル。2音1秒、無音0.2秒、2音1秒 |
| コード対応 | HACS独自変換。実機に割り当てられたコードと自動的に一致するものではない |
| 秘匿 | 共通鍵による機番号とコードの対応変更。音声・RF通信自体の暗号化ではない |
| 鍵 | 256 bit親鍵。漏えい時は独立した新しい親鍵へ即時更新 |
| 周期 | 日／週（月曜）／月（1日）、日本時刻00:00。WebからON/OFFと周期を変更可能 |
| 呼び出し先 | プリセット登録・更新・削除、選択呼び出し、現在コード一覧・CSV |
| 対象無線機 | 未確定・メーカー限定なし。暫定基準は`HACS-STD-ANALOG-v1`（アナログ音声入力＋接点PTT）。国際電気・日立国際、R&S、Icomの資料／サンプルあり |
| 動作環境 | 本体はDocker、Windows／macOS／Linuxを想定。ローカル開発環境はApple Silicon搭載Mac。実機ドライバ・SDKの対応は別確認 |
| Git・ライセンス | GitHub main、Apache-2.0 |

## 3. 現在の画面

| タブ | 内容 |
|---|---|
| 呼び出し操作 | 相手選択、16/32音、機番号、受信設定コード、WAV生成・再生・保存、内部ループバック |
| 無線機インターフェース | メーカー・型式、音声デバイス、共通出力レベル、シリアルPTT、時間設定、保存・再読込・JSON出力、エミュレータへのリンク |
| 呼び出し先管理 | 呼び出し操作と独立したプリセット編集、現在コード一覧、CSV |
| 秘匿設定 | 管理トークンを用いた秘匿ON/OFF・周期変更、緊急親鍵更新 |
| 操作・更新履歴 | ブラウザ内の音声生成・内部確認記録、サーバ側の鍵・秘匿設定更新履歴 |

共通出力レベルは1〜90%のデジタル振幅。画面読込時に保存値を適用し、変更時に生成済み音声を無効化します。端子電圧やRF送信電力を直接設定するものではありません。

ブラウザの操作履歴はlocalStorageに最大200件、UTCで保存し、JSON出力・削除が可能です。サーバの送信監査記録ではなく、他端末との共有もありません。

## 4. 起動・停止

### 通常構成（固定変換＋全エミュレータ）

```sh
git clone https://github.com/UeEmon/HACS.git
cd HACS
docker compose -f compose.yaml -f compose.emulators.yaml up -d --build
```

| サービス | URL | 主な用途 |
|---|---|---|
| hacs | http://localhost:8787 | 本体 |
| receiver | http://localhost:8788 | WAVを手動投入する受信試験 |
| radio-emulator | http://localhost:8789 | 模擬PTT、WAV生成・航空機側への転送 |
| aircraft-emulator | http://localhost:8790 | 自機番号・方式の設定、PCM解析・呼び出し判定 |

Composeの公開ポートは127.0.0.1へバインドします。別端末からのLAN利用を前提とした認証・公開設定は未整備です。リンクのlocalhostはブラウザを開いている端末を指します。

### Web秘匿切替・共有鍵を使用する構成

Python 3.10以降で、初回のみ別用途の管理トークンを作成します。既存ファイルは上書きしません。環境に応じて`python`を`python3`へ読み替えます。

```sh
python generate_key.py --output .secrets/admin.token
docker compose -f compose.yaml -f compose.emulators.yaml -f compose.rotation.yaml -f compose.emulators.rotation.yaml up -d --build
```

トークンファイルは操作者が保護された環境で参照し、管理操作時に入力します。親鍵は本体が初期化し、共有ボリュームへ格納します。Webで変更した秘匿設定はDBに保存され、以後は`HACS_ROTATION`より優先します。初期既定はdailyです。

```sh
docker compose -f compose.yaml -f compose.emulators.yaml -f compose.rotation.yaml -f compose.emulators.rotation.yaml ps
docker compose -f compose.yaml -f compose.emulators.yaml -f compose.rotation.yaml -f compose.emulators.rotation.yaml logs --tail=100
docker compose -f compose.yaml -f compose.emulators.yaml -f compose.rotation.yaml -f compose.emulators.rotation.yaml down
```

停止・状態確認は起動時と同じComposeファイルを指定します。通常構成の場合はrotationの2ファイルを除いてください。`down -v`は鍵と登録データを削除するため、通常停止に使いません。`depends_on`は鍵準備完了を保証しません。受信部は共有鍵ストアが作成されるまで最大60秒（`HACS_KEY_WAIT_SECONDS`）待機し、エミュレータは準備完了まで503を返します。実Docker環境での初回起動の挙動は引き続き確認してください。

## 5. 最初に行う動作確認

1. 本体で5501・16音を選び、受信設定コードとWAVを生成。内部ループバックが合格することを確認。
2. 32音でも同様に確認。出力レベル変更後に再生成が必要になることを確認。
3. 呼び出し先管理で0001を登録し、操作タブから選択。一覧・CSVで先頭0を確認。
4. 航空機エミュレータの自機を5501に設定。無線機エミュレータで5501のWAVを生成し、模擬送信。自機呼び出し判定を確認。
5. 別番号では他機判定、無音WAVでは未検出を確認。
6. 共有鍵構成で秘匿周期を変更。送受信の期間・鍵識別子を照合し、旧WAVの拒否を確認。
7. 無線機設定を保存・再読込し、JSON出力。保存値の復元と入力検証を確認。ここでは実出力しない。

無線機エミュレータへのHACS音声投入はWAV保存・アップロードです。本体からの直接転送は未実装です。模擬PTT解除後にWAVをHTTP転送するバッファ方式で、リアルタイムRF伝搬を再現しません。

## 6. コードの読み始め

| ファイル | 担当 |
|---|---|
| `server.py`、`index.html` | 本体HTTP API・画面、インライン音声操作 |
| `tabs_ui.js` | タブとブラウザ操作履歴 |
| `selcal.py`、`tail_mapping.py` | トーン生成、16/32音・基礎の機番号変換 |
| `rotation.py`、`rotation_ui.js` | JST期間、鍵付き対応、状態取得、旧音声の無効化 |
| `key_store.py`、`key_admin.py` | 親鍵、設定、変更履歴、管理トークン認証 |
| `security_ui.js`、`keys_ui.js` | Web秘匿切替・親鍵更新 |
| `presets.py`、`preset_exports.py`、`presets_ui.js` | プリセット・現在コード一覧・CSV |
| `receiver.py`、`receiver_server.py` | PCMからの検出と手動WAV受信試験 |
| `loopback_ui.js`、`wav_context.py` | 実生成WAVの内部確認、試験用期間・鍵情報 |
| `emulator_server.py`、`emulator_ui.js` | 無線機／航空機の独立サービス |
| `radio_interface.py` | AudioOutput／PTTOutput契約、出力順序・期限・解除 |
| `radio_drivers.py`、`radio_host.py` | sounddevice・pySerialを用いるホストドライバ／CLI |
| `radio_dry_run.py` | 実出力しないインターフェース動作確認 |
| `radio_calibration.py` | 標準アナログ無線機のレベル校正。校正信号の生成・出力（PTTなし）と減衰量の算出 |
| `radio_settings.py`、`radio_settings_ui.js` | Web設定保存、世代照合、プロファイルJSON |
| `radio_templates/` | 汎用・機種別サンプル。実行可能範囲は各backendを確認 |

本体はPython標準ライブラリ中心です。ホスト実出力には`requirements-radio.txt`の依存とOS側の音声基盤が必要です。Dockerイメージへの同梱はホスト用ソフトウェアの実接続を意味しません。

## 7. APIと保存先

| API | 用途 |
|---|---|
| GET `/tone.wav`、`/api/convert` | WAV・コード生成 |
| GET `/api/rotation` | 現在のモード・期間・鍵識別子・設定世代 |
| GET/POST `/api/presets` | プリセット管理 |
| GET `/api/presets/codes`、`/api/presets/export.csv` | 現在コード一覧 |
| POST `/api/loopback` | WAVの内部照合 |
| GET/POST `/api/keys` | 管理トークン必須の履歴取得・親鍵更新 |
| POST `/api/security` | 管理トークン必須の秘匿モード・周期変更 |
| GET/POST `/api/radio-settings` | 無線機設定の取得・保存（実出力なし） |

`/api/security`は`cadence`と`expected_revision`、`/api/radio-settings`は`profile`と`revision`を受け取り、古い世代による変更を拒否します。すべてのAPIが管理認証付きではありません。LAN公開・遠隔操作を追加する際は認証と権限を別途設計してください。

| 保存対象 | 場所・扱い |
|---|---|
| プリセット | `/data/presets.sqlite3`、`hacs_data` |
| 無線機プロファイル | `/data/radio.sqlite3`、`hacs_data` |
| 親鍵・秘匿設定・更新履歴 | `/keydata/keys.sqlite3`、`hacs_keys`。受信側は読み取り専用 |
| 管理トークン | `.secrets/admin.token` → 本体Docker secret |
| ブラウザ操作履歴 | localStorage `hacs.activity.v1` |
| エミュレータの自機設定・直近結果 | メモリ。再起動で初期化 |

稼働データの移管はこの作業とは別です。停止中の整合したバックアップ、保存先権限、鍵を含む安全な移送、復旧後の世代・期間照合を計画してください。旧バックアップの復元は失効鍵の再有効化につながり得ます。

## 8. 検証状況と再実行方法

2026-10-14の再現確認で、Pythonテスト60件と以下のNode画面ロジック試験の合格を確認しました。詳細は[再現確認記録 2026-10-14](verification-2026-10-14.md)を参照してください。

```sh
python -m unittest discover -v
node test_ui.js
node test_loopback_ui.js
node test_tabs_ui.js
node test_security_ui.js
node test_radio_settings_ui.js
```

検証済み：機番号変換、トーン規則、生成PCM・検出、鍵／期間、プリセット、API認証・Origin検証、模擬サービス間通信、ホストドライバのモック、設定保存・出力レベル、画面ロジック。

2026-10-14追加検証：Dockerfileの`COPY`対象と同じファイル構成で4サービスを起動し、`e2e_check.py`で手順1〜7（通常構成27件・共有鍵構成41件）に合格。ヘッドレスChromiumでPC・iPad・スマートフォン幅の5タブ操作、ループバック、キー操作、エミュレータ画面（45件）に合格。サービス再起動後のデータ保持も確認済み。

**未検証：Dockerイメージのビルド・コンテナ制限下の実起動（作業環境からレジストリへ接続できず）、Windows/macOS/Linux実環境一式、実機ブラウザでの音声再生・WAV保存・iPad Safari、実機音声端子・PTT・RF送信、実受信装置との適合性。**

起動済みの環境に対しては、次のコマンドで同じ確認を再実行できます（共有鍵構成での実行は鍵世代を1つ進めるため、試験環境でのみ使用）。

```sh
python3 e2e_check.py
python3 e2e_check.py --token-file .secrets/admin.token
```

## 9. 未完了事項と次担当の着手順

| 優先 | 作業 | 完了条件 |
|---|---|---|
| 1 | Docker・実ブラウザで再現確認（イメージ相当構成・ヘッドレスブラウザでは2026-10-14に完了） | 実Docker環境で`docker compose up --build`後に`e2e_check.py`を両構成で実行し、実機ブラウザで音声再生・WAV保存を確認して記録 |
| 2 | 対象無線機・資料確定（未確定。暫定基準として[標準アナログ無線機仕様](standard-analog-radio-spec.md)を2026-10-14に作成） | 型式・FW・ICD・音声/PTT端子・許容値を機種別記入票に記入し、標準適合か差分ありかを判定 |
| 3 | Web↔ホストサービス設計 | API、認証、接続状態、機器排他、WAV受渡し、ジョブID、取消・期限・異常解除を定義 |
| 4 | ホストサービス実装・模擬試験 | 機器列挙、接続切断、設定適用、二重実行防止、異常時PTT解除を試験 |
| 5 | 機種別接続・レベル校正 | 配線図と実測記録、音声レベル・トーン・PTT時間が仕様内 |
| 6 | 実機・受信試験 | 対応する16/32音の呼び出し検出を確認し、制限事項を記録 |

追加残件：サーバ側の送信履歴、複数利用者の認証・権限、別環境への鍵配布、機種固有Ethernet・シリアルコマンド・1553ドライバ。これらを実装済みとして扱わないでください。

## 10. 変更時に保持すべき条件

- 4桁機番号と先頭0、16/32音の独自アルファベット順序・変換ベクトルを保持する。
- 鍵／周期の1スナップショットでコード・一覧・WAVを作り、更新後の古い音声利用を拒否する。
- 秘密鍵・管理トークンをGit、API応答、ブラウザ永続領域、ログへ出力しない。
- WAV内の期間・鍵識別子は署名なしの試験情報。RF認証・リプレイ防止と解釈しない。
- 標準ドライラン、実出力の明示指定、処理の排他、PTT解除を維持する。プロセス停止・ドライバ停止までの解除保証には現地回路等の検討が必要。
- 「音声生成」「再生完了」「PTT解除」「装置送信状態」「実受信成功」を区別する。
- メーカー紹介・調達文書を根拠に、ピン配置・電圧・コマンドや実機適合性を推定しない。

## 11. 関連資料

- [README](../README.md)：入口・起動
- [再現確認記録 2026-10-14](verification-2026-10-14.md)：イメージ相当構成・ヘッドレスブラウザでの確認結果、`e2e_check.py`
- [無線機インターフェース必要項目・記入票](radio-interface-requirements.md)：次の実機開発の主資料
- [標準アナログ無線機仕様](standard-analog-radio-spec.md)：対象機確定までの設計基準、校正・適合試験
- [汎用音声・PTT](generic-radio-interface.md)：契約・ホスト適用・レベル設定
- [Ethernet・シリアル・1553](radio-transport-options.md)：方式別の設計検討
- [自動更新・鍵管理](automatic-rotation-and-management.md)：保存・運用・管理API
- [エミュレータ](emulators.md)：構成・操作・制限
- [システム構成図](system-architecture.md)
- [16/32音仕様](dual-mode-spec.md)
- `docs/radio-samples/`：Icom、R&S、国際電気／日立国際、LRTの公開資料調査

担当者・実機保有者・資料入手先・試験場所・接続対象の最終型式は、リポジトリ上では未確定です。次担当へ割り当てる際に別途記入してください。
