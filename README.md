# HACS — HF Aircraft Calling System

HF航空機呼び出しシステム。4桁の機番号をHACS独自規則で選択した16音／32音のコード形式に変換し、送信音声を生成します。実機の既存コード割当との一致は未確認です。

従来16音とSELCAL 32・4文字コードに対応する送信音声エンコーダです。Python標準ライブラリのみで動作します。Web操作画面、音声再生、WAV保存、CLI、Docker構成を含みます。Windows・Mac・Linuxで同一のLinuxコンテナを使用する構成です。既存受信装置との互換性を目標にした音声試作版であり、実機での相互接続・航空運用の適合性は未確認です。

## ライセンス

HACSの独自ソースコードと付属説明書は **Apache License 2.0** で提供します。
Copyright 2026 UeEmon and HACS contributors.

利用・改変・商用利用・再配布が可能です。再配布時はライセンス本文と必要な表示を保持し、改変したファイルには変更した旨を明記してください。詳細は [LICENSE](LICENSE) と [NOTICE](NOTICE) を参照してください。名称・商標の使用許諾や航空運用の認証を意味するものではありません。

Python・コンテナ内の第三者ソフトウェアにはそれぞれのライセンスが適用されます。[第三者ソフトウェア情報](THIRD_PARTY_NOTICES.md) を参照してください。Docker Desktopの契約は別で、政府機関での利用には有償サブスクリプションが必要です。導入支援・保守は別途契約で提供できます。

## システム構成

[システム構成図](docs/system-architecture.md)に、全体構成、内部ループバック、共通鍵・期間管理、実無線機との接続境界を記載しています。

## 起動

Python 3.10以降:

```bash
cd HACS
python3 server.py
```

ブラウザで http://localhost:8787 を開きます。

Docker Desktop（Intel / Apple Silicon）またはLinux Docker:

```bash
cd HACS
docker compose up --build -d
```

Docker実行および各OSでの実行はこの開発環境では未検証です。ポートはローカル端末のみからアクセスできます。

## Windows・Mac・Linux共通構成

| 処理 | 実行場所 |
|---|---|
| コード検証・音声生成・Web画面配信 | Linuxコンテナ |
| 再生・停止・WAV保存 | ホスト端末のブラウザ |
| USB音声機器の管理・音声出力先選択 | ホストOS |
| 無線機の音声入力 | ホスト端末の音声出力と接続 |
| PTT制御 | 将来の無線機アダプタ（未実装） |

コンテナへのUSB音声デバイス割り当ては不要です。Windows・MacはDocker DesktopをLinuxコンテナモードで使用します。LinuxはDocker EngineとComposeプラグイン、またはDocker Desktopを使用します。Dockerサービスを起動してから、ZIPを展開したフォルダで操作してください。

Windows PowerShell:

```powershell
cd HACS
docker compose up --build -d
```

Mac / Linuxのターミナル:

```bash
cd HACS
bash start.sh
```

Windows用の起動スクリプト `start.ps1` も同梱します。PowerShellの実行ポリシーでスクリプトが実行できない場合は、上記のDockerコマンドを直接実行してください。

すべてのOSで http://localhost:8787 を開き、OSの音声出力設定で無線機に接続したUSB音声機器等を選択します。初回起動にはベースイメージを取得するネットワーク接続が必要です。Intel Mac / Apple Siliconのどちらも対象とし、ComposeでCPUアーキテクチャを固定しません。

停止とログ確認（全OS共通）:

```bash
docker compose down
docker compose logs --tail 100 hacs
```

音声再生には利用者の操作が必要です。Dockerホストから自動で音声を出す方式、音声出力先をアプリから固定する機能、PTTとの自動同期は現段階では未実装です。ブラウザが別の端末にある場合、音声もその端末から出るため、無線機に接続した端末で操作します。

CLIで音声生成:

```bash
python3 selcal.py AC-BD --output AC-BD.wav --level 0.5
python3 -m unittest -v
```

## 自動更新・プリセット・共通鍵管理

