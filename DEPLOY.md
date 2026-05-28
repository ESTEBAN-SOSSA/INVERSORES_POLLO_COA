# Despliegue en Producción — INVERSORES POLLO COA

## Servidor
- VPS Contabo: `217.77.10.85`
- Stack Portainer: `pollo-coa`

## Acceso API
```
GET http://217.77.10.85:8011/health
GET http://217.77.10.85:8011/api/v1/plants
GET http://217.77.10.85:8011/api/v1/inverters/{sn}/energy
Header: X-API-Key: EDEMCO_2026_GROWAT_INVERSORES
```

## Imágenes Docker
- API:     `pollo-coa-inversores-api:latest`  (Dockerfile.api)
- Scraper: `pollo-coa-inversores-scraper:latest`  (Dockerfile.scraper)
- DB:      `postgres:16-alpine`

## Variables de entorno requeridas
```
GROWATT_USER=<usuario growatt>
GROWATT_PASSWORD=<contraseña growatt>
DATABASE_URL=postgresql+psycopg2://...
API_KEY=EDEMCO_2026_GROWAT_INVERSORES
API_HOST=0.0.0.0
API_PORT=8001
HEADLESS=true
TZ=America/Bogota
```

## Arquitectura completa
Ver [INFRASTRUCTURE.md](../ARCHITECTURE.md) en el repo EDEMCO-X.
