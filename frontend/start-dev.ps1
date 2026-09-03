#!/usr/bin/env powershell
# RAG TypeScript React App - Startup Script for Windows

Write-Host "========================================" -ForegroundColor Blue
Write-Host "RAG Document QA - TypeScript React App" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue
Write-Host ""

# Check if Node.js is installed
$nodeVersion = node --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Node.js is not installed!" -ForegroundColor Red
    Write-Host "Please install Node.js 18+ from https://nodejs.org" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Node.js version: $nodeVersion" -ForegroundColor Green

# Navigate to UI directory
$uiPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $uiPath
Write-Host "📁 Working directory: $(Get-Location)" -ForegroundColor Cyan
Write-Host ""

# Check if node_modules exists
if (-not (Test-Path "node_modules")) {
    Write-Host "📦 Installing dependencies..." -ForegroundColor Yellow
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "✅ Dependencies already installed" -ForegroundColor Green
}

Write-Host ""
Write-Host "📋 Prerequisites:" -ForegroundColor Cyan
Write-Host "  • FastAPI backend running on http://127.0.0.1:8000" -ForegroundColor White
Write-Host "  • PostgreSQL with pgvector running on localhost:5432" -ForegroundColor White
Write-Host ""

# Check if backend is running
$backendCheck = (Invoke-WebRequest -Uri "http://127.0.0.1:8000/docs" -Method GET -ErrorAction SilentlyContinue).StatusCode
if ($backendCheck -eq 200) {
    Write-Host "✅ FastAPI backend is running" -ForegroundColor Green
} else {
    Write-Host "⚠️  FastAPI backend is not responding" -ForegroundColor Yellow
    Write-Host "   Start it with: uvicorn app.main:app --reload" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "🚀 Starting development server..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

npm run dev