[起動と操作の説明](docs/automatic-rotation-and-management.md)。日本時刻00:00（日次／週次は月曜／月次は1日）に対応表を自動切替します。プリセットは名称・機番号・方式を保存し、コードは現在の鍵で計算します。共通鍵の漏えい時は管理トークンを使って新しい鍵へ即時切替できます。

```bash
python3 generate_key.py --output .secrets/admin.token
docker compose -f compose.yaml -f compose.rotation.yaml up --build -d
```

初回起動で親鍵を生成し、送信部・受信部が共有ストアを使用します。既存管理トークンは上書きしません。既定は日次、週次・月次は `.env` に `HACS_ROTATION=weekly` または `monthly` を設定します。通常の `docker compose up` は従来どおり鍵なしです。Docker構成の動作はこの環境では未検証です。

## 操作

1. 相手の機番号を半角数字4桁で入力する（例: `5501`）。
   入力すると「受信側に設定するコード」を表示します（`5501` → `EM-DL`）。受信画面にも自機番号から変換した「自機の受信設定コード」を表示します。音声生成・受信判定を行う前に確認できます。
2. WAV出力レベルを設定し「音声を生成」を押す。
3. WAV保存または音声再生で信号を確認する。

音声はブラウザを開いた端末の選択済み音声出力から出ます。Dockerホスト側の音声出力ではありません。設定を変更したら再生成が必要です。画面に機番号と変換結果を表示します。機番号からの変換結果は当該機の実際のSELCALコード割当を確認するものではありません。

## 実送信前の内部ループバック確認

送信画面で「音声を生成」した後、「内部ループバック確認」を押します。保存・再生に使う同じWAVをサーバー内の受信シミュレータ処理へ渡し、PCM音声から検出したコード、2組の信号長、無音間隔を確認します。検出した呼び出しが1件で期待コードと一致した場合に「合格」と表示します。従来16音・SELCAL 32の両方に対応し、別の受信コンテナの起動や音声の再生は不要です。

機番号・方式・出力レベルの変更、音声の再生成、鍵・期間の更新後は確認結果を無効にします。鍵付きWAVは現在の鍵・期間のものだけを受け付け、解析中に鍵・期間が変わった場合も結果を拒否します。

これはシステム内のデジタル音声確認です。OS音量、音声端子、無線機入力、PTT、RF送信経路や実受信装置の動作は確認しません。送信機能に強制的な許可条件を追加するものではなく、確認後に利用者が再生・保存を操作します。

API: `POST /api/loopback?tail_number=5501&mode=selcal16`、`Content-Type: audio/wav`、本文は生成WAV（最大2 MB）。鍵付き構成では`period_id`・`key_id`を併記できます。結果の`passed`が内部確認の成否、`detection`が受信解析結果です。

## 4桁の機番号変換

変換方式は `HACS-TN16-v1`。`0000`〜`9999` を重複なく変換し、逆変換で先頭のゼロを含む4桁を復元します。有効な従来SELCALコード10920通りの先頭10000通りを使用します。

```bash
python3 tail_mapping.py --tail 5501
python3 tail_mapping.py --code EM-DL
python3 selcal.py --tail 5501 --output HACS-5501.wav
```

変換APIは `/api/convert?tail_number=5501`、逆変換は `/api/convert?code=EM-DL`。音声生成は `/tone.wav?tail_number=5501`。従来の直接コード指定 `/tone.wav?code=AC-BD` も試験用に利用できます。同時指定は拒否します。

**この規則はHACS独自です。既存航空機に登録されたSELCALコードと一致する保証はありません。** 実機接続は保留中であり、現段階では同一変換規則を使う送信部と受信シミュレータ間の検証に使用します。

32音の変換は `HACS-TN32-v1`。追加音を含む10000コードを使い、従来変換と衝突しません。機番号 `5501` は16音で `EM-DL`、32音で `AT-U7` となります。方式を省略した既存API/CLIは従来16音のままです。

```bash
python3 tail_mapping.py --tail 5501 --mode selcal32
python3 selcal.py --tail 5501 --mode selcal32 --output HACS-5501-selcal32.wav
```

