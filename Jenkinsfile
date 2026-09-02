// ---------------------------------------------------------------------------
// Jenkinsfile — CloudeDX 저장소에 둔다. reluxe-gitops 가 아니다.
//
// 🔴 같은 저장소에 두면 무한 루프가 난다.
//    Jenkins 가 빌드 → values 에 태그 커밋 → 그 커밋이 Jenkins 를 다시 깨움 → 반복.
//    커밋하는 곳(reluxe-gitops)과 Jenkins 를 깨우는 곳(CloudeDX)이 달라야 한다.
//
// 파이프라인: lint → test → build → chart lint → update gitops
// 배포는 하지 않는다. Argo CD 가 git 을 보고 가져간다.
//
// 🔴 에이전트는 컨테이너 3개짜리 파드다 (helm-values/jenkins.yaml)
//      python   uv · ruff · pytest · alembic
//      buildah  이미지 빌드/푸시
//      tools    helm · git
//    단계마다 container('이름') 으로 골라 쓴다. 한 컨테이너에 전부 있지 않다.
// ---------------------------------------------------------------------------
pipeline {
    agent { label 'build' }

    options {
        // 같은 브랜치의 이전 빌드가 돌고 있으면 취소한다 (ci.yml 의 concurrency 와 같은 취지)
        disableConcurrentBuilds()
        timeout(time: 60, unit: 'MINUTES')
    }

    environment {
        // 🔴 문서 0-C IP 대역표와 일치해야 한다. AWS 파이프라인에서는 ECR 주소로 교체.
        REGISTRY    = '192.168.56.15:30500'
        GITOPS_REPO = 'github.com/jpnjb0918-glitch/reluxe-gitops.git'
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
                    // python:3.13-slim 에는 uv 가 없다. 매 빌드마다 설치한다.
                    sh '''
                        pip install --no-cache-dir uv
                        uv --version
                    '''
                }
            }
        }

        stage('lint') {
            steps {
                container('python') {
                    sh 'uv run ruff check .'
                }
            }
        }

        stage('test') {
            // 🔴 docker run 으로 DB 를 띄우지 않는다.
            //    k3s 에는 Docker 데몬이 없어 그 방식은 실패한다.
            //    Kubernetes 플러그인의 사이드카로 Postgres 를 붙인다.
            //    같은 파드 안이라 127.0.0.1 로 접근된다.
            agent {
                kubernetes {
                    yaml '''
spec:
  nodeSelector:
    workload: batch
  tolerations:
    - key: workload
      operator: Equal
      value: batch
      effect: NoSchedule
  containers:
    - name: python
      image: python:3.13-slim
      command: ["sleep"]
      args: ["99d"]
    - name: postgres
      image: postgres:17-alpine
      env:
        - name: POSTGRES_USER
          value: reluxe
        - name: POSTGRES_PASSWORD
          value: test
        - name: POSTGRES_DB
          value: reluxe_test
'''
                }
            }
            steps {
                container('python') {
                    sh '''
                        set -e
                        pip install --no-cache-dir uv

                        # 사이드카가 뜰 때까지 기다린다. 고정 sleep 은 느린 노드에서 부족하다.
                        for i in $(seq 1 30); do
                          if python -c "import socket;socket.create_connection(('127.0.0.1',5432),1)" 2>/dev/null; then
                            echo "DB 준비 완료"; break
                          fi
                          echo "DB 대기 중... ($i/30)"; sleep 2
                        done

                        # crawler extra 를 설치하지 않는다.
                        # 백엔드가 실수로 크롤러를 임포트하면 여기서 걸린다 (ci.yml 과 같은 의도).
                        uv sync

                        export DATABASE_URL="postgresql+asyncpg://reluxe:test@127.0.0.1:5432/reluxe_test"
                        uv run alembic upgrade head
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
                    // --tls-verify=false 는 사설 레지스트리가 HTTP 이기 때문 (registries.yaml 과 동일)
                    sh """
                        set -e
                        buildah bud -f dockerfile.backend -t ${REGISTRY}/reluxe-backend:${IMAGE_TAG} .
                        buildah bud -f dockerfile.crawler -t ${REGISTRY}/reluxe-crawler:${IMAGE_TAG} .

                        buildah push --tls-verify=false ${REGISTRY}/reluxe-backend:${IMAGE_TAG}
                        buildah push --tls-verify=false ${REGISTRY}/reluxe-crawler:${IMAGE_TAG}
                    """
                }
            }
        }

        stage('chart lint') {
            steps {
                container('tools') {
                    // 차트가 실제로 렌더링되는지 확인한다.
                    // 문법 오류를 클러스터에 올리기 전에 여기서 잡는다.
                    sh """
                        set -e
                        # 🔴 alpine/helm 은 Alpine 기반이라 git 이 없다.
                        #    Alpine 이미지는 git 을 기본 포함하지 않으므로 직접 설치한다.
                        command -v git >/dev/null 2>&1 || apk add --no-cache git

                        rm -rf gitops-check
                        git clone --depth 1 https://${GITOPS_REPO} gitops-check

                        helm lint gitops-check/charts/reluxe
                        helm template reluxe gitops-check/charts/reluxe \\
                            -f gitops-check/charts/reluxe/${VALUES_FILE} > /dev/null
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
                        // 🔴 이 단계만 reluxe-gitops 에 커밋한다.
                        //    Jenkins 는 클러스터를 만지지 않는다. kubectl 도 쓰지 않는다.
                        sh '''
                            set -e
                            command -v git >/dev/null 2>&1 || apk add --no-cache git

                            rm -rf gitops-update
                            git clone https://${GIT_USER}:${GIT_TOKEN}@${GITOPS_REPO} gitops-update

                            cd gitops-update/charts/reluxe
                            sed -i "s|^  tag: .*|  tag: \\"${IMAGE_TAG}\\"|" ${VALUES_FILE}

                            git config user.email 'jenkins@reluxe.local'
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
            //
            // 🔴 container('tools') 로 감싸지 않는다.
            //    파이프라인이 앞 단계에서 실패하면 그 컨테이너가 없을 수 있고,
            //    그러면 정리 자체가 실패해 원래 오류가 가려진다.
            //    rm 은 기본 jnlp 컨테이너에도 있으므로 그대로 쓴다.
            sh 'rm -rf gitops-check gitops-update || true'
        }
        success {
            echo "빌드 성공 — 이미지 태그 ${env.IMAGE_TAG}"
        }
        failure {
            echo '빌드 실패. 위 로그에서 실패한 stage 를 확인할 것.'
        }
    }
}
// 배포는 여기서 하지 않는다 — Argo CD 의 selfHeal 이 위 커밋을 감지해 가져간다.
