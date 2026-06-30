# Fase 4A: respaldo histórico local antártico

Este parche agrega una tercera fuente para los pronósticos:

```text
1. API moderna
2. Endpoint histórico remoto
3. Respaldo histórico local oficial
```

## Reemplazar

```text
scripts/descargar_datos_operativos.py
.github/workflows/descargar-operativo.yml
```

## Agregar

```text
data/fuentes/pronosticos_historicos_antartida.json
tests/test_respaldo_historico_local.py
```

No borres los cachés existentes.

## Contenido inicial

El archivo local contiene:

```text
10806 Base Belgrano II
10811 Base Carlini
10814 Base Orcadas
10817 Base San Martín
10818 Base Marambio
```

Base Esperanza `10810` ya está guardada con estado `stale` en el caché del
shard 1. La próxima ejecución la copiará automáticamente al archivo local,
dejándolo con las seis referencias antárticas.

## Ejecutar shard 1

```text
Actions
→ Descargar datos operativos
→ Run workflow
```

Valores:

```text
mode: forecast
shard: 1
batch_size: 100
sleep_seconds: 3.0
```

## Resultado esperado

```text
forecast shard 1:
total: 238
success: 238
fresh: 234
stale: 4
errors: 0
pending: 0
```

El archivo:

```text
data/fuentes/pronosticos_historicos_antartida.json
```

debería pasar de `count: 5` a `count: 6`, incorporando automáticamente
Base Esperanza desde el caché existente.
