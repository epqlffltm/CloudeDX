// ---------------------------------------------------------------------------
// Jenkinsfile — CloudeDX 저장소에 둔다. reverdi(배포 저장소)가 아니다.
//
// 🔴 같은 저장소에 두면 무한 루프가 난다.
//    Jenkins 가 빌드 → values 에 태그 커밋 → 그 커밋이 Jenkins 를 다시 깨움 → 반복.
//    커밋하는 곳(reverdi)과 Jenkins 를 깨우는 곳(CloudeDX)이 달라야 한다.
//
// 파이프라인: lint → test → build → chart lint → update gitops
// 배포는 하지 않는다. Argo CD 가 git 을 보고 가져간다.
//
// 🔴 파드 정의를 이 파일 안에 둔다 (인라인).
//    helm-values/jenkins.yaml 의 podTemplates 에 의존하지 않는 이유:
//      · agent.enabled: false 면 차트가 podTemplates 를 렌더링하지 않는다
//      · Jenkins 를 다시 깔면 UI 설정이 사라진다
//      · 설정이 코드에 남아야 재현된다
// ---------------------------------------------------------------------------

// 빌드용 파드 — 컨테이너를 역할별로 나눈다.
// 한 이미지에 uv·buildah·helm·git 이 다 들어있지 않기 때문이다.
def BUILD_POD = '''
spec:
  # 🔴 배치 노드에서 빌드한다. 웹 노드의 자원을 쓰면 서비스 응답이 흔들린다.
  nodeSelector:
    workload: batch
  # 🔴 node4 에 taint(workload=batch:NoSchedule)가 걸려 있다.
  #    toleration 없이는 파드가 Pending 에서 멈춘다.
  tolerations:
    - key: workload
      operator: Equal
      value: batch
      effect: NoSchedule
  containers:
    # --- 파이썬 lint / test ---------------------------------------------
    - name: python
      image: python:3.13-slim
      command: ["sleep"]
      args: ["99d"]
      resources:
        requests: { cpu: "500m", memory: "1Gi" }
        limits:   { cpu: "2",    memory: "2Gi" }

    # --- 테스트용 Postgres (사이드카) ------------------------------------
    # 🔴 docker run 으로 띄우지 않는다. k3s 는 containerd 라 Docker 데몬이 없다.
    #    같은 파드 안이라 127.0.0.1 로 접근된다.
    - name: postgres
      image: postgres:17-alpine
      env:
        - { name: POSTGRES_USER,     value: cloudedx }
        - { name: POSTGRES_PASSWORD, value: cloudedx }
        - { name: POSTGRES_DB,       value: cloudedx_test }
      resources:
        requests: { cpu: "200m", memory: "512Mi" }
        limits:   { cpu: "1",    memory: "1Gi" }

    # --- 이미지 빌드 -----------------------------------------------------
    - name: buildah
      image: quay.io/buildah/stable:latest
      command: ["sleep"]
      args: ["99d"]
      # 🔴 rootless 빌드에도 특별 권한이 필요하다.
      #    배치 전용 노드라 웹 파드에는 영향이 없다.
      securityContext:
        privileged: true
      resources:
        requests: { cpu: "1", memory: "2Gi" }
        # 크롤러 이미지가 2.7GB 라 여유를 준다
        limits:   { cpu: "2", memory: "4Gi" }

    # --- helm / git ------------------------------------------------------
    - name: tools
      # ⚠️ Alpine 기반이라 git 이 기본 포함되지 않는다.
      #    아래 stage 에서 apk add 로 설치한다.
      #    ENTRYPOINT 가 helm 이므로 command 로 덮어써야 sh 가 돈다.
      image: alpine/helm:3.16.3
      command: ["sleep"]
      args: ["99d"]
      resources:
        requests: { cpu: "200m", memory: "512Mi" }
'''

