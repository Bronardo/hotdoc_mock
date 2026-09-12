// ============================================================================
// HotDoc mock - Jenkins CI/CD pipeline (SIT772 Task 9.2D)
//
// Flow:
//   GitHub -> Jenkins (10.10.10.100): build & push image to Docker Hub
//   Jenkins (kubectl + kubeconfig at /var/lib/jenkins/.kube/config):
//       create DB secret from Jenkins credential `dbuser_hotdoc_user`,
//       ensure image pull secret from `docker-hub-creds`,
//       apply manifest to the cluster node (IP from `k8s-node-ip-secret`)
//       and verify the rollout.
//
// No credentials are stored in this file or in the Kubernetes manifest.
// ============================================================================

pipeline {
    agent any

    environment {
        APP_NAME    = 'hotdoc-app'
        DOCKER_REPO = 'bronardo/hotdoc-app'
        // Secret-text credential containing only the node IP, e.g. 10.10.10.10
        K8S_NODE_IP = credentials('k8s-node-ip-secret')
        KUBECONFIG  = '/var/lib/jenkins/.kube/config'
    }

    stages {

        stage('Checkout Source Code') {
            steps {
                echo 'Pulling latest code from GitHub...'
                checkout scm
            }
        }

        stage('Build Docker Image') {
            steps {
                echo "Building image ${DOCKER_REPO}:${BUILD_NUMBER} on the Jenkins server..."
                sh """
                    docker build \
                        -t ${DOCKER_REPO}:${BUILD_NUMBER} \
                        -t ${DOCKER_REPO}:latest .
                """
            }
        }

        stage('Push Image to Docker Hub') {
            steps {
                withCredentials([
                    usernamePassword(credentialsId: 'docker-hub-creds',
                                     usernameVariable: 'DOCKER_USER',
                                     passwordVariable: 'DOCKER_PASS')
                ]) {
                    sh '''
                        set -eu
                        # No `set -x`: the password is passed as an argument.
                        printf '%s' "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin
                        docker push "$DOCKER_REPO":latest
                        docker push "$DOCKER_REPO":"$BUILD_NUMBER"
                        docker logout
                    '''
                }
            }
        }

        stage('Create Kubernetes Secrets') {
            steps {
                // Database username/password Secret (out-of-band value source).
                withCredentials([
                    usernamePassword(credentialsId: 'dbuser_hotdoc_user',
                                     usernameVariable: 'HOTDOC_DB_USER',
                                     passwordVariable: 'HOTDOC_DB_PASS'),
                    usernamePassword(credentialsId: 'docker-hub-creds',
                                     usernameVariable: 'DOCKER_USER',
                                     passwordVariable: 'DOCKER_PASS')
                ]) {
                    sh '''
                        set -eu
                        # No `set -x`: credentials are passed as command arguments.
                        # The node IP comes from the Secret-text credential.
                        S="https://${K8S_NODE_IP}:6443"

                        # Secret consumed by the Deployment via secretKeyRef.
                        kubectl --server="$S" create secret generic mysql-vm-secret \
                            --from-literal=db-username="$HOTDOC_DB_USER" \
                            --from-literal=db-password="$HOTDOC_DB_PASS" \
                            --dry-run=client -o yaml | kubectl --server="$S" apply -f -

                        # Registry pull secret referenced by imagePullSecrets.
                        kubectl --server="$S" create secret docker-registry dockerhub-registry \
                            --docker-server=https://index.docker.io/v1/ \
                            --docker-username="$DOCKER_USER" \
                            --docker-password="$DOCKER_PASS" \
                            --dry-run=client -o yaml | kubectl --server="$S" apply -f -
                    '''
                }
            }
        }

        stage('Deploy to Kubernetes') {
            steps {
                echo 'Applying manifest with the immutable build tag (new tag triggers the rollout)...'
                sh '''
                    set -eu
                    sed "s|__IMAGE_TAG__|${BUILD_NUMBER}|g" app-k8s.yaml \
                        | kubectl --server="https://${K8S_NODE_IP}:6443" apply -f -
                '''
            }
        }

        stage('Verify Rollout Status') {
            steps {
                sh 'kubectl --server="https://${K8S_NODE_IP}:6443" rollout status deployment/${APP_NAME} --timeout=120s'
            }
        }
    }

    post {
        success {
            // The IP is a Secret-text credential, so Jenkins masks it in this log line.
            echo "Deployment successful! HotDoc form UI: http://${K8S_NODE_IP}:30080"
        }
        failure {
            echo 'Pipeline failed. Check the Jenkins build logs for details.'
        }
    }
}