32音のAPI例は `/api/convert?tail_number=5501&mode=selcal32`、`/tone.wav?tail_number=5501&mode=selcal32`。受信APIには `mode=selcal32`（受信能力）と `own_mode=selcal32`（自機変換方式）を指定します。受信側の `own_mode` を省略した場合は `mode` と同じになります。

詳細と一意性の説明: [機番号変換アルゴリズム](docs/tail-number-mapping.md)。

公開仕様との照合結果: [SELCAL互換性確認](docs/selcal-compatibility.md)。従来16音の形式とデジタル波形を確認済みですが、実機設定コードの一致と実機相互接続は未確認、SELCAL 32の追加音も生成・検出します。

対応仕様: [二方式対応仕様 v1](docs/dual-mode-spec.md)。従来16音とSELCAL 32の選択、固定周波数表、既存変換の維持、32音向け変換、送受信API、受入条件を定義しています。16音／32音の変換、生成、WAV受信、方式選択を実装済みです。実機コード対応表など残りの設計項目は未実装です。

画面設計: [ユーザインターフェース仕様 v1](docs/user-interface-spec.md)。送信画面と受信シミュレータ画面の配置、方式選択、操作状態、結果表示、PC・iPad向けの表示条件を定義しています。

変換の秘匿: [共通鍵による変換秘匿仕様案](docs/keyed-mapping-spec.md)。256ビット親鍵から期間鍵を導出して対応関係を変える自動更新と、共通鍵の即時更新を実装しています。SELCAL音声や通信の暗号化・認証を提供するものではありません。

## 実装仕様

| 項目 | 値 |
|---|---|
| 方式 | 従来16音／SELCAL 32、4文字、2音同時の2組 |
| 信号 | 第1組1.0秒 → 無音0.2秒 → 第2組1.0秒 |
| WAV | 48,000 Hz / 16 bit / mono / 2.2秒 |
| 成分レベル | 2音の振幅は同一。合成ピーク上限は設定値 |
| コード確認 | 使用文字、4文字、重複禁止、各組内の英字→数字の文字順位順 |
| 拡張32音 | 対応。T〜Z、1〜9を追加 |
| RF・PTT制御 | 未実装 |
| 受信 | 別コンテナのWAV受信シミュレータ |
| 実無線受信・自動応答 | 未実装 |

WAV出力レベルはデジタル振幅です。無線機入力の電圧、RF出力、変調度の設定ではありません。ブラウザ音量とOS音量も実際の出力に影響します。

## 受信シミュレータ

`docker compose up --build -d` で送信部と受信シミュレータの2コンテナが起動します。

| 画面 | URL |
|---|---|
| 送信部 | http://localhost:8787 |
| 受信シミュレータ | http://localhost:8788 |

1. 受信画面で受信能力、自機方式、自機番号を設定する（初期値は16音・`5501`）。32音受信能力なら従来16音の自機方式も選択できます。
2. 送信画面に4桁の機番号を入力し、方式を選択して音声を生成しWAVを保存する。
3. 受信画面で保存したWAVを選択し、「受信判定」を押す。
4. 自局一致は通知音と画面表示、他局は検出コードの表示、有効な信号がなければ未検出を表示する。

例: 自機 `5501` に対して送信 `5501` は自局通知、送信 `0001` は他局判定となります。ファイル名や送信コード文字列で受信判定を行わず、PCM音声に含まれる周波数成分を解析します。検出コードから機番号を逆変換し、未割当の920コードは「HACS割当範囲外」と表示します。通知音は受信画面を開いた端末から出ます。音声自体の再生・スピーカーとマイクの接続は不要です。自機番号はブラウザに保存し、受信結果は画面表示のみです。

Pythonでの受信部単独起動:

```bash
python3 receiver_server.py
```

受信API:

```bash
curl --data-binary @HACS-5501.wav -H "Content-Type: audio/wav" "http://localhost:8788/api/decode?own_tail_number=5501"
```

JSONの `status` は `alert`（自局一致）、`other_station`（他局）、`not_detected`（有効な呼び出しなし）です。不正ファイルや不正自局コードはHTTP 400、容量超過は413、解析中の追加要求は409となります。