pipeline {
    agent {
        kubernetes {
            yaml BUILD_POD
            defaultContainer 'python'
        }
    }

    options {
        disableConcurrentBuilds()
        timeout(time: 60, unit: 'MINUTES')
    }

    environment {
        // 🔴 문서 0-C IP 대역표와 일치해야 한다. AWS 에서는 ECR 주소로 교체.
        REGISTRY    = '192.168.56.15:30500'
        // 🔴 배포 저장소. 앱 소스(CloudeDX)와 다른 곳이어야 한다.
        GITOPS_REPO = 'github.com/jpnjb0918-glitch/reverdi.git'
        CHART_PATH  = 'charts/reverdi'
        VALUES_FILE = 'values-vagrant.yaml'   // AWS 에서는 values-aws.yaml
    }

    stages {

        stage('준비') {
            steps {
                container('python') {
                    script {
                        // 🔴 GIT_COMMIT 은 체크아웃 이후에만 채워진다.
                        //    environment 블록에서 쓰면 null 이 되어 태그가 비어버린다.
                        env.IMAGE_TAG = env.GIT_COMMIT.take(7)
                        echo "이미지 태그: ${env.IMAGE_TAG}"
                    }
                    // python:3.13-slim 에는 uv 가 없다.
                    sh 'pip install --no-cache-dir uv && uv --version'
                }
            }
        }

        stage('lint') {
            steps {
                container('python') {
                    // ci.yml 과 동일하게 crawler extra 까지 포함해 검사한다.
                    sh '''
                        set -e
                        uv sync --extra crawler
                        uv run ruff check .
                    '''
                }
            }
        }

        stage('test') {
            steps {
                container('python') {
                    sh '''
                        set -e

                        # 사이드카가 접속을 받을 때까지 기다린다.
                        # 고정 sleep 은 느린 노드에서 부족하다.
                        for i in $(seq 1 30); do
                          if python -c "import socket;socket.create_connection(('127.0.0.1',5432),1)" 2>/dev/null; then
                            echo "DB 준비 완료"; break
                          fi
                          echo "DB 대기 중... ($i/30)"; sleep 2
                        done

                        # 🔴 crawler extra 를 설치하지 않는다.
                        #    백엔드가 실수로 크롤러를 최상단에서 임포트하면 여기서 걸린다.
                        uv sync

                        export DATABASE_URL="postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx_test"
                        export TEST_DATABASE_URL="$DATABASE_URL"

                        uv run alembic upgrade head
                        # 모델을 고치고 마이그레이션을 안 만든 경우가 여기서 걸린다.
                        uv run alembic check
                        uv run pytest
                    '''
                }
            }
        }

        stage('build') {
            steps {
                container('buildah') {
                    // 🔴 k3s 는 containerd 라 docker build 가 안 된다. Buildah 를 쓴다.
                    //    Kaniko 는 2025년 6월 아카이브되어 쓰지 않는다.
                    // --tls-verify=false 는 사설 레지스트리가 HTTP 이기 때문
                    //    (infra/registries.yaml 의 insecure_skip_verify 와 짝)
                    sh """
                        set -e
                        buildah bud -f dockerfile.backend -t ${REGISTRY}/reverdi-backend:${IMAGE_TAG} .
                        buildah bud -f dockerfile.crawler -t ${REGISTRY}/reverdi-crawler:${IMAGE_TAG} .

                        buildah push --tls-verify=false ${REGISTRY}/reverdi-backend:${IMAGE_TAG}
                        buildah push --tls-verify=false ${REGISTRY}/reverdi-crawler:${IMAGE_TAG}
                    """
                }
            }
        }

        stage('chart lint') {
            steps {
                container('tools') {
                    // 차트가 실제로 렌더링되는지 확인한다.
                    // 템플릿 오류를 클러스터에 올리기 전에 잡는다.
                    sh """
                        set -e
                        command -v git >/dev/null 2>&1 || apk add --no-cache git

                        rm -rf gitops-check
                        git clone --depth 1 https://${GITOPS_REPO} gitops-check

                        helm lint gitops-check/${CHART_PATH}
                        helm template reverdi gitops-check/${CHART_PATH} \\
                            -f gitops-check/${CHART_PATH}/${VALUES_FILE} > /dev/null
                        echo "차트 렌더링 정상"
                    """
                }
            }
        }

        stage('update gitops') {
            // main 브랜치에서만 커밋한다. PR 빌드가 배포를 일으키면 안 된다.
            when { branch 'main' }
            steps {
                container('tools') {
                    withCredentials([usernamePassword(
                            credentialsId: 'gitops-push-token',
                            usernameVariable: 'GIT_USER',
                            passwordVariable: 'GIT_TOKEN')]) {
                        // 🔴 이 단계만 배포 저장소에 커밋한다.
                        //    Jenkins 는 클러스터를 만지지 않는다. kubectl 도 쓰지 않는다.
                        //    작은따옴표라 Groovy 보간이 없어 토큰이 로그에 안 남는다.
                        sh '''
                            set -e
                            command -v git >/dev/null 2>&1 || apk add --no-cache git

                            rm -rf gitops-update
                            git clone https://${GIT_USER}:${GIT_TOKEN}@${GITOPS_REPO} gitops-update

                            cd gitops-update/${CHART_PATH}
                            sed -i "s|^  tag: .*|  tag: \\"${IMAGE_TAG}\\"|" ${VALUES_FILE}

                            git config user.email 'jenkins@reverdi.local'
                            git config user.name  'jenkins-bot'

                            if git diff --quiet; then
                                echo "태그 변경 없음. 커밋을 건너뛴다."
                            else
                                git commit -am "ci: bump image tag to ${IMAGE_TAG}"
                                git push
                                echo "커밋 완료. Argo CD 가 감지해 배포한다."
                            fi
                        '''
                    }
                }
            }
        }
    }

    post {
        always {
            // 토큰이 들어간 디렉터리를 남기지 않는다.
            // 🔴 container() 로 감싸지 않는다 — 앞 단계가 실패하면 그 컨테이너가
            //    없을 수 있고, 그러면 정리 실패가 원래 오류를 가린다.
            sh 'rm -rf gitops-check gitops-update || true'
        }
        success { echo "빌드 성공 — 이미지 태그 ${env.IMAGE_TAG}" }
        failure { echo '빌드 실패. 위 로그에서 실패한 stage 를 확인할 것.' }
    }
}
// 배포는 여기서 하지 않는다 — Argo CD 의 selfHeal 이 위 커밋을 감지해 가져간다.
