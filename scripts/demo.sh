#!/usr/bin/env bash
set -e

echo "Building OpsPilot demo image..."
docker build -t opspilot:demo .

echo "Starting demo..."
docker compose -f docker-compose.demo.yml up -d

echo ""
echo "========================================"
echo "  OpsPilot Demo is starting up"
echo "========================================"
echo ""
echo "URL:      http://localhost:8443"
echo "Username: admin"
echo "Password: demo"
echo ""
echo "Demo scenarios:"
echo "  Tier 1: Auto-Run  (disk space — runs without confirmation)"
echo "  Tier 2: Confirm    (docker service — needs operator approval)"
echo "  Tier 3: Blocked    (memory pressure — blocked by safety guard)"
echo ""
echo "Logs:     docker compose -f docker-compose.demo.yml logs -f"
echo "Stop:     docker compose -f docker-compose.demo.yml down"
echo ""
