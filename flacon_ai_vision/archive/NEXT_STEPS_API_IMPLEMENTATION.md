# 🔗 Guia: Implementación de APIs Faltantes

## 📋 APIs Requeridas por el Frontend

El frontend React está buscando estos endpoints que aún no están implementados:

```javascript
// Errores encontrados en los logs del navegador:
❌ GET /api/dashboard/stats        → 404 (Not Found)
❌ GET /api/events/recent?limit=5  → 401 (Unauthorized)
❌ GET /api/system/stats           → 404 (Not Found)
❌ GET /api/auth/me                → 401 (Unauthorized)
❌ GET /api/cameras                → 401 (Unauthorized)
❌ GET /static/surveillance.css    → 404 (Not Found - ✅ FIXED)
```

---

## 🎯 Prioridad de Implementación

### 1️⃣ CRÍTICA: Autenticación
```
GET  /api/auth/me          - Get current user info
POST /api/auth/login       - Login endpoint
POST /api/auth/logout      - Logout endpoint
POST /api/auth/refresh     - Refresh token
```

**Por qué**: Todos los endpoints protegidos retornan 401 sin autenticación

### 2️⃣ ALTA: Dashboard
```
GET  /api/dashboard/stats  - Dashboard statistics
GET  /api/events/recent    - Recent events (last N)
GET  /api/system/stats     - System performance
```

**Por qué**: Componentes principales del frontend dependen de esto

### 3️⃣ ALTA: Recursos Base
```
GET  /api/cameras          - List all cameras
GET  /api/cameras/{id}     - Get camera details
POST /api/cameras          - Add new camera
PUT  /api/cameras/{id}     - Update camera
```

### 4️⃣ MEDIA: Alertas y Eventos
```
GET  /api/alerts           - Get active alerts
POST /api/alerts/{id}/acknowledge - Mark as read
GET  /api/events           - Get event history
```

---

## 🛠️ Estructura Actual de Routers

```
vms/backend/routers/
├── auth.py                 # ✅ Existe, necesita completarse
├── cameras.py              # ✅ Existe
├── events.py               # ✅ Existe
├── personnel.py            # ✅ Existe
├── vehicle_entries.py      # ✅ Existe
├── facial.py               # ✅ Existe
├── uploads.py              # ✅ Existe
├── ws.py                   # ✅ WebSocket alerts
├── alerts.py               # ✅ Alertas
├── test_camera.py          # ✅ Test endpoints
├── camera_pool_router.py   # ✅ Sprint 2
├── calibration_router.py   # ✅ Sprint 3
├── scenarios_router.py     # ✅ Sprint 4
├── realtime_router.py      # ✅ Sprint 5
├── reporting_router.py     # ✅ Sprint 7
├── admin_router.py         # ✅ Sprint 6
└── video.py                # ✅ Video recording
```

---

## 📝 Template para Implementar un Endpoint

### Estructura Estándar

```python
# vms/backend/routers/dashboard.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..schemas import DashboardStatsSchema
from .. import crud

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/stats", response_model=DashboardStatsSchema)
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get dashboard statistics"""
    try:
        stats = crud.get_dashboard_stats(db)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Añadir al main.py

```python
from .routers import dashboard

app.include_router(dashboard.router)
```

---

## 🔑 Solución de Autenticación (Prioritaria)

### 1. Crear endpoint /api/auth/login

```python
# vms/backend/routers/auth.py

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Login endpoint"""
    user = crud.authenticate_user(db, request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create JWT token
    token = create_access_token(data={"sub": user.username})
    
    return {
        "access_token": token,
        "user_id": user.id,
        "username": user.username
    }

@router.get("/me")
async def get_current_user_info(current_user = Depends(get_current_user)):
    """Get current user info"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role
    }
```

### 2. Implementar JWT (en core/security.py)

```python
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

# Environment: .env
# SECRET_KEY=your-secret-key-here-change-in-production
# ALGORITHM=HS256

def create_access_token(data: dict, expires_delta: timedelta = None):
    """Create JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.SECRET_KEY, 
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt

def verify_token(token: str):
    """Verify JWT token"""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except JWTError:
        return None
```

### 3. Dependency para autenticación

```python
# En auth.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthCredentials

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    """Get current authenticated user"""
    token = credentials.credentials
    username = verify_token(token)
    
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user
```

---

## 📊 Endpoints de Dashboard

```python
# vms/backend/routers/dashboard.py

@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Dashboard statistics"""
    return {
        "total_cameras": db.query(Camera).count(),
        "active_cameras": db.query(Camera).filter(Camera.status == "active").count(),
        "total_events": db.query(Event).count(),
        "events_today": db.query(Event).filter(
            Event.timestamp.date() == datetime.today().date()
        ).count(),
        "total_personnel": db.query(Personnel).count(),
        "vehicles_detected": db.query(VehicleEntry).filter(
            VehicleEntry.exit_time.is_(None)
        ).count(),
    }

@router.get("/events/recent")
async def get_recent_events(
    limit: int = 5,
    db: Session = Depends(get_db)
):
    """Recent events"""
    events = db.query(Event).order_by(
        Event.timestamp.desc()
    ).limit(limit).all()
    
    return [
        {
            "id": e.id,
            "type": e.type,
            "description": e.description,
            "timestamp": e.timestamp,
            "camera_id": e.camera_id,
        }
        for e in events
    ]

@router.get("/system/stats")
async def get_system_stats():
    """System performance stats"""
    import psutil
    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage('/').percent,
        "timestamp": datetime.now().isoformat(),
    }
```

---

## 🔌 Frontend Integration

### Ejemplo: Conectando React al API

```typescript
// vms/frontend/src/services/api.ts

import axios from 'axios';

const API_BASE = 'http://localhost:5003/api';

interface LoginCredentials {
  username: string;
  password: string;
}

export const authService = {
  login: async (credentials: LoginCredentials) => {
    const response = await axios.post(`${API_BASE}/auth/login`, credentials);
    localStorage.setItem('token', response.data.access_token);
    return response.data;
  },
  
  getCurrentUser: async () => {
    const token = localStorage.getItem('token');
    const response = await axios.get(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    return response.data;
  }
};

export const dashboardService = {
  getStats: async () => {
    const token = localStorage.getItem('token');
    const response = await axios.get(`${API_BASE}/dashboard/stats`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    return response.data;
  }
};
```

---

## ✅ Checklist de Implementación

- [ ] Crear router de autenticación completo
- [ ] Implementar JWT tokens
- [ ] Crear schemas Pydantic para responses
- [ ] Implementar CRUD en models para dashboard
- [ ] Crear endpoint /dashboard/stats
- [ ] Crear endpoint /dashboard/events/recent
- [ ] Crear endpoint /system/stats
- [ ] Agregar logging
- [ ] Crear tests unitarios
- [ ] Documentar en Swagger
- [ ] Conectar frontend a APIs
- [ ] Probar flujo completo

---

## 🚀 Próximos Pasos

1. **Hoy**: Implementar autenticación JWT
2. **Mañana**: Endpoints de dashboard
3. **Semana**: Integración React-API
4. **Semana 2**: Formularios y validaciones
5. **Semana 3**: Features avanzadas (alertas, reportes)

---

## 📚 Recursos

- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [JWT en Python](https://python-jose.readthedocs.io/)
- [Axios en React](https://axios-http.com/)
- [React Query](https://tanstack.com/query/latest)

---

**Ready to implement! 🚀**
