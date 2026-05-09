# Falcon AI Vision - Production Readiness Action Plan

## Overview
Quantified 8-week plan to transform prototype into production-ready system. Addresses all audit findings with corrected technical details.

**Total Effort**: 36 person-days (4.5 person-weeks)  
**Timeline**: 8 weeks (4 x 2-week sprints)  
**Priority**: Production blockers → Scaling → Quality

---

## Sprint 1: Production Readiness Foundation (2 weeks)
**Focus**: Fix blocking production issues  
**Effort**: 8 person-days

### 1. Database Migrations Baseline (2 days)
- **Impact**: High - Prevents deployment inconsistencies
- **Tasks**:
  - Generate initial migration for existing models
  - Set up migration versioning
  - Test migration rollback/upgrade cycle
- **Files**: `alembic/versions/`

### 2. Alert Persistence & Indexing (3 days)
- **Impact**: High - Eliminates data loss, enables reliable analytics
- **Tasks**:
  - Create Alert SQLAlchemy model with indexes on: `timestamp`, `severity`, `camera_id`, `rule_type`, `tenant_id`
  - Add `retention_days` config for automatic cleanup
  - Migrate AlertService from memory to DB
- **Files**: `alert_service.py`, create `models/alert.py`, migration

### 3. Database-Driven Alert Stats (1 day)
- **Impact**: High - Provides accurate 24h/7d/30d statistics
- **Tasks**:
  - Update `/api/alerts/stats` to query DB with optimized indexes
  - Add aggregation queries for dashboard
- **Files**: `alerts.py`

### 4. Secure CORS Configuration (2 days)
- **Impact**: High - Essential production security
- **Tasks**:
  - Replace `ALLOWED_ORIGINS = ["*"]` with environment-based allowlist
  - Add origin validation middleware
  - Support multiple environments (dev/prod)
- **Files**: `config.py`

---

## Sprint 2: Multi-Instance & Real-Time Scaling (2 weeks)
**Focus**: Enable horizontal scaling  
**Effort**: 11 person-days

### 5. Rules Configuration in Database (4 days)
- **Impact**: High - Enables multi-instance deployment
- **Tasks**:
  - Create Rule/Zone SQLAlchemy models
  - Migrate rule_engine_service to DB storage
  - Add local cache with 30s invalidation
  - Create API endpoints for rule management
- **Files**: `rule_engine_service.py`, create `models/rule.py`, `routers/rules.py`

### 6. Distributed Alert State with Pub/Sub (5 days)
- **Impact**: High - Supports load balancing
- **Tasks**:
  - Implement Redis pub/sub for alert distribution
  - Update RealtimeManager for shared state
  - Add alert deduplication across instances
  - DB as source of truth, Redis for real-time sync
- **Files**: `realtime_manager.py`, `alert_service.py`

### 7. Secure WebSocket Token Handling (2 days)
- **Impact**: Medium - Improves security without breaking browser compatibility
- **Tasks**:
  - Implement short-term tokens (5-15 min) with automatic rotation
  - Keep token in query param but add rotation/clean logging
  - Add token blacklist for logout/disconnect
- **Files**: `websocket.ts`, backend WS auth

---

## Sprint 3: Observability & Streaming Enhancements (2 weeks)
**Focus**: Reliability and monitoring  
**Effort**: 10 person-days

### 8. Basic Metrics & Health Monitoring (3 days)
- **Impact**: Medium - Enables production troubleshooting
- **Tasks**:
  - Add `/metrics` endpoint with Prometheus format
  - Track: API latency, AI processing time, alert rates per camera, WS connection count
  - Integrate basic health checks with thresholds
- **Files**: `config.py`, create `routers/metrics.py`

### 9. Enhanced Streaming Robustness (4 days)
- **Impact**: Medium - Improves video reliability
- **Tasks**:
  - Add 2-5 second ring buffer for multi-client support
  - Implement stream health monitoring with reconnect
  - Add process isolation indicators (no full refactor)
- **Files**: `stream_service.py`

### 10. Critical Flow End-to-End Tests (3 days)
- **Impact**: Low - Increases deployment confidence
- **Tasks**:
  - Test alert creation → DB storage → WS broadcast → frontend display
  - Test rule engine triggering with DB rules
  - Add streaming connection stability tests
- **Files**: Create `tests/e2e/`

---

## Sprint 4: Advanced Features & Polish (2 weeks)
**Focus**: Product quality enhancements  
**Effort**: 7 person-days

### 11. Fine-Grained Permissions (4 days)
- **Impact**: Medium - Enables role-based access control
- **Tasks**:
  - Add camera/zone permission models
  - Update RBAC system for granular access
  - Update frontend permission checks and UI
- **Files**: `rbac.py`, frontend permission hooks

### 12. Analytics Dashboard Enhancements (3 days)
- **Impact**: Low - Improves user experience
- **Tasks**:
  - Add 30-day trend views with DB queries
  - Implement alert distribution charts
  - Add CSV export functionality
- **Files**: Dashboard components, `alerts.py`

---

## Technical Dependencies
- **Redis**: Required for Sprint 2 distributed state
- **Monitoring Stack**: Prometheus + Grafana for Sprint 3
- **Database**: PostgreSQL recommended for production (indexes essential)

## Risk Mitigation
- **Testing**: Each sprint includes integration testing
- **Rollback**: Migrations enable safe rollbacks
- **Monitoring**: Metrics added early for issue detection

## Success Criteria
- **End of Sprint 1**: Zero data loss on restarts, secure CORS
- **End of Sprint 2**: Multi-instance deployment possible
- **End of Sprint 4**: Production-ready with monitoring and analytics

---

**Last Updated**: 2026-10-04  
**Based on Technical Audit**: All blocking issues addressed in Sprint 1