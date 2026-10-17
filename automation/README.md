# automation

TakasakiInfo 데이터 파이프라인. 설계는 [docs/DESIGN.md](docs/DESIGN.md).

## 구조

| 위치 | 내용 |
| --- | --- |
| `../data/` | **단일 원천.** 엔티티별 YAML (persons, characters, artists, works, releases, concerts …) |
| `../data/legacy/layout.yaml` | 레거시 파일의 배치 순서 (어느 그룹 파일의 몇 번째에 어떤 앨범이 오는지) |
| `../data/meta.yaml` | `dbLastUpdate`, 스키마 버전 |
| `../albums/` `../songs/` `../members/` `../concerts/` `../TakasakiInfo.json` | **생성물(레거시).** 직접 수정하지 않는다. CI가 막는다(E8) |
| `src/takasaki/` | 모델, 빌더, 검증기, 이관기, 리뷰 처리 |
| `review/` | 사람이 판단할 리뷰 항목 |
| `migration/REPORT.md` | 레거시 → 정규화 이관 보고서 (이관 전 레거시 파일과 달라진 모든 셀) |

## 설치와 실행

[uv](https://docs.astral.sh/uv/)가 필요하다.

```sh
cd automation
uv sync
uv run takasaki validate      # 검증 규칙 (오류가 있으면 종료 코드 1)
uv run takasaki build         # data/ → 레거시 파일 재생성
uv run takasaki check         # 커밋된 레거시 파일이 빌드 결과와 같은지 (E8)
uv run pytest -q
```

YouTube Music 어댑터(`takasaki ytm …`)는 추가 의존성과 로그인 세션이 필요하다. 로그인하지 않으면 Lantis 앨범이 재생 불가로 나와 videoId를 받지 못한다.

```sh
uv sync --group sync
uvx --with ytmusicapi ytmusicapi browser   # 안내대로 요청 헤더를 붙여 넣으면 browser.json이 생긴다 (automation/에 두거나 TAKASAKI_YTM_AUTH로 지정, git 제외)
```

| 명령 | 하는 일 |
| --- | --- |
| `takasaki build [--out DIR]` | 레거시 파일 생성. 기본 출력 위치는 저장소 루트 |
| `takasaki check` | E8 검사 |
| `takasaki validate [-v]` | DESIGN.md §8 규칙 |
| `takasaki review apply` | 리뷰 항목의 `decision` 적용 → `data/` 갱신, 처리된 항목 삭제, `dbLastUpdate` 갱신 |
| `takasaki stamp` | `data/`를 손으로 고친 뒤 `dbLastUpdate` 갱신 |
| `takasaki ytm match [--release ID …] [--project P] [--apply]` | YouTube Music 어댑터(§7.2). 발매물·에디션마다 앨범을 찾아 트랙을 순서·제목으로 맞추고 자기 videoId를 채운다. 후보가 하나뿐이고 모든 트랙이 맞을 때만 반영하고, 죽은 값은 교체·살아 있는 값은 유지한다(`ytm-change` 리뷰). 애매하면 `ytm-album` 리뷰 항목을 남긴다. `--apply` 없이는 미리보기 |
| `takasaki ytm links [--json PATH]` | W7: 저장된 videoId가 지금도 재생되는지 확인 |
| `takasaki migrate [--force]` | 레거시 → `data/` 1회성 이관 (이미 완료. 다시 돌리면 `data/`를 덮어씀) |
| `takasaki deploy --bucket … --distribution … --base-url … --sha … [--promote]` | 릴리스를 S3 `releases/<sha>/`에 업로드. `--promote`면 공개 경로 반영 → CloudFront 무효화 → 스모크 테스트, 실패 시 직전 릴리스로 롤백 (§10.4). 보통은 `deploy` 워크플로가 실행한다. `uv sync --group deploy` 필요 |

## 데이터를 고치는 흐름

1. `data/`의 YAML을 고친다 (또는 리뷰 항목에 결정을 적고 `takasaki review apply`).
2. 손으로 고쳤다면 `takasaki stamp`.
3. `takasaki build` → `takasaki validate` → `takasaki check`.
4. `data/`와 생성물을 같은 커밋에 넣는다.

## 리뷰 항목

`review/*.yaml`의 `decision`에 적는다. 결정이 빈 항목은 그대로 남는다.

| decision | 대상 | 효과 |
| --- | --- | --- |
| `merge:<종류>:<id>` | merge | 항목의 모든 `ref`를 그 엔티티로 병합. 참조를 고쳐 쓰고, 다른 표기는 alias로 남기고, 병합된 엔티티는 삭제. 예: `merge:person:hiroto-kikuchi`. 작중 크레딧(D27)이면 person을 character로도 병합할 수 있다 |
| `distinct` | merge | 서로 다른 대상으로 기록(`distinct_from`). 이후 경고가 사라진다 |
| `kind:<종류>` | classify | 아티스트 종류 지정: `group` `unit` `solo` `cross_unit` `collab` `special` |
| `rule` | latin-ko | 라틴 원어 이름의 ko를 원문으로 (§5.4) |
| `keep:official` / `keep:established` | latin-ko | 지금 ko를 승인된 예외로 유지. `decision_note:`에 근거를 적는다 |
| `pick:<n>` / `pick:<edition>=<n>,…` / `none` | ytm-album | 후보 앨범을 고른다. 항목에 트랙 대응이 저장돼 있어 네트워크 없이 반영된다. 고르지 않은 에디션은 자기 URL 없음 |
| `done` | 전부 | `data/`를 직접 고친 뒤 항목을 닫는다 |

캐릭터의 표기 변형으로 들어온 가창자(예: `渡辺 曜`)는 classify가 아니라 merge 항목에서 캐릭터로 병합한다(`merge:character:aqours/you-watanabe`).

## 진행 상황

- **Phase 0 (기반)**: 완료. 모델, YAML 저장소, 레거시 빌더, 검증기, CLI, PR CI(`.github/workflows/ci.yml`)
- **Phase 1 (이관)**: 완료 (2026-10-17). M1~M8, 이관 리뷰 66건, 부록 A-1·A-2. 출력이 바뀐 곳은 승인된 변경뿐이다(`migration/REPORT.md`, 이후 리뷰로 바뀐 것은 DESIGN.md §10.1 6~15). 결정 D25~D33
  - Phase 3으로 넘긴 것: 공연 곡별 가창자(M6의 Fandom 보강)
  - 남은 문제: 기존 YouTube Music videoId 644개 중 611개(95%)가 "Video unavailable"이다(2026-10-17, 로그인 세션으로 확인). 살아 있는 것은 2023년 하반기 하스노소라·니지가사키 발매물 5개뿐이다. 이번에 다룬 발매물 6개는 현재 videoId로 바꿨고, 나머지는 YouTube Music 어댑터(Phase 2)로 다시 채운다
  - 로그인 세션: `automation/browser.json`(ytmusicapi 브라우저 인증, git에서 제외)
- **배포 파이프라인 (§10.4)**: 완료. AWS에 배포했고, `main` 병합 후 `deploy` 워크플로가 업로드 → 공개 → 무효화 → 스모크 테스트까지 통과했다(2026-10-17).
  - 인프라: `../infra/` (CDK 스택 3개). 배포·운영 방법은 [../infra/README.md](../infra/README.md)
  - 데이터 배포: `.github/workflows/deploy.yml` + `takasaki deploy`. `main`에 push되면 자동으로 실행된다
  - 배포 역할(OIDC)은 `main` 브랜치만 위임받을 수 있다. 다른 브랜치에서 워크플로를 수동 실행하면 AWS 인증 단계에서 실패한다
  - API는 아직 `/api/v1/health`만 있다. 질의 엔드포인트는 Phase 6(§10.6)
