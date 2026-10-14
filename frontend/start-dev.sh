#!/bin/bash
# RAG TypeScript React App - Startup Script for Linux/macOS

echo -e "\033[94m========================================"
echo "RAG Document QA - TypeScript React App"
echo "========================================\033[0m"
echo ""

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo -e "\033[91m❌ Node.js is not installed!\033[0m"
    echo -e "\033[93mPlease install Node.js 18+ from https://nodejs.org\033[0m"
    exit 1
fi

NODE_VERSION=$(node --version)
echo -e "\033[92m✅ Node.js version: $NODE_VERSION\033[0m"

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "\033[96m📁 Working directory: $(pwd)\033[0m"
echo ""

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo -e "\033[93m📦 Installing dependencies...\033[0m"
    npm install
    if [ $? -ne 0 ]; then
        echo -e "\033[91m❌ Failed to install dependencies\033[0m"
        exit 1
    fi
    echo -e "\033[92m✅ Dependencies installed\033[0m"
else
    echo -e "\033[92m✅ Dependencies already installed\033[0m"
fi

echo ""
echo -e "\033[96m📋 Prerequisites:\033[0m"
echo "  • FastAPI backend running on http://127.0.0.1:8000"
echo "  • PostgreSQL with pgvector running on localhost:5432"
echo ""

# Check if backend is running
if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8000/docs" | grep -q "200"; then
    echo -e "\033[92m✅ FastAPI backend is running\033[0m"
else
    echo -e "\033[93m⚠️  FastAPI backend is not responding\033[0m"
    echo -e "\033[93m   Start it with: uvicorn app.main:app --reload\033[0m"
fi

echo ""
echo -e "\033[92m🚀 Starting development server...\033[0m"
echo -e "\033[90mPress Ctrl+C to stop\033[0m"
echo ""

npm run dev
