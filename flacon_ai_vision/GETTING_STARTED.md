# 🚀 Falcon AI Vision - Getting Started

## ⚡ Quick Start (30 secondes)

### Windows Users
```bash
# Double-click this file:
run_complete.bat

# Then open browser:
http://localhost:5003/
```

### Manual Start
```bash
# 1. Activate virtual environment
.venv\Scripts\activate

# 2. Start server
python -m uvicorn vms.backend.main:app --reload --port 5003

# 3. Open browser
http://localhost:5003/
```

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| **START_HERE.md** | Complete setup guide |
| **QUICK_START.md** | Quick reference |
| **FRONTEND_COMPILATION_COMPLETE.md** | How frontend was built |
| **CORRECTIONS_SUMMARY.md** | Issues and fixes |
| **NEXT_STEPS_API_IMPLEMENTATION.md** | Adding new APIs |
| **DEPLOYMENT_COMPLETE.md** | Validation report |

---

## 🔗 Access Points

```
Main App:      http://localhost:5003/
API Docs:      http://localhost:5003/docs
Health Check:  http://localhost:5003/health
Admin:         http://localhost:5003/admin
User:          http://localhost:5003/user
```

---

## 🧪 Testing

```bash
# Quick test endpoints
python quick_test.py

# Test frontend assets
python test_asset_loading.py

# Test compiled frontend
python test_compiled_frontend.py
```

---

## 🛠️ Building Frontend

```bash
# Compile React/Vite frontend
build_frontend.bat

# Or Python:
python build_frontend.py
```

---

## ✅ Check Status

```bash
curl http://localhost:5003/health
```

Should return: `{"status":"ok",...}`

---

## 🆘 Troubleshooting

### Port 5003 in use?
Change PORT in `.env` or command line:
```bash
python -m uvicorn vms.backend.main:app --port 5004
```

### Frontend not loading?
```bash
build_frontend.bat
```

### Missing packages?
```bash
pip install -r requirements.txt
```

---

## 📖 Learn More

- **React docs**: https://react.dev/
- **FastAPI docs**: https://fastapi.tiangolo.com/
- **SQLAlchemy**: https://docs.sqlalchemy.org/
- **Tailwind CSS**: https://tailwindcss.com/

---

**Ready to develop! 🎉**
