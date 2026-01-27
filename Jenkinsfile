
// Declarative Jenkins pipeline updated for cross-platform compatibility
pipeline {
    agent any
    options {
        // Keep build logs concise and add timestamps
        timestamps()
        // Fail the build faster on long-running stalls
        timeout(time: 60, unit: 'MINUTES')
    }
    environment {
        PYTHON_ENV = "venv"
    }
    stages {
        stage('Setup') {
            steps {
                script {
                    if (isUnix()) {
                        sh 'python3 -m venv ${PYTHON_ENV} || python -m venv ${PYTHON_ENV}'
                        sh './${PYTHON_ENV}/bin/python -m pip install --upgrade pip'
                        sh './${PYTHON_ENV}/bin/pip install -r requirements.txt'
                    } else {
                        // Windows agent
                        bat 'python -m venv %PYTHON_ENV%'
                        bat '%PYTHON_ENV%\\Scripts\\python -m pip install --upgrade pip'
                        bat '%PYTHON_ENV%\\Scripts\\pip install -r requirements.txt'
                    }
                }
            }
        }

        stage('Lint & Test') {
            steps {
                script {
                    if (isUnix()) {
                        sh './${PYTHON_ENV}/bin/python -m pytest tests/ --maxfail=1 --disable-warnings'
                    } else {
                        bat '%PYTHON_ENV%\\Scripts\\python -m pytest tests/ --maxfail=1 --disable-warnings'
                    }
                }
            }
        }

        stage('Build Docker Image') {
            when {
                expression { return isUnix() || env.DOCKER_ON_WINDOWS == 'true' }
            }
            steps {
                script {
                    if (isUnix()) {
                        sh 'docker build -t rag-doc-qa:latest .'
                    } else {
                        bat 'docker build -t rag-doc-qa:latest .'
                    }
                }
            }
        }

        stage('Deploy (Optional)') {
            steps {
                echo 'Deployment is optional — implement your deployment steps here.'
            }
        }
    }
    post {
        always {
            echo 'Pipeline finished.'
        }
        success {
            echo 'Build succeeded!'
        }
        failure {
            echo 'Build failed!'
        }
    }
}
