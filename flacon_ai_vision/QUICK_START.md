# 🔧 Falcon AI Vision - Quick Start Guide

## 📋 Requirements

- **Python** 3.9+
- **Node.js** 18+ (for frontend compilation)
- **npm** 9+
- **Virtual Environment** (venv)

---

## 🚀 Quick Start (Windows)

### Option 1: Complete Build & Run (Recommended)
```bash
# Double-click this file:
run_complete.bat

# Or from terminal:
cd "C:\Users\boufm\Desktop\eye_of_falcon"
run_complete.bat
```

This will:
1. ✅ Build the React/Vite frontend
2. ✅ Start the FastAPI backend
3. ✅ Open http://localhost:5003/

### Option 2: Manual Build & Run

#### Step 1: Build Frontend (if changed)
```bash
# Double-click:
build_frontend.bat

# Or manually:
cd vms/frontend
npm run build
cd ../..
```

#### Step 2: Start Backend
```bash
# Double-click:
start_server.bat

# Or manually:
.venv\Scripts\activate
python -m uvicorn vms.backend.main:app --reload --host 127.0.0.1 --port 5003
```

---

## 🌐 Access Points

Once the server is running:

| URL | Purpose |
|-----|---------|
| http://localhost:5003/ | **Main Application** (React Frontend) |
| http://localhost:5003/admin | Admin Dashboard |
| http://localhost:5003/user | User Dashboard |
| http://localhost:5003/docs | **API Documentation** (Swagger UI) |
| http://localhost:5003/redoc | Alternative API Docs (ReDoc) |
| http://localhost:5003/health | Health Check |

---

## 🔄 Development Workflow

### When Modifying Frontend Code
```bash
# 1. Frontend only (if just changing React code)
cd vms/frontend
npm run build           # Compile changes
cd ../..

# 2. Backend automatically reloads (--reload flag)
# Just refresh http://localhost:5003/ in browser
```

### When Adding New API Endpoints
```bash
# 1. Edit vms/backend/routers/your_router.py
# 2. Backend auto-reloads (watch mode)
# 3. Test in Swagger UI: http://localhost:5003/docs
```

### Full Development Setup
```bash
# Terminal 1: Frontend dev server with hot reload
cd vms/frontend
npm run dev              # Runs on http://localhost:3000

# Terminal 2: Backend API
cd vms
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 5003
```

---

## 📦 Project Structure

```
eye_of_falcon/
├── vms/
│   ├── backend/                    # FastAPI backend
│   │   ├── main.py                # Entry point
│   │   ├── core/
│   │   │   ├── config.py          # Configuration
│   │   │   ├── database.py        # Database setup
│   │   │   └── rbac.py            # Role-based access
│   │   ├── routers/               # API endpoints
│   │   ├── models/                # Database models
│   │   ├── schemas/               # Pydantic schemas
│   │   ├── services/              # Business logic
│   │   └── data/                  # SQLite database
│   │
│   ├── frontend/                   # React/Vite frontend
│   │   ├── dist/                  # 📦 COMPILED OUTPUT (served by backend)
│   │   │   ├── index.html         # Main entry point
│   │   │   └── assets/            # Minified CSS/JS
│   │   ├── src/                   # TypeScript/React source code
│   │   ├── admin/                 # Legacy admin pages
│   │   ├── user/                  # Legacy user pages
│   │   ├── templates/             # HTML templates
│   │   ├── static/                # Static assets
│   │   ├── package.json           # npm dependencies
│   │   └── vite.config.ts         # Vite configuration
│   │
│   ├── facial_recognition/        # Facial recognition module
│   └── vehicle_detection/         # Vehicle detection module
│
├── .venv/                         # Python virtual environment
├── build_frontend.bat             # Quick frontend build script
├── build_frontend.py              # Python build script
├── run_complete.bat               # Complete build & run
├── start_server.bat               # Just start backend
├── test_*.py                      # Test scripts
├── requirements.txt               # Python dependencies
└── README.md                      # This file
```

---

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Change port in .venv\Scripts\activate.bat or command line:
python -m uvicorn vms.backend.main:app --port 5005
# Then access: http://localhost:5005/
```

### Frontend Not Loading
```bash
# 1. Check if dist folder exists:
if not exist "vms\frontend\dist" (
    echo Frontend not built - run build_frontend.bat
)

# 2. Rebuild:
build_frontend.bat
```

### database Lock Error
```bash
# Delete the database and restart:
rmdir /s /q vms\backend\data
# Server will create a new empty database on startup
```

### npm Build Errors
```bash
# Clear npm cache:
npm cache clean --force

# Reinstall dependencies:
cd vms/frontend
rm node_modules
npm install
npm run build
```

---

## 📊 Testing

```bash
# Quick endpoint test
python quick_test.py

# Detailed frontend test
python test_compiled_frontend.py

# Test asset loading
python test_asset_loading.py

# Check configuration paths
python test_frontend_paths.py
```

---

## 🔐 Security Notes

- Default admin user: needs to be configured
- API uses CORS for localhost development
- HTTPS recommended for production
- Change JWT_SECRET_KEY before deploying

---

## 📚 Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Vite Documentation](https://vitejs.dev/)
- [React Documentation](https://react.dev/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)

---

## 🆘 Getting Help

1. Check the logs in the terminal where the server is running
2. Review API documentation: http://localhost:5003/docs
3. Check for error messages in the browser console (F12)
4. Review the configuration files in `vms/backend/core/`

---

## 🎯 Next Steps

1. ✅ Frontend is compiled and served
2. ⏭️ Set up user authentication
3. ⏭️ Connect frontend to API endpoints
4. ⏭️ Configure camera sources
5. ⏭️ Set up surveillance scenarios
6. ⏭️ Configure alerts and notifications

---

**Happy coding! 🚀**
