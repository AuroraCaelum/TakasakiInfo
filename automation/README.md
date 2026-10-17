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

| 명령 | 하는 일 |
| --- | --- |
| `takasaki build [--out DIR]` | 레거시 파일 생성. 기본 출력 위치는 저장소 루트 |
| `takasaki check` | E8 검사 |
| `takasaki validate [-v]` | DESIGN.md §8 규칙 |
| `takasaki review apply` | 리뷰 항목의 `decision` 적용 → `data/` 갱신, 처리된 항목 삭제, `dbLastUpdate` 갱신 |
| `takasaki stamp` | `data/`를 손으로 고친 뒤 `dbLastUpdate` 갱신 |
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
| `done` | 전부 | `data/`를 직접 고친 뒤 항목을 닫는다 |

캐릭터의 표기 변형으로 들어온 가창자(예: `渡辺 曜`)는 classify가 아니라 merge 항목에서 캐릭터로 병합한다(`merge:character:aqours/you-watanabe`).

## 진행 상황

- **Phase 0 (기반)**: 완료. 모델, YAML 저장소, 레거시 빌더, 검증기, CLI, PR CI(`.github/workflows/ci.yml`)
- **Phase 1 (이관)**: M1~M7 완료. 기존 데이터를 무손실로 옮겼고, 출력이 바뀐 곳은 이미 승인된 변경뿐이다(`migration/REPORT.md`, 이후 리뷰로 바뀐 것은 DESIGN.md §10.1 6~9).
  - 완료: merge 리뷰 18건, 부록 A-1 1~12, `NA` 엔티티 정리 (2026-10-17, 결정 D25~D27)
  - 남은 것
    - 리뷰 37건 결정: classify 28, latin-ko 2, legacy-row 3, setlist 4
    - 부록 A-1 13 (ko 장음의 `established` 근거 확인), 부록 A-2 링크 점검
    - W14: 크레딧이 빈 보컬 음원 6건. Aqours `聖良と理亞を…` 3건은 드라마인데 곡으로 분류돼 있고, 2021년 REMIX 3건은 크레딧이 비어 있다(legacy-row 리뷰와 같은 발매물)
    - Note 열 자유 텍스트의 구조화(M3 일부)
- **배포 파이프라인 (§10.4)**: 완료. AWS에 배포했고, `main` 병합 후 `deploy` 워크플로가 업로드 → 공개 → 무효화 → 스모크 테스트까지 통과했다(2026-10-17).
  - 인프라: `../infra/` (CDK 스택 3개). 배포·운영 방법은 [../infra/README.md](../infra/README.md)
  - 데이터 배포: `.github/workflows/deploy.yml` + `takasaki deploy`. `main`에 push되면 자동으로 실행된다
  - 배포 역할(OIDC)은 `main` 브랜치만 위임받을 수 있다. 다른 브랜치에서 워크플로를 수동 실행하면 AWS 인증 단계에서 실패한다
  - API는 아직 `/api/v1/health`만 있다. 질의 엔드포인트는 Phase 6(§10.6)
