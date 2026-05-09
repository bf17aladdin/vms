#!/usr/bin/env bash
# PHASE 4 - QUICK START SCRIPT (Linux/Mac)
# Run this to validate and start the system

echo "🚀 Phase 4: E2E Integration & Validation"
echo "=========================================="
echo ""

# Step 1: Validate
echo "1️⃣  Running pre-flight validation..."
python phase4_validate.py
if [ $? -ne 0 ]; then
    echo "❌ Validation failed. Please fix errors above."
    exit 1
fi

echo ""
echo "2️⃣  Starting FastAPI server..."
echo "   Opening: http://localhost:5003"
echo "   Client:  file:///path/to/phase4_client.html"
echo ""
echo "   Press Ctrl+C to stop the server"
echo ""

# Step 2: Start server
python -m uvicorn vms.backend.main:app --reload --host 0.0.0.0 --port 5003
