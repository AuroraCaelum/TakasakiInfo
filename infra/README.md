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
| `TakasakiInfo-App` | ap-northeast-2 | S3 버킷, API Lambda + Function URL, CloudFront 배포, GitHub OIDC 공급자와 배포 역할, 예산 알림 |
| `TakasakiInfo-Plan` | us-east-1 | CloudFront Flat-rate **Free** 플랜 가입 (가입 API가 us-east-1에만 있음) |

세 스택은 CDK의 리전 간 참조로 연결된다. 배포 순서는 Waf → App → Plan이고, CDK가 알아서 지킨다.

GitHub Actions가 쓰는 OIDC 공급자와 배포 역할(`takasakiinfo-github-deploy`)도 App 스택이 만든다. 콘솔에서 따로 만들 것은 없다.

## 처음 배포하기

### 0. 준비물

- AWS CLI v2 (`aws --version`)
- Node.js 22 또는 24 LTS. 다른 버전이면 CDK가 경고를 내는데, `export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1`로 끌 수 있다
- [uv](https://docs.astral.sh/uv/)

### 1. 로컬 관리자 자격 증명

인프라 배포는 관리자 권한이 필요하다. GitHub Actions에는 이 권한을 주지 않고, 사람이 로컬에서 한다. 루트 계정의 액세스 키는 쓰지 않고, 관리자용 IAM 사용자를 따로 만든다. IAM Identity Center(`aws configure sso`)는 쓰지 않는다.

1. IAM 콘솔 → 사용자 → 사용자 생성. 이름은 `takasakiinfo-admin`. 콘솔 접근 권한은 주지 않는다
2. 권한 옵션: 직접 정책 연결 → `AdministratorAccess`
3. 만든 사용자 → 보안 자격 증명 탭 → 액세스 키 만들기 → 사용 사례 "CLI"
4. 키를 로컬 프로필에 넣는다:
   ```sh
   aws configure --profile takasakiinfo
   # AWS Access Key ID / Secret Access Key: 3에서 받은 값
   # Default region name: ap-northeast-2
   # Default output format: Enter
   ```
5. 확인한다:
   ```sh
   export AWS_PROFILE=takasakiinfo
   aws sts get-caller-identity
   # Arn이 arn:aws:iam::<ACCOUNT>:user/takasakiinfo-admin 이면 맞다
   # Account 값(12자리)은 3·4단계에서 쓴다
   ```

이 키는 오래 사는 관리자 키다. 배포가 끝나면 비활성화하고(7단계), 인프라를 바꿀 때만 다시 켠다.

### 2. 사전 확인

```sh
# (a) Lambda 동시성 한도
aws lambda get-account-settings --region ap-northeast-2 --query AccountLimit.ConcurrentExecutions

# (b) GitHub OIDC 공급자가 이미 있는지
aws iam list-open-id-connect-providers
```

- (a) Lambda는 예약하지 않은 동시성을 100 이상 남겨야 한다. 이 스택은 API 함수에 5를 예약하므로 **105 이상**이면 그대로 진행한다(보통 400 또는 1000). 그보다 작으면 4단계에서 `-c api_reserved_concurrency=0`을 붙인다.
- (b) 결과가 비어 있으면 그대로 진행한다. 스택이 공급자를 만든다. 다른 프로젝트가 만든 `token.actions.githubusercontent.com` 공급자가 보이면, 계정에 하나만 둘 수 있으므로 4단계에서 `-c github_oidc_provider_arn=<그 ARN>`을 붙여 그것을 쓴다.

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
# 2단계 결과에 따라 추가: -c api_reserved_concurrency=0   -c github_oidc_provider_arn=<ARN>
```

- IAM 변경을 확인하는 질문이 나오면 내용을 보고 `y`.
- CloudFront 배포 생성 때문에 10~20분 걸린다.
- **Plan 스택에서 실패한다면** Flat-rate 플랜에 가입할 수 없는 계정이라는 뜻이다. WAF만 붙은 채로 두면 요금(월 약 $8)이 나오므로 바로 종량제로 바꾼다:
  ```sh
  npx aws-cdk@2 deploy TakasakiInfo-App -c account=<ACCOUNT> -c alert_email=<이메일> -c flat_rate=false
  npx aws-cdk@2 destroy TakasakiInfo-Plan TakasakiInfo-Waf -c account=<ACCOUNT>
  ```

끝나면 `TakasakiInfo-App`의 Outputs가 출력된다. 5단계에서 쓴다.

### 5. GitHub 저장소 설정

**Settings → Secrets and variables → Actions**에 등록한다. 공개 저장소의 Actions 로그는 누구나 볼 수 있다. 그래서 AWS 계정 ID가 들어 있는 역할 ARN은 **Secrets**에 넣어 로그에서 가리고, 나머지는 **Variables**에 넣는다.

| 탭 | 이름 | 값 (App 스택 Outputs) |
| --- | --- | --- |
| Secrets | `AWS_ROLE_ARN` | `DeployRoleArn` |
| Variables | `AWS_REGION` | `ap-northeast-2` |
| Variables | `S3_BUCKET` | `BucketName` |
| Variables | `DISTRIBUTION_ID` | `DistributionId` |
| Variables | `BASE_URL` | `BaseUrl` |

- 버킷 이름과 배포 ID는 알려져도 쓸 수 없는 값이라 Variables에 둔다. 버킷은 비공개이고, 배포 ID는 자격 증명 없이는 쓸 수 없다.
- `S3_BUCKET`이 등록되기 전까지 `deploy` 워크플로는 건너뛴다.
- `gh` CLI로도 등록할 수 있다: `gh secret set AWS_ROLE_ARN --body '<값>'`, `gh variable set S3_BUCKET --body '<값>'`.

**계정 정보는 저장소에 남기지 않는다.** 계정 ID와 이메일은 명령줄 `-c`로만 넘기고 `cdk.json`에 적지 않는다. CDK가 계정 정보를 담아 만드는 `cdk.context.json`은 `.gitignore`에 들어 있다.

### 6. 확인

- **시험 업로드 (공개 데이터는 안 바뀜)**: GitHub → Actions → `deploy` → Run workflow → 브랜치 `dev/automation`. S3에 `releases/<커밋>/`만 생긴다.
- **실제 배포**: `dev/automation`을 PR로 `main`에 병합하면 `deploy`가 자동으로 업로드 → 공개 → 무효화 → 스모크 테스트까지 한다. 실패하면 직전 릴리스로 되돌린다.
- 브라우저로 확인: `<BaseUrl>/`, `<BaseUrl>/data/version.json`, `<BaseUrl>/data/v1/TakasakiInfo.json`, `<BaseUrl>/api/v2/health`
- 우회 차단 확인: S3 버킷 주소와 Lambda Function URL을 직접 열면 403이 나와야 한다.

### 7. 정리

- IAM 콘솔 → `takasakiinfo-admin` → 보안 자격 증명 탭에서 액세스 키를 **비활성화**한다. 삭제하지 않아도 된다. 다음에 인프라를 바꿀 때 다시 활성화한다.
- 첫 `main` 배포가 성공하면 `cdk.json`의 `deploy_branches`에서 `dev/automation`을 빼고 `npx aws-cdk@2 deploy TakasakiInfo-App -c account=<ACCOUNT> -c alert_email=<이메일>`.
- 기존 API Gateway·Lambda·S3 객체는 새 API(Phase 6) 공개 직후 삭제한다(결정 D20).

## 평소 작업

인프라 명령은 `takasakiinfo-admin` 액세스 키를 잠깐 활성화하고 `export AWS_PROFILE=takasakiinfo`로 실행한다. 끝나면 키를 다시 비활성화한다.

| 할 일 | 명령 |
| --- | --- |
| 바뀔 내용 미리 보기 | `npx aws-cdk@2 diff --all -c account=<ACCOUNT> -c alert_email=<이메일>` |
| 인프라 변경 반영 | `npx aws-cdk@2 deploy --all -c account=<ACCOUNT> -c alert_email=<이메일>` |
| 테스트 (AWS 호출 없음, 키 필요 없음) | `uv run pytest -q` |

데이터 배포는 인프라와 무관하게 `main` 병합 때 Actions가 한다(`.github/workflows/deploy.yml`). 관리자 키는 쓰지 않는다.

## 비용

- CloudFront: Flat-rate Free, $0. WAF도 포함. 월 요청 100만·전송 100GB가 기준 사용량이고 초과 요금은 없다
- Lambda: 상시 무료 범위(월 요청 100만 건) 안. CloudFront 캐시 덕에 호출이 적다. 예약 동시성 5로 상한
- S3: 수 MB. 플랜의 S3 크레딧(5GB)으로 상쇄
- CloudWatch Logs(Lambda 로그, 30일 보관)와 CDK 부트스트랩 버킷: 사실상 0
- 예산 알림: 계정 전체 월 비용이 $1의 80%를 넘거나 넘을 것으로 예측되면 메일
