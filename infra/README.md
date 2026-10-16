# infra

TakasakiInfo 인프라 (AWS CDK, Python). 설계는 [../automation/docs/DESIGN.md](../automation/docs/DESIGN.md) §10.4.

## 구성

```
사용자 → CloudFront (Flat-rate Free 플랜, WAF)
           ├─ /          → S3 site/   (연결 맵 사이트, 지금은 안내 페이지)
           ├─ /data/*    → S3 data/   (v1 파일, version.json …)
           └─ /api/*     → Lambda Function URL (AuthType AWS_IAM)
S3와 Function URL은 OAC로 CloudFront 경유 요청만 받는다.
```

| 스택 | 리전 | 내용 |
| --- | --- | --- |
| `TakasakiInfo-Waf` | us-east-1 | WAF 웹 ACL (CloudFront용 WAF는 us-east-1에만 만들 수 있음). 규칙 4개 |
| `TakasakiInfo-App` | ap-northeast-2 | S3 버킷, API Lambda + Function URL, CloudFront 배포, GitHub 배포 역할, 예산 알림 |
| `TakasakiInfo-Plan` | us-east-1 | CloudFront Flat-rate **Free** 플랜 가입 (가입 API가 us-east-1에만 있음) |

세 스택은 CDK의 리전 간 참조로 연결된다. 배포 순서는 Waf → App → Plan이고, CDK가 알아서 지킨다.

## 처음 배포하기

### 0. 준비물

