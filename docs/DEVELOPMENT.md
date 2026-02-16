# Development Workflow

## Local run

```bash
cp .env.example .env
./scripts/astra dev
```

Sources: `scripts/astra:266`, `scripts/astra:148`, `scripts/run.sh:128`, `scripts/run.sh:142`.

## Stop and logs

```bash
./scripts/astra stop
./scripts/astra logs
./scripts/astra logs api
./scripts/astra logs desktop
```

Sources: `scripts/astra:270`, `scripts/astra:276`, `scripts/astra:245`, `scripts/astra:248`.

## Quality gates

```bash
python3 -m pytest -q
npm --prefix apps/desktop run test
npm --prefix apps/desktop run lint
./scripts/doctor.sh prereq
./scripts/doctor.sh runtime
```

Sources: `apps/desktop/package.json:11`, `apps/desktop/package.json:12`, `apps/desktop/package.json:13`, `scripts/doctor.sh:12`.

## Useful scripts

- `./scripts/check.sh` — базовые проверки (`scripts/check.sh:1`).
- `./scripts/smoke.sh` — smoke flow (`scripts/smoke.sh:1`).
- `./scripts/models.sh install|verify|clean` — модели Ollama (`scripts/models.sh:1`).
- `python scripts/diag_addresses.py` — диагностика адресов/env/token (`scripts/diag_addresses.py:1`).

## Notes

- Desktop frontend требует явные `VITE_ASTRA_API_BASE_URL` и `VITE_ASTRA_BRIDGE_BASE_URL` (`apps/desktop/src/shared/api/config.ts:47`, `apps/desktop/src/shared/api/config.ts:55`).
- Startup scripts синхронизируют эти значения из `ASTRA_*` (`scripts/lib/address_config.sh:155`, `scripts/lib/address_config.sh:156`).
