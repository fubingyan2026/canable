以下は提供された英文の日本語訳です。

---

# candleLight_gsusb、Canable V2（STM32F431ベース）CAN-FD用に調整したバージョン

***注意: このプロジェクトが継続的に保守される見込みは低いです***

自由にフォークして発展させてください。

ここでの多くの変更は以下をベースにしています:

[https://github.com/ddleed/CANNEDPI_SW_GSUSB_CANFD](https://github.com/ddleed/CANNEDPI_SW_GSUSB_CANFD) （Ryan Edwards）
[https://github.com/normaldotcom/candleLight_fw](https://github.com/normaldotcom/candleLight_fw) （multitarget ブランチ, Ethan Zonca）

不具合をいくつか追加してしまったと思います。現状、CAN FD を 2M, 5Mbps で動作させた基本的な双方向テストのみ行っています。

これは一部の STM32G431 ベースの USB-CAN アダプタ（特に以下）向けのファームウェアです:

* canable v2: [http://canable.io/](http://canable.io/) （STM32G431x8）
* CANable-MKS V2.0: [https://github.com/makerbase-mks/CANable-MKS](https://github.com/makerbase-mks/CANable-MKS) （STM32G431x8）

このフォークは現在 STM32G431 ベースのアダプタでのみ動作します。他の G4 系や H7 系でも FDCAN ペリフェラルが必要ですが、おそらく比較的簡単に対応できると思われます。

これは mainline Linux の gs_usb カーネルモジュールのインターフェースを実装しており、Ubuntu などこのモジュールを同梱する Linux ディストリビューションでそのまま動作します。

## 既知の問題

linux<4.5 の gs_usb モジュールには、デバイス取り外し時にカーネルがクラッシュする可能性があるバグがあります。

以下は、古いカーネルでも動作する修正版です:
[https://github.com/HubertD/socketcan_gs_usb](https://github.com/HubertD/socketcan_gs_usb)

このファームウェアは WCID USB ディスクリプタも実装しているため、最近の Windows バージョンではドライバのインストールなしで使用できます。

## ビルド

ビルドには arm-none-eabi-gcc ツールチェーンが必要です。

```shell
sudo apt-get install gcc-arm-none-eabi

mkdir build
cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=../cmake/gcc-arm-none-eabi-8-2019-q3-update.cmake

# または
# cmake-gui ..
# 設定前に cmake toolchain file を指定することを忘れないでください。
#
# すべてのターゲットをコンパイル:

make

# または、各ボードターゲットは cmake オプションで無効化可能
# または、単一ターゲットをビルド（例）
make canable2_fw

#
# ターゲット一覧:
make help
```

## フラッシュ

Linux で candleLight をフラッシュする方法（出典: [https://cantact.io/cantact/users-guide.html）](https://cantact.io/cantact/users-guide.html）)

* フラッシュには dfu-util が必要です。Ubuntu では `sudo apt install dfu-util` でインストール可能。
* 上記の手順でコンパイルするか、現在のバイナリリリース gsusb_cantact_8b2b2b4.bin をダウンロード。
* Linux で dfu-util がパーミッションエラーになる場合、追加の udev ルールが必要なことがあります。ディストリビューションのドキュメントを参照し、このリポジトリの `70-candle-usb.rules` も確認してください。

### 推奨される簡単な方法

* cmake でビルドした場合、`make flash-<targetname_fw>` を使用（例: `make flash-canable_fw`）。dfu-util が自動実行されます。

### 特定のシリアル番号を持つデバイスをリフラッシュする方法

* 複数のデバイスが接続されている場合、dfu-util がどれをフラッシュするか判断できないことがあります。
* `dfu-util -l` で対象デバイスのシリアル番号を確認。
* 以下のコマンドを適宜修正して使用:
  `dfu-util -D CORRECT_FIRMWARE.bin -S "serial_number_here" -a 0 -s 0x08000000:leave`
* `:leave` は古い dfu-util では使用できませんが、便利な再起動機能です。

### フェイルセーフ方法（または未フラッシュのデバイスの場合）

* USB を外し、CANtact 基板の BOOT ピンをショートして USB を再接続。デバイスは "STM32 BOOTLOADER" として認識されます。

* 以下を実行:
  `sudo dfu-util --dfuse-address -d 0483:df11 -c 1 -i 0 -a 0 -s 0x08000000 -D CORRECT_FIRMWARE.bin`

* USB を外し、BOOT ピンを戻して再接続。

## 永続的なデバイス名の割り当て

Linux の udev を使うと、特定のシリアル番号のデバイスに名前を割り当てることができます（udev および systemd.link の manpage を参照）。複数デバイス使用時に便利です。

例：

```
$ cat /etc/systemd/network/60-persistent-candev.link
[Match]
Property=ID_MODEL=cannette_gs_usb ID_SERIAL_SHORT="003800254250431420363230"

[Link]
# systemd.link manpage より:
# カーネルが使用する可能性のある名前（例: "eth0"）を指定するのは危険。
# udev とカーネルが競合し、どちらが勝つか予測不能。

Name=cannette99
```

（シリアル番号は `lsusb` で確認できます）。systemd の設定をリロードし、ボードをリセット後:

```
$ ip a
...
59: cannette99: <NOARP,ECHO> mtu 16 qdisc noop state DOWN group default qlen 10
    link/can
$
```

## Hacking

### Pull Request の提出

* 各コミットには無関係な変更を含めない（例: 機能変更と空白変更を分ける）。
* プロジェクトは各コミットで（デフォルト設定で）コンパイル可能かつ機能する状態であること。
* "WIP" などの作業途中コミットは squash する。
* エディタが空白や改行コードを壊さないよう注意。
* `.editorconfig` と `uncrustify.cfg` を同梱しているので整形に利用可能。

uncrustify を実行する典型的な例（HAL とサードパーティ除外）:
`uncrustify -c ./uncrustify.cfg --replace $(find include src -name "*.[ch]")`

`.orig` ファイルを作りたくない場合は `--no-backup` を追加。

### プロファイリング

Cortex-M0（F042, F072 など）は ITM/SWO がないため適していませんが、プログラムカウンタのランダムサンプリングで粗いプロファイルは可能です。

例として openocd の `profile` コマンド（[https://openocd.org/doc/html/General-Commands.html#Misc-Commands）を使用](https://openocd.org/doc/html/General-Commands.html#Misc-Commands）を使用):

`profile 5 test.out 0x8000000 0x8100000`

（gdb 内では `monitor` を前につける: `monitor profile 5 ...`）

生成された .out ファイルは `gprof <firmware_name> -l test.out` で解析可能です。

## 関連プロジェクト

* Cangaroo: [https://github.com/HubertD/cangaroo](https://github.com/HubertD/cangaroo) （オープンソース CAN バス解析ソフト）
* Candle.NET: [https://github.com/elliotwoods/Candle.NET](https://github.com/elliotwoods/Candle.NET) （candle API の .NET ラッパー）
