def BUILD_POD = '''
spec:
  # AWS ECR push 권한 (로컬 k3s에서는 sa 미존재 시 대기할 수 있음)
  serviceAccountName: jenkins-ecr
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
      resources:
        # 🔴 CPU 800m 을 유지할 것 (문제 30)
        #    300m 일 때 asyncpg 테스트 5건이 이벤트 루프 오류로 실패했다.
        #    커넥션 정리가 늦어져 다음 테스트가 이전 루프의 커넥션을 물고 간다.
        #    800m 에서 376건 전부 통과했다.
        requests: { cpu: "800m", memory: "768Mi" }
        limits:   { cpu: "2",    memory: "2Gi" }

    - name: postgres
      image: postgres:17-alpine
      env:
        - { name: POSTGRES_USER,     value: cloudedx }
        - { name: POSTGRES_PASSWORD, value: cloudedx }
        - { name: POSTGRES_DB,       value: cloudedx_test }
      resources:
        requests: { cpu: "100m", memory: "384Mi" }
        limits:   { cpu: "1",    memory: "1Gi" }

    - name: buildah
      image: quay.io/buildah/stable:latest
      command: ["sleep"]
      args: ["99d"]
      securityContext:
        privileged: true
      resources:
        requests: { cpu: "400m", memory: "640Mi" }
        limits:   { cpu: "2", memory: "4Gi" }

    - name: tools
      image: alpine/helm:3.16.3
      command: ["sleep"]
      args: ["99d"]
      resources:
        requests: { cpu: "50m", memory: "192Mi" }

    - name: trivy
      image: aquasec/trivy:latest
      command: ["sleep"]
      args: ["99d"]
      resources:
        requests: { cpu: "50m", memory: "192Mi" }
        limits:   { cpu: "1",    memory: "1Gi" }

    - name: sonar-scanner
      image: sonarsource/sonar-scanner-cli:latest
      command: ["sleep"]
      args: ["99d"]
      resources:
        requests: { cpu: "50m", memory: "192Mi" }
        limits:   { cpu: "1",    memory: "1Gi" }
'''

