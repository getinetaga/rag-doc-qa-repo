
pipeline {
    agent any
    environment { PYTHON_ENV = "venv" }
    stages {
        stage('Setup') {
            steps {
                sh 'python -m venv venv'
                sh './venv/bin/pip install --upgrade pip'
                sh './venv/bin/pip install -r requirements.txt'
            }
        }
        stage('Lint & Test') {
            steps {
                sh './venv/bin/pytest tests/ --maxfail=1 --disable-warnings'
            }
        }
        stage('Build Docker Image') {
            steps {
                sh 'docker build -t rag-doc-qa:latest .'
            }
        }
        stage('Deploy (Optional)') {
            steps { echo 'Deploy to server or cloud platform' }
        }
    }
    post {
        always { echo 'Pipeline finished.' }
        success { echo 'Build succeeded!' }
        failure { echo 'Build failed!' }
    }
}