解析仕様: 8〜96 kHz・16 bit・mono・非圧縮PCM WAV、最大10秒・2 MB。100 ms単位で選択方式の16音／32音をGoertzel法で評価し（32音ではHann窓を使用）、、2音成分、音長、無音間隔、コード規則を確認します。これは静かな試験音声を主対象とする検出器です。雑音を含む無音区間、任意の音声開始位置、フェージング、音声歪みへの対応や、100 msより細かなタイミング精度は未検証です。判定閾値は試作上の設計値であり、実機の受信性能や規格適合を保証しません。ブラウザの音声再生制約により通知音が鳴らない場合も、画面で一致結果を確認できます。

このシミュレータはWAVファイルによる検証用です。実RF受信、マイク連続入力、送信部との自動音声転送は実装していません。

## 実機接続の設計

[汎用音声入力・PTTテンプレート](docs/generic-radio-interface.md)を用意しました。接続プロファイルと差し替え用ドライバ契約、実出力しないドライランを利用できます。

接続対象はメーカーを限定しないHF無線機です。共通のコード変換・信号生成処理と機種別の音声・PTTアダプタを分離する設計とし、機種ごとの接続可否を確認します。実機の接続仕様確定と音声・PTTドライバ実装は引き続き保留中です。

PCのUSB音声出力 → レベル調整・必要な音声絶縁 → HF無線機の指定音声入力 → RF送信 → 相手機器のSELCALデコーダ。

PTTは独立したアダプタとする予定です。将来の送信処理は「排他取得 → PTT ON → 無線機固有の立ち上がり待ち → 音声再生 → 再生完了・末尾待ち → PTT OFF → 結果記録」とします。異常時にPTTを解除し、最大送信時間を設けます。送信完了と相手の呼び出し成功は別々に扱います。

接続仕様の確定には無線機メーカー・型番、入力端子・規定レベル・インピーダンス、PTT方式（接点/CAT/シリアル等）、PCのOSが必要です。HFのRF周波数は無線機が設定します。SELCALの音声周波数とは別の値です。

## 互換性の確認

ソフトウェア試験では全16音の成分振幅、PCM仕様、信号・無音時間、クリッピング上限、無効コードの拒否、HTTP音声生成を確認します。

実機確認では音声インターフェースのクロック誤差、音声フィルタ、利得差、歪み、無線機の立ち上がりを測定し、既存SELCALデコーダで複数のコードを試験します。現時点で実機による試験・RF測定は実施していません。

## Git管理

Gitリポジトリは `main` ブランチで管理します。初回コミットにソース、Docker設定、起動スクリプト、試験、説明書を含みます。生成したWAV、ログ、Pythonキャッシュ、端末固有の設定は除外します。

```bash
git status
git log --oneline
```

更新時は変更を確認してからコミットします。コミット前に利用者の名前とメールアドレスをこのリポジトリに設定してください。

```bash
git config user.name "YOUR NAME"
git config user.email "YOUR EMAIL"
git diff
git add .
git commit -m "Describe the change"
```

リモートリポジトリ: https://github.com/UeEmon/HACS

```bash
git clone https://github.com/UeEmon/HACS.git
cd HACS
docker compose up --build -d
```

更新の取得は `git pull --ff-only`、更新の反映は `git push origin main` を使用します。認証情報はソースに保存しません。

## 参照資料

- ASRI: How SELCAL Works — コード、周波数表、信号順序、時間、文字順序。
  https://asri.aero/selcal/how-selcal-works/
- Sierra Leone Civil Aviation Authority: Part 10C Communication Systems (2024)、SELCAL System / Table 3-1、PDF 174〜175ページ（0基準）。音長1.0±0.25秒、間隔0.2±0.1秒、周波数安定度±0.15%、RF信号の音声歪み15%以下、2音のレベル差3 dB以内。これらは実機を通した測定で検証する。
  https://slcaa.gov.sl/wp-content/uploads/2024/05/PART-10C-COMMUNICATION-SYSTEMS-5-FEB-24.pdf

この試作版は認証済みの航空地上通信装置ではありません。