- AWS CLI v2 (`aws --version`)
- Node.js 22 또는 24 LTS. 다른 버전이면 CDK가 경고를 내는데, `export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1`로 끌 수 있다
- [uv](https://docs.astral.sh/uv/)

### 1. 로컬 관리자 자격 증명

인프라 배포는 관리자 권한이 필요하다. GitHub Actions에는 이 권한을 주지 않고, 사람이 로컬에서 한다. 루트 계정의 액세스 키는 쓰지 않는다.

- **IAM Identity Center를 쓰고 있다면**: `aws configure sso --profile takasakiinfo`
- **아니라면**
  1. IAM 콘솔 → 사용자 생성 (예: `takasakiinfo-admin`)
  2. 권한: `AdministratorAccess`
  3. 보안 자격 증명 탭 → 액세스 키 만들기 → "CLI"
  4. `aws configure --profile takasakiinfo`에 키를 넣고, 기본 리전은 `ap-northeast-2`
  5. 배포가 끝나면 키를 비활성화한다. 인프라를 바꿀 때만 다시 켠다

```sh
export AWS_PROFILE=takasakiinfo
aws sts get-caller-identity          # Account 값(12자리)을 확인
```

### 2. 사전 확인 (명령 세 개)

```sh
# (a) Lambda 동시성 한도. 1000이면 그대로 진행.
#     10처럼 작으면 예약 동시성을 설정할 수 없으므로 4단계에서 -c api_reserved_concurrency=0 을 붙인다
aws lambda get-account-settings --region ap-northeast-2 --query AccountLimit.ConcurrentExecutions

# (b) GitHub OIDC 공급자가 이미 있는지 (지난번 콘솔 안내 2단계를 했다면 있음)
aws iam list-open-id-connect-providers
#     token.actions.githubusercontent.com 이 보이면 그 ARN을 4단계에서 -c github_oidc_provider_arn=<ARN> 으로 넘긴다

# (c) 지난번 콘솔 안내로 만든 역할이 있다면 지운다 (새 스택이 같은 이름의 역할을 만든다)
aws iam get-role --role-name takasakiinfo-github-deploy   # NoSuchEntity면 없음
```

(c)에서 역할이 있다고 나오면 IAM 콘솔에서 `takasakiinfo-github-deploy` 역할을 삭제한다(인라인 정책도 함께 삭제됨).

### 3. CDK 부트스트랩 (계정당 한 번)

두 리전 모두에 CDK 배포용 리소스(작은 S3 버킷, IAM 역할)를 만든다.

```sh
cd infra
uv sync
npx aws-cdk@2 bootstrap aws://<ACCOUNT>/ap-northeast-2 aws://<ACCOUNT>/us-east-1
```

### 4. 배포

```sh
npx aws-cdk@2 deploy --all \
  -c account=<ACCOUNT> \
  -c alert_email=<알림 받을 이메일>
# 필요하면 추가: -c github_oidc_provider_arn=<ARN>   -c api_reserved_concurrency=0
```

- IAM 변경을 확인하는 질문이 나오면 내용을 보고 `y`.
- CloudFront 배포 생성 때문에 10~20분 걸린다.
- **Plan 스택에서 실패한다면** Flat-rate 플랜에 가입할 수 없는 계정이라는 뜻이다. WAF만 붙은 채로 두면 요금(월 약 $8)이 나오므로 바로 종량제로 바꾼다:
  ```sh
  npx aws-cdk@2 deploy TakasakiInfo-App -c account=<ACCOUNT> -c alert_email=<이메일> -c flat_rate=false
  npx aws-cdk@2 destroy TakasakiInfo-Plan TakasakiInfo-Waf -c account=<ACCOUNT>
  ```

끝나면 `TakasakiInfo-App`의 Outputs가 출력된다.

### 5. GitHub 저장소 변수

**Settings → Secrets and variables → Actions → Variables**에 등록한다. 모두 비밀값이 아니다.

| 변수 | 값 (App 스택 Outputs) |
| --- | --- |
| `AWS_ROLE_ARN` | `DeployRoleArn` |
| `AWS_REGION` | `ap-northeast-2` |
| `S3_BUCKET` | `BucketName` |
| `DISTRIBUTION_ID` | `DistributionId` |
| `BASE_URL` | `BaseUrl` |

`gh` CLI가 있다면 `gh variable set AWS_ROLE_ARN --body '<값>'` 식으로 등록할 수도 있다.

### 6. 확인

- **시험 업로드 (공개 데이터는 안 바뀜)**: GitHub → Actions → `deploy` → Run workflow → 브랜치 `dev/automation`. S3에 `releases/<커밋>/`만 생긴다.
- **실제 배포**: `dev/automation`을 PR로 `main`에 병합하면 `deploy`가 자동으로 업로드 → 공개 → 무효화 → 스모크 테스트까지 한다. 실패하면 직전 릴리스로 되돌린다.
- 브라우저로 확인: `<BaseUrl>/`, `<BaseUrl>/data/version.json`, `<BaseUrl>/data/v1/TakasakiInfo.json`, `<BaseUrl>/api/v2/health`
- 우회 차단 확인: S3 버킷 주소와 Lambda Function URL을 직접 열면 403이 나와야 한다.

### 7. 정리

- 첫 `main` 배포가 성공하면 `cdk.json`의 `deploy_branches`에서 `dev/automation`을 빼고 `npx aws-cdk@2 deploy TakasakiInfo-App -c account=<ACCOUNT> -c alert_email=<이메일>`.
- 기존 API Gateway·Lambda·S3 객체는 새 API(Phase 6) 공개 직후 삭제한다(결정 D20).

## 평소 작업

| 할 일 | 명령 |
| --- | --- |
| 바뀔 내용 미리 보기 | `npx aws-cdk@2 diff --all -c account=<ACCOUNT> -c alert_email=<이메일>` |
| 인프라 변경 반영 | `npx aws-cdk@2 deploy --all -c account=<ACCOUNT> -c alert_email=<이메일>` |
| 테스트 (AWS 호출 없음) | `uv run pytest -q` |

데이터 배포는 인프라와 무관하게 `main` 병합 때 Actions가 한다(`.github/workflows/deploy.yml`).

## 비용

- CloudFront: Flat-rate Free, $0. WAF도 포함. 월 요청 100만·전송 100GB가 기준 사용량이고 초과 요금은 없다
- Lambda: 상시 무료 범위(월 요청 100만 건) 안. CloudFront 캐시 덕에 호출이 적다. 예약 동시성 5로 상한
- S3: 수 MB. 플랜의 S3 크레딧(5GB)으로 상쇄
- CloudWatch Logs(Lambda 로그, 30일 보관)와 CDK 부트스트랩 버킷: 사실상 0
- 예산 알림: 계정 전체 월 비용이 $1의 80%를 넘거나 넘을 것으로 예측되면 메일
