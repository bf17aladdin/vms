# Falcon AI Vision Infra Stack

This project now supports:
- Load balancing (Nginx)
- Microservice split (API + AI service)
- Multi-GPU ready deployment
- Cluster object storage (MinIO distributed)
- Monitoring (Prometheus + Grafana + exporters)

## 1) Base stack (single API service)

```bash
docker compose up -d --build
```

Endpoints:
- API: `http://localhost:5003`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## 2) Load balancing + microservices

This mode enables:
- `app` + `app_2` for API load balancing
- `ai_service` for AI routes
- `nginx` as gateway/LB on port `5003`

```bash
docker compose -f docker-compose.yml -f docker-compose.scaling.yml up -d --build
```

Health checks:
- LB health: `http://localhost:5003/health`
- WebSocket: `ws://localhost:5003/api/ws`

## 3) Multi-GPU mode

Enable optional GPU AI worker:

```bash
docker compose -f docker-compose.yml -f docker-compose.scaling.yml --profile gpu up -d --build
```

Set GPU device via env:
- `AI_DEVICE=cuda:0`
- `AI_GPU_DEVICE=cuda:1`
- `NVIDIA_VISIBLE_DEVICES=all`

## 4) Cluster storage (distributed MinIO)

```bash
docker compose -f docker-compose.yml -f docker-compose.cluster-storage.yml up -d
```

Endpoints:
- S3 API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`

## 5) Monitoring targets

Prometheus scrapes:
- FastAPI metrics: `/metrics`
- `mysqld_exporter`
- `redis_exporter`
- `nginx_exporter`
- optional: `node_exporter`, `cadvisor` (Linux profile)

## 6) Suggested validation commands

```bash
docker compose ps
curl http://localhost:5003/health
curl http://localhost:5003/metrics
curl http://localhost:9090/-/healthy
curl http://localhost:9090/api/v1/targets
```
