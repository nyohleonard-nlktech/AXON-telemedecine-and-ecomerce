#!/bin/bash
# AxonForge Django Backend — Setup Script
# Run: bash setup.sh

echo "========================================"
echo "  AxonForge Backend Setup"
echo "========================================"

# 1. Install dependencies
echo ""
echo "[1/4] Installing dependencies..."
pip install -r requirements.txt

# 2. Migrations
echo ""
echo "[2/4] Setting up database..."
python manage.py makemigrations api
python manage.py migrate

# 3. Create media folder
echo ""
echo "[3/4] Creating media folder..."
mkdir -p media/profiles media/logos media/ids media/products

# 4. Start server
echo ""
echo "[4/4] Starting server..."
echo ""
echo "  ✅ Backend running at: http://127.0.0.1:8000"
echo "  ✅ API base URL:       http://127.0.0.1:8000/api"
echo "  ✅ Django admin:       http://127.0.0.1:8000/django-admin/"
echo ""
echo "  Open your index.html in a browser."
echo "  Make sure API = 'http://127.0.0.1:8000/api' in the JS."
echo ""
python manage.py runserver