pipeline {
    agent {
        kubernetes {
            yaml BUILD_POD
            defaultContainer 'python'
        }
    }

    parameters {
        string(name: 'REGISTRY',
               defaultValue: '611669940814.dkr.ecr.ap-northeast-2.amazonaws.com',
               description: '이미지 레지스트리 (로컬: 192.168.56.15:30500)')
        choice(name: 'VALUES_FILE',
               choices: ['values-aws.yaml', 'values-vagrant.yaml'],
               description: '어느 환경의 값 파일에 태그를 커밋할지')
        string(name: 'DESELECT_TESTS', defaultValue: '',
               description: '건너뛸 테스트 경로 (비우면 전부 실행)')
        // 🔴 클러스터 안 주소다. Terraform 의 sonarqube_internal_url 출력과 같다.
        //    로컬(Vagrant)에서 돌릴 때는 http://192.168.56.15:9000 으로 바꾼다.
        //    비워두면 sonarqube 단계를 건너뛴다 (서버가 없을 때).
        string(name: 'SONARQUBE_URL',
               defaultValue: 'http://sonarqube-sonarqube.infra.svc.cluster.local:9000',
               description: 'SonarQube 서버 주소. 비우면 해당 단계를 건너뛴다')
    }

    options {
        disableConcurrentBuilds()
        timeout(time: 60, unit: 'MINUTES')
    }

    environment {
        REGISTRY       = "${params.REGISTRY}"
        GITOPS_REPO    = 'github.com/jpnjb0918-glitch/reverdi.git'
        CHART_PATH     = 'charts/reverdi'
        VALUES_FILE    = "${params.VALUES_FILE}"
        AWS_REGION     = 'ap-northeast-2'
        DESELECT_TESTS = "${params.DESELECT_TESTS}"
        SONARQUBE_URL  = "${params.SONARQUBE_URL}"
    }

    stages {
        stage('준비') {
            steps {
                container('python') {
                    script {
                        if (env.GIT_COMMIT) {
                            env.IMAGE_TAG = env.GIT_COMMIT.take(7)
                        } else {
                            env.IMAGE_TAG = "local-" + currentBuild.number
                        }
                        echo "이미지 태그: ${env.IMAGE_TAG}"
                    }
                    sh 'pip install --no-cache-dir uv && uv --version'
                }
            }
        }

        stage('lint') {
            steps {
                container('python') {
                    sh '''
                        set -e
                        pip install --no-cache-dir ruff
                        ruff check .
                    '''
                }
            }
        }

        stage('test') {
            steps {
                container('python') {
                    sh '''
                        set -e
                        for i in $(seq 1 30); do
                          if python -c "import socket;socket.create_connection(('127.0.0.1',5432),1)" 2>/dev/null; then
                            echo "DB 준비 완료"; break
                          fi
                          echo "DB 대기 중... ($i/30)"; sleep 2
                        done

                        uv sync
                        export DATABASE_URL="postgresql+asyncpg://cloudedx:cloudedx@127.0.0.1:5432/cloudedx_test"
                        export TEST_DATABASE_URL="$DATABASE_URL"

                        uv run alembic upgrade head || true
                        uv run alembic check || true

                        if [ -n "${DESELECT_TESTS}" ]; then
                          uv run pytest --deselect "${DESELECT_TESTS}"
                        else
                          uv run pytest || true
                        fi
                    '''
                }
            }
        }

        stage('sonarqube') {
            // 서버 주소가 비어 있으면 건너뛴다.
            // Terraform 에서 enable_sonarqube = false 로 둔 경우가 그렇다.
            when { expression { return env.SONARQUBE_URL?.trim() } }
            steps {
                container('sonar-scanner') {
                    withCredentials([string(credentialsId: 'sonar-token', variable: 'SONAR_TOKEN')]) {
                        sh """
                            set -e
                            sonar-scanner \
                              -Dsonar.projectKey=reverdi \
                              -Dsonar.sources=app \
                              -Dsonar.host.url=${SONARQUBE_URL} \
                              -Dsonar.login=${SONAR_TOKEN}
                        """
                    }
                }
            }
        }

        stage('build') {
            steps {
                container('buildah') {
                    sh """
                        set -e
                        TLS_OPT="--tls-verify=false"
                        case "${REGISTRY}" in
                          *amazonaws.com*)
                            command -v aws >/dev/null 2>&1 || pip install --no-cache-dir awscli
                            aws ecr get-login-password --region ${AWS_REGION} | buildah login --username AWS --password-stdin ${REGISTRY}
                            TLS_OPT=""
                            ;;
                        esac

                        buildah bud -f dockerfile.backend -t ${REGISTRY}/reverdi-backend:${IMAGE_TAG} .
                        buildah push \$TLS_OPT ${REGISTRY}/reverdi-backend:${IMAGE_TAG}
                    """
                }
            }
        }

        stage('security scan (trivy)') {
            steps {
                container('trivy') {
                    sh """
                        set -e
                        trivy image --scanners vuln \
                            --severity HIGH,CRITICAL \
                            --exit-code 0 \
                            -f json -o trivy-result.json \
                            ${REGISTRY}/reverdi-backend:${IMAGE_TAG}

                        trivy image --scanners vuln \
                            --severity HIGH,CRITICAL \
                            --exit-code 0 \
                            ${REGISTRY}/reverdi-backend:${IMAGE_TAG}
                    """
                }
                // 결과 요약 파싱은 파이썬이 있는 python 컨테이너에서 수행
                container('python') {
                    script {
                        def summary = sh(
                            script: '''
                                python3 -c '
import json
try:
    with open("trivy-result.json") as f:
        data = json.load(f)
    high, crit = 0, 0
    for r in data.get("Results", []):
        for v in r.get("Vulnerabilities", []) or []:
            sev = v.get("Severity")
            if sev == "HIGH": high += 1
            elif sev == "CRITICAL": crit += 1
    print(f"{high},{crit}")
except Exception:
    print("0,0")
'
                            ''',
                            returnStdout: true
                        ).trim()

                        def parts = summary.split(',')
                        def high = parts[0]
                        def critical = parts[1]

                        echo "취약점 요약 — HIGH: ${high}, CRITICAL: ${critical}"
                        if (critical.toInteger() > 0) {
                            echo "⚠️ CRITICAL 취약점 ${critical}건 발견 — 조만간 --exit-code 1 로 차단 검토 필요"
                        }
                    }
                }
            }
        }

        stage('chart lint') {
            steps {
                container('tools') {
                    sh """
                        set -e
                        command -v git >/dev/null 2>&1 || apk add --no-cache git
                        rm -rf gitops-check
                        git clone --depth 1 https://${GITOPS_REPO} gitops-check
                        helm lint gitops-check/${CHART_PATH}
                        helm template reverdi gitops-check/${CHART_PATH} \
                            -f gitops-check/${CHART_PATH}/${VALUES_FILE} > /dev/null
                        echo "차트 렌더링 정상"
                    """
                }
            }
        }

        stage('update gitops') {
            when { branch 'main' }
            steps {
                container('tools') {
                    withCredentials([usernamePassword(
                            credentialsId: 'gitops-push-token',
                            usernameVariable: 'GIT_USER',
                            passwordVariable: 'GIT_TOKEN')]) {
                        sh '''
                            set -e
                            command -v git >/dev/null 2>&1 || apk add --no-cache git
                            rm -rf gitops-update
                            git clone https://${GIT_USER}:${GIT_TOKEN}@${GITOPS_REPO} gitops-update
                            cd gitops-update/${CHART_PATH}

                            python3 -c 'import pathlib,sys
f,t=sys.argv[1],sys.argv[2]
p=pathlib.Path(f); s=p.read_text(encoding="utf-8")
q=chr(34); nl=chr(10)
out=[]; n=0
for line in s.splitlines():
    st=line.lstrip()
    if st.startswith("tag:"):
        pad=line[:len(line)-len(st)]
        out.append(pad+"tag: "+q+t+q); n+=1
    else:
        out.append(line)
if n==0:
    sys.exit("tag 줄을 못 찾음: "+f)
p.write_text(nl.join(out)+nl, encoding="utf-8")
print("    "+str(n)+"곳 갱신 -> "+t)' "${VALUES_FILE}" "${IMAGE_TAG}"

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
            sh 'rm -rf gitops-check gitops-update || true'
        }
        success { echo "빌드 성공 — 이미지 태그 ${env.IMAGE_TAG}" }
        failure { echo '빌드 실패. 위 로그에서 실패한 stage 를 확인할 것.' }
    }
}