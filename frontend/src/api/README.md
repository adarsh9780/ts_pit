# Frontend API Client

Generate the API client from backend OpenAPI:

```bash
npm run generate:api
```

This runs:

1. `generate:openapi`: exports `../openapi.yaml` from FastAPI
2. `generate:client`: generates JavaScript client code in `src/api/generated`

The generator is configured for JavaScript (`--js`) with Axios.
Type declaration files (`*.d.ts`) are removed automatically after generation.

Use `src/api/service.js` from UI code (friendly method names).
Keep `src/api/generated` as generated-only and avoid importing it directly in views/components.

Set backend URL with:

```bash
VITE_API_BASE_URL=http://localhost:8000
```
