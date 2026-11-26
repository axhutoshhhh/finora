# Finora — Local HTTP API Contracts (Phase 1)

All `/api/*` endpoints run strictly on `http://127.0.0.1:<ephemeral_port>` behind:
- `Host` validation (`127.0.0.1:<port>`)
- `Origin` / `Sec-Fetch-Site` validation
- `X-Finora-Token: <ephemeral_launch_token>` header authentication
- `Content-Type: application/json` for mutating (`POST`/`PUT`) requests
- `MAX_CONTENT_LENGTH = 65536` bytes

## 1. Public Health Probe
### `GET /health`
- **Auth**: None (internal launcher readiness probe).
- **Response (`200 OK`)**: `{"status": "ok"}` (never leaks paths, tokens, env vars, or financial figures).

## 2. Error Envelope
All errors return JSON:
```json
{
  "error": {
    "code": "validation_error",
    "message": "Amount must be greater than zero.",
    "field": "amount"
  }
}
```
Status codes: `400` / `422` validation, `401` missing/invalid launch token, `403` invalid Host/Origin/Fetch-Metadata, `404` missing resource/unknown route, `409` idempotency conflict, `413` payload too large, `415` wrong content-type, `500` unexpected internal error (sanitized, no stack trace).

## 3. Phase 1 Financial & Settings Endpoints

### `GET /api/overview?month=YYYY-MM`
Returns current total account balance (across non-archived accounts), selected-month income, expense, surplus/deficit, active month metadata, and recent transactions (default limit 8).

### `GET /api/transactions?limit=100&offset=0`
Returns chronological transactions (`tx_date DESC, id DESC`) with posting account, category name/slug/icon, formatted INR amount, minor units, and description.
- Query params: `limit` (`1..500`, default `100`), `offset` (`>= 0`, default `0`).
- Response (`200 OK`): `{"transactions": [...], "total_count": N, "limit": ..., "offset": ...}`.

### `POST /api/transactions`
Creates a single-posting `expense` or `income` transaction atomically.
- **Body**:
  ```json
  {
    "entry_type": "expense",
    "account_id": 1,
    "category_id": 1,
    "amount": "250.50",
    "tx_date": "2026-11-26",
    "description": "Lunch",
    "idempotency_key": "optional-uuid-v4"
  }
  ```
- **Responses**: `201 Created` with `{"transaction": {...}, "created": true}` (or `200 OK` with `{"transaction": {...}, "created": false}` if `idempotency_key` matches exact submission, or `409 Conflict` on conflicting reuse).

### `GET /api/categories?kind=expense|income`
Returns active (`is_archived = 0`) categories ordered by `sort_order` under `{"categories": [...]}`.

### `GET /api/accounts`
Returns active accounts (`Cash` in Phase 1) with authoritative `balance_minor` and `balance_formatted` under `{"accounts": [...]}`.

### `GET /api/settings`
Returns current settings (`appearance`: `system` | `light` | `dark`, `currency`: `INR`, `version`, `storage`: storage directory & database path info for user transparency inside the authenticated app).

### `PUT /api/settings/appearance`
Updates and persists `appearance` (`"system" | "light" | "dark"`). Returns `200 OK` with updated setting and informs desktop bridge if running in `pywebview`.
