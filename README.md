<b><h2>TakasakiInfo -<br>CSV & JSON Database of Love Live Song List, Song URLs, Member List, Seiyuu List.</h2></b>
<br>
<b>IMPORTANT: Data is still being configured.</b>
<br><br>
README Language &nbsp;&nbsp;&nbsp;||&nbsp;&nbsp;&nbsp; <a href="#korean" >한국어</a> &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; <a href="#japanese" >日本語</a> &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; <a href="#english" >English</a>
<br></br>

<h2>Database Status (Final Update Date, Quick Links)</h2>

|         | Songs           | Albums  | Members |
| :--------: | :-------------: | :-----:| :---: |
|    μ’s     | Planned | Planned | (<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/members/Muse.csv">CSV</a>) |
|   Aqours   | In Progress | Planned | (<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/members/Aqours.csv">CSV</a>) |
|  Nijigaku  | <b>[Final Update 2023/04/09]</b><br>(<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/songs/Nijigaku/Nijigaku.csv">CSV</a> / <a href="https://github.com/AuroraCaelum/TakasakiInfo/tree/main/songs/Nijigaku">JSON</a>) | In Progress | (<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/members/Nijigaku.csv">CSV</a>) |
|   Liella!  | <b>[Final Update 2023/04/09]</b><br>(<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/songs/Liella/Liella.csv">CSV</a> / <a href="https://github.com/AuroraCaelum/TakasakiInfo/tree/main/songs/Liella">JSON</a>) | <b>[Final Update 2023/04/09]</b><br>(<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/albums/Liella/Liella.csv">CSV</a> / <a href="https://github.com/AuroraCaelum/TakasakiInfo/tree/main/albums/Liella">JSON</a>) | (<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/members/Liella.csv">CSV</a>) |
| Hasunosora | <b>[Final Update 2023/04/09]</b><br>(<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/songs/Hasunosora/Hasunosora.csv">CSV</a> / <a href="https://github.com/AuroraCaelum/TakasakiInfo/tree/main/songs/Hasunosora">JSON</a>) | <b>[Final Update 2023/04/09]</b><br>(<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/albums/Hasunosora/Hasunosora.csv">CSV</a> / <a href="https://github.com/AuroraCaelum/TakasakiInfo/tree/main/albums/Hasunosora">JSON</a>) | (<a href="https://github.com/AuroraCaelum/TakasakiInfo/blob/main/members/Hasunosora.csv">CSV</a>) |
| Musical |  |  |  |
<br>

***

<div id="english"></div>

# About

- Multilanguage Database of the terms related to Love Live Series.
- It provides Japanese/Romanization/Korean translation of the song title, and the release date and YouTube link of each song.
  - However, the YouTube link is only available for songs that have been officially released as streaming. For songs without streaming, it is filled with ```NA```.

## Before Starting
- All data is based on the information on the official site or official music streaming service.
- If the official name is English, no Korean translation is included.
- <b>For the reasons of the data is still being configured, missing data may exist and the structure of the data may change in the future.</b>
- The name of each file is the English name of the group, as follows.
  - μ’s - ```Muse```
  - Aqours - ```Aqours```
  - Nijigasaki High School Idol Club - ```Nijigaku```
  - Liella! - ```Liella```
  - Hasunosora Girls' High School Idol Club - ```Hasunosora```
  - School Idol Musical - ```Musical```

## CSV Structure
- The first row of each file contains a header.
- Each data is provided as a CSV separated by ```,```
- If a column contains multiple data, it is divided by ```;```
<br>

- The columns for each ```song data``` are as follows.

  | 0 | 1 | 2 | 3 | 4 | 5 |
  |:---:|:---:|:---:|:---:|:---:|:---:|
  | Title (ja) | Title (rom) | Title (ko) | Singer (ja) | Singer (rom) | Singer (ko) |
  | <b>6</b> | <b>7</b> | <b>8</b> | <b>9</b> | <b>10</b> | <b>11</b> |
  | Lyricist (ja) | Lyricist (rom) | Lyricist (ko) | Composer (ja) | Composer (rom) | Composer (ko) |
  | <b>12</b> | <b>13</b> | <b>14</b> | <b>15</b> | <b>16</b> | <b>17</b> |
  | Arranger (ja) | Arranger (rom) | Arranger (ko) | Album | Release Date | YT Link |
  | <b>18</b> |
  | Notes |
  
- The columns for each ```album data``` are as follows.

  | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
  |:---:|:---:|:---:|:---:|:---:|:---:|:---:|
  | Album | Track Number | Title (ja) | Title (rom) | Title (ko) | Singer (ja) | Singer (rom) |
  | <b>7</b> | <b>8</b> | <b>9</b> | <b>10</b> | <b>11</b> | <b>12</b> | <b>13</b> |
  | Singer (ko) | Lyricist (ja) | Lyricist (rom) | Lyricist (ko) | Composer (ja) | Composer (rom) | Composer (ko) |
  | <b>14</b> | <b>15</b> | <b>16</b> | <b>17</b> | <b>18</b> | <b>19</b> |
  | Arranger (ja) | Arranger (rom) | Arranger (ko) | Release Date | YT Link | Notes |
  
<!--
  <details>
    <summary>Song Data Columns</summary>
      <table><thead><tr><th>0</th><th>1</th><th>2</th><th>3</th><th>4</th><th>5</th></tr></thead><tbody><tr><td>Title (ja)</td><td>Title (rom)</td><td>Title (ko)</td><td>Singer (ja)</td><td>Singer (rom)</td><td>Singer (ko)</td></tr><tr><th>6</th><th>7</th><th>8</th><th>9</th><th>10</th><th>11</th></tr><tr><td>Lyricist (ja)</td><td>Lyricist (rom)</td><td>Lyricist (ko)<br></td><td>Composer (ja)</td><td>Composer (rom)</td><td>Composer (ko)</td></tr><tr><th>12</th><th>13</th><th>14</th><th colspan="3">15</th></tr><tr><td>Arranger (ja)</td><td>Arranger (rom)</td><td>Arranger (ko)</td><td colspan="3">Album</td></tr><tr><td colspan="2"><b>16</b></td><td colspan="2"><b>17</b></td><td colspan="2"><b>18</b></td></tr><tr><td colspan="2">Release Date</td><td colspan="2">YT Link</td><td colspan="2">Note</td></tr></tbody></table>
  </details>
-->
  
- The columns for each ```member data``` are as follows.
  | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
  |:---:|:---:|:---:|:---:|:---:|:---:|:---:|
  | Name(Japanese) | Name(Romaji) | Name(Korean) | Seiyuu(Japanese) | Seiyuu(Romaji) | Seiyuu(Korean) | Unit |
<br>

- The order of each row is as follows.
  - Song: Release Date Priority
  - Voice actors and members: Based on the order of members on the official website
<br>

## JSON Structure
### Songs
`Example: Singlelanguage JSON (Hasunosora-ja.json)`
```js
[
  {
    "title": "ド！ド！ド！",
    "artist": "みらくらぱーく！",
    "lyricist": "ろさ",
    "composer": "山本玲史",
    "arranger": "山本玲史",
    "release": "2023-03-29",
    "link": "https://youtu.be/5TXxIDBRPEI",
    "note": ""
  }
]
```
`Example: Multilanguage JSON (Nijigaku.json)`
```js
[
  {
    "title": {
      "ja": "ヤダ！",
      "rom": "Yada!",
      "ko": "싫어!"
    },
    "artist": {
      "ja": "優木せつ菜",
      "rom": "Setsuna Yuki",
      "ko": "유키 세츠나"
    },
    "lyricist": {
      "ja": "Akira Sunset",
      "rom": "Akira Sunset",
      "ko": "Akira Sunset"
    },
    "composer": [
      {
        "ja": "Akira Sunset",
        "rom": "Akira Sunset",
        "ko": "Akira Sunset"
      },
      {
        "ja": "菊地博人",
        "rom": "Hiroto Kikuchi",
        "ko": "키쿠치 히로토"
      }
    ],
    "arranger": {
      "ja": "菊地博人",
      "rom": "Hiroto Kikuchi",
      "ko": "키쿠치 히로토"
    },
    "release": "2021-10-13",
    "link": "https://youtu.be/1lPESUmrbZY",
    "note": ""
  },
  // Continues
]
```
### Albums
`Example: Singlelanguage JSON (Liella-ko.json)`
```js
[
  {
    "album": "Welcome to 僕らのセカイ / Go!! リスタート 【第1話盤】",
    "release": "2022-08-17",
    "songs": [
      {
        "track": "1",
        "title": "Welcome to 우리들의 세계",
        "artist": "Liella!",
        "lyricist": "미야지마 준코",
        "composer": "미츠마스 하지메",
        "arranger": [
          "EFFY",
          "모리 유야"
        ],
        "link": "https://youtu.be/oDnmWbGsNxA",
        "note": ""
      },
      // Track Continues
    ]
  },
  // Album Continues
]
```
`Example: Multilangauge JSON (Liella.json)`
```js
[
  {
    "album": "始まりは君の空 [みんなで叶える物語盤]",
    "release": "2021-04-07",
    "songs": [
      {
        "track": "1",
        "title": {
          "ja": "始まりは君の空",
          "rom": "Hajimari wa Kimi no Sora",
          "ko": "시작은 너의 하늘"
        },
        "artist": {
          "ja": "Liella!",
          "rom": "Liella!",
          "ko": "Liella!"
        },
        "lyricist": {
          "ja": "畑 亜貴",
          "rom": "Aki Hata",
          "ko": "하타 아키"
        },
        "composer": {
          "ja": "兼松 衆",
          "rom": "Shu Kanematsu",
          "ko": "카네마츠 슈"
        },
        "arranger": {
          "ja": "兼松 衆",
          "rom": "Shu Kanematsu",
          "ko": "카네마츠 슈"
        },
        "link": "https://youtu.be/bjIRLovzc80",
        "note": ""
      },
      // Track Continues
    ]
  },
  // Album Continues
]
```

## Feedback
- Feedback on the data structure or suggestions for missing information will be reflected if you send them through the [Issue](https://github.com/AuroraCaelum/LoveLiveTerm-MultiLang/issues).


***

<div id="korean"></div>

# 이 DB는
- 러브라이브 시리즈 노래와 멤버에 대한 DB입니다.
- 노래의 일본어 표기 / 로마자 표기 / 한국어 번역, 그리고 각 곡의 발매일과 유튜브 링크를 제공합니다.
  - 단, 유튜브 링크는 정식으로 스트리밍으로 발매된 곡에 한하여 제공됩니다. 스트리밍이 없는 곡의 경우, ```NA```로 대체됩니다.

## 시작하기에 앞서
- 모든 데이터는 공식 사이트나 공식 음원의 정보를 최우선으로 합니다.
- 공식 명칭이 영어인 경우, 그에 대한 한국어 번역은 포함하지 않습니다.
- <b>아직 데이터를 구성하는 중이므로, 누락된 데이터가 존재할 수 있으며, 차후 데이터의 구조가 변경될 수 있습니다.</b>

## CSV 구조
- 각 파일의 첫번째 행에는 헤더가 포함되어 있습니다.
- 각 데이터는 ```,```로 구분되는 CSV로 제공됩니다.
- 하나의 열에 여러 개의 데이터가 들어있을 경우, ```;```로 구분됩니다.
<br>

- 각 ```노래 데이터```의 열은 다음과 같습니다.
  - ```제목(일본어)```, ```제목(로마자)```, ```제목(한국어)```, ```가수(일본어)```, ```가수(로마자)```, ```가수(한국어)```, ```작사가(일본어)```, ```작사가(로마자)```, ```작사가(한국어)```, ```작곡가(일본어)```, ```작곡가(로마자)```, ```작곡가(한국어)```, ```편곡자(일본어)```, ```편곡자(로마자)```, ```편곡자(한국어)```, ```수록 앨범명```, ```발매일```, ```유튜브 링크```, ```비고```
- 각 ```멤버 데이터```의 열은 다음과 같습니다.
  - ```이름(일본어)```, ```이름(로마자)```, ```이름(한국어)```, ```성우(일본어)```, ```성우(로마자)```, ```성우(한국어)```, ```소속 유닛```
<br>

- 각 행의 순서는 다음과 같습니다.
  - 곡: 발매일 우선순
  - 성우 및 멤버: 공식 홈페이지 멤버 순서 기준
<br>

- 각 파일의 이름은 해당 그룹의 영문명칭이며, 다음과 같습니다.
  - μ’s - ```Muse```
  - Aqours - ```Aqours```
  - 니지가사키 학원 스쿨 아이돌 동호회 - ```Nijigaku```
  - Liella! - ```Liella```
  - 하스노소라 여학원 스쿨 아이돌 클럽 - ```Hasunosora```
  - 스쿨 아이돌 뮤지컬 - ```Musical```

## 피드백
- 데이터 구조에 대한 피드백이나, 정보 누락에 대한 제안은 [이슈](https://github.com/AuroraCaelum/LoveLiveTerm-MultiLang/issues)를 통해 보내주시면 반영하도록 하겠습니다.


***

<div id="japanese"></div>

# このDBは
- ラブライブシリーズの曲とメンバーに関するDBです。
- 曲の日本語表記 / ローマ字表記 / 韓国語訳、そして各曲の発売日とユーチューブリンクを提供します。
  - ただし、YouTubeリンクは正式にストリーミングで発売された曲に限り提供されます。ストリーミングがない曲の場合、```NA```で満たされます。

## 始める前に
- すべてのデータは、公式サイトや公式音源の情報を最優先にします。
- 公式名称が英語の場合、それに対する韓国語訳は含みません。
- <b>まだデータを構成しているため、欠落したデータが存在する可能性があり、その後データの構造が変更される可能性があります。</b>

## CSV ストラクチャー
- 各ファイルの最初の行にはヘッダーが含まれています。
- 各データは```,```に区分されるCSVで提供されます。
- 1つの列に複数のデータが含まれている場合は、```;```に区分されます。
<br>

- 各```曲データ```の列は次のとおりです。
  - ```タイトル(日本語)```, ```タイトル(ローマ字)```, ```タイトル(韓国語)```, ```歌手(日本語)```, ```歌手(ローマ字)```, ```歌手(韓国語)```, ```作詞(日本語)```, ```作詞(ローマ字)```, ```作詞(韓国語)```, ```作曲(日本語)```, ```作曲(ローマ字)```, ```作曲(韓国語)```, ```編曲(日本語)```, ```編曲(ローマ字)```, ```編曲(韓国語)```, ```アルバム名```, ```発売日```, ```YouTubeリンク```, ```備考```
- 各```メンバーデータ```の列は次のとおりです。
  - ```名前(日本語)```, ```名前(ローマ字)```, ```名前(韓国語)```, ```声優(日本語)```, ```声優(ローマ字)```, ```声優(韓国語)```, ```所属ユニット```
<br>

- 各行の手順は次のとおりです。
  - 曲: 発売日優先順
  - 声優・メンバー:　公式ホームページメンバー順基準
<br>

- 各ファイルの名前は、そのグループの英語名称であり、次のとおりです。
  - μ’s - ```Muse```
  - Aqours - ```Aqours```
  - 虹ヶ咲学園スクールアイドル同好会 - ```Nijigaku```
  - Liella! - ```Liella```
  - 蓮ノ空女学院スクールアイドルクラブ - ```Hasunosora```
  - スクールアイドルミュージカル - ```Musical```

## フィードバック
- データ構造に対するフィードバックや情報漏れの提案は、[イシュー](https://github.com/AuroraCaelum/LoveLiveTerm-MultiLang/issues)を通じて送っていただければ反映するようにします。
