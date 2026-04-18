#!/bin/sh
set -e

echo "Patching Kairos source files for dynamic embedding dimensions..."

/app/.venv/bin/python3 << 'PYEOF'
import os
dims = os.environ.get('VECTOR_STORE__DIMENSIONS', '1536')

# Patch embedding_client.py: 支持 LLM__EMBEDDING_MODEL 环境变量
ec_path = '/app/src/embedding_client.py'
ec = open(ec_path).read()
old_model = 'self.model = "openai/text-embedding-3-small"'
new_model = 'self.model = os.environ.get("LLM__EMBEDDING_MODEL", "openai/text-embedding-3-small")'
if old_model in ec and 'LLM__EMBEDDING_MODEL' not in ec:
    ec = ec.replace(old_model, new_model)
    if 'import os' not in ec[:300]:
        ec = 'import os\n' + ec
    open(ec_path, 'w').write(ec)
    print(f'Patched embedding model, now using: {os.environ.get("LLM__EMBEDDING_MODEL")}')
else:
    print(f'Already patched or pattern not found, model: {os.environ.get("LLM__EMBEDDING_MODEL")}')

# Patch embedding_client.py: output_dimensionality from env
old_dim = 'config={"output_dimensionality": 1536}'
new_dim = f'config={{"output_dimensionality": {dims}}}'
if old_dim in ec:
    ec = ec.replace(old_dim, new_dim)
    open(ec_path, 'w').write(ec)
    print(f'Patched output_dimensionality to {dims}')
else:
    print(f'output_dimensionality already patched or pattern not found')

# Patch models.py: Vector(1536) -> Vector(dims)
models_path = '/app/src/models.py'
models = open(models_path).read()
old_vec = 'Vector(1536)'
new_vec = f'Vector({dims})'
count = models.count(old_vec)
if count > 0:
    models = models.replace(old_vec, new_vec)
    open(models_path, 'w').write(models)
    print(f'Patched {count}x Vector(1536) -> Vector({dims})')
else:
    print(f'Vector(1536) not found in models.py')
PYEOF

echo "Running database migrations..."
/app/.venv/bin/python scripts/provision_db.py

echo "Starting API server..."
exec /app/.venv/bin/fastapi run --host 0.0.0.0 src/main.py
