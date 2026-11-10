# PILO

**AI コーディングのための、ローカルなプロジェクト情報・根拠の保存・復旧ツールです。**

[English](README.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

PILO は、AI コーディングツールがプロジェクトの情報を検索し、実際に参照した内容を記録するための Python アプリです。プロジェクト単位の権限、不変のコンテキスト Snapshot、任意のローカル分析を提供します。

**現在の状態:** 0.3.1 公開前の試験版です。ローカルの自動テストは実施済みですが、すべての環境の安定性や検索精度を保証するものではありません。GitHub 上の公開 CI はまだ実行していません。

## できること

- 許可された UTF-8 ファイルを索引化し、キーワードで検索します。
- 参照した内容と出典ハッシュを Snapshot として保存し、読み取り時に権限を再確認します。
- ローカル STDIO の MCP クライアントに接続します。
- 任意で Ollama の意味検索・AI 分析や Graphify の Python 構造分析を利用できます。
- 承認済みのコード処理や、変更のない Git 作業ツリーを前提とした Checkpoint・復旧を運用者 API で利用できます。既定の MCP 接続では、プロジェクトを変更する操作は許可しません。

例えば、リポジトリを索引化して checkpoint に関する情報を検索し、後から同じ Snapshot を読み、当時の根拠を確認できます。

## クイックスタート

Python 3.11 以上、Git、JSON 関数と FTS5 trigram を備えた SQLite 3.37 以上が必要です。対象は macOS と Linux です。ローカル検証は macOS で実施し、Linux CI は準備済みですが未実行です。現在 Windows はサポートしていません。

展開したソースのディレクトリで実行します。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/pilo init --directory .pilo
.venv/bin/pilo --config .pilo/database_config.json add-project --key sample --name Sample --root examples/sample-project
.venv/bin/pilo --config .pilo/database_config.json search --project sample --query checkpoint
```

最後のコマンドは内容、Snapshot ID、出典パス、完了状態を返します。結果がない場合や予算により一部だけを含む場合は、その状態を明示します。初期化は既存の環境を上書きしません。

自分のプロジェクトを登録するには、`add-project` のパスとキーを変更してください。このコマンドはローカル運用者による明示的な登録・索引化です。専用の読み取りアカウントを設定し、一時的な索引化アカウントは終了後に無効化します。

## コーディングツールへの接続

実行ファイルの絶対パスで `pilo --config /absolute/path/to/.pilo/database_config.json serve` を起動するローカル STDIO MCP を設定します。既定で提供するのはプロジェクト一覧・詳細・検索・Snapshot 読み取りです。設定例は英語の [MCP 仕様](docs/mcp.md)を参照してください。クラウドクライアントからローカルプロセスへ接続できるとは限りません。

## 任意の機能と制限

- **意味検索:** Ollama の埋め込みと cosine 順位を使用します。検索対象は最大 512 単位で、呼び出し時に計算します。
- **AI 分析:** 保存済み Snapshot をローカルモデルで分析します。構造と出典を検査しても、回答の事実確認は別途必要です。
- **関係分析:** Graphify による Python 構造分析です。最大 100 ファイル、ソース 2 MB が対象です。
- **復旧:** 変更のない Git 状態が前提で、Git オブジェクトと保存済みコンテンツが必要です。

基本のインストールにはモデル、クラウドアカウント、API キー、Graphify は不要です。追加設定は英語の [拡張ガイド](docs/extensions.md)を参照してください。

## 文書とライセンス

正式な仕様書は **英語のみ**で管理します。日本語・韓国語 README は紹介と利用案内です。[仕様](docs/specification.md)、[ロードマップ](docs/roadmap.md)、[検証範囲](docs/verification.md)を参照してください。

PILO 自体のコードと文書は [MIT](LICENSE) です。依存ソフトウェアにはそれぞれのライセンスが適用されます。Graphify の Apache-2.0 などは [第三者ライセンスの告知](THIRD_PARTY_NOTICES.md)に記載しています。モデルの重み、個人データ、非公開の会話原文は配布しません。
