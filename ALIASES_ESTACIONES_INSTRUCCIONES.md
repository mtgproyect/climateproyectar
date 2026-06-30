# Corrección de alias de estaciones operativas

Los tres errores finales no son fallas de red. El endpoint actual del SMN
devuelve estas reasignaciones:

```text
87412 -> 87420  MENDOZA OBSERVATORIO
87470 -> 87360  RAFAELA AERO
87683 -> 87637  CORONEL SUAREZ AERO
```

Las estaciones de destino ya existen y ya tienen observaciones exitosas en
el caché. Por eso el inventario operativo debe agrupar 121 estaciones, no
124.

El catálogo maestro no se modifica. Conserva los números de estación
obtenidos de la fuente original. La resolución de alias se hace al generar
la capa operativa.

## Reemplazar

```text
scripts/generar_inventario_operativo.py
scripts/descargar_datos_operativos.py
.github/workflows/generar-inventario.yml
```

## Agregar

```text
tests/test_aliases_estaciones.py
```

No borres ninguno de los cachés existentes.

## Paso 1: regenerar inventario

Ejecutar:

```text
Actions
-> Generar inventario operativo
-> Run workflow
```

Resultado esperado:

```text
forecast references: 475
stations: 121
total operational keys: 596
```

Los grupos 87412, 87470 y 87683 desaparecerán como consultas separadas.
Sus localidades quedarán integradas en 87420, 87360 y 87637.

## Paso 2: recalcular el estado operativo

Ejecutar:

```text
Actions
-> Descargar datos operativos
-> Run workflow
```

Valores:

```text
mode: stations
shard: 1
batch_size: 100
sleep_seconds: 1.5
```

Como las 121 estaciones activas ya están en caché, se esperan cero
consultas nuevas.

Resultado final esperado:

```json
{
  "totals": {
    "query_keys": 596,
    "success": 596,
    "fresh": 590,
    "stale": 6,
    "errors": 0,
    "pending": 0
  }
}
```

La partición de estaciones debe quedar:

```json
{
  "mode": "stations",
  "shard": 1,
  "total": 121,
  "success": 121,
  "fresh": 121,
  "stale": 0,
  "errors": 0,
  "pending": 0
}
```

`docs/data/errores_descarga_operativa.json` debe quedar con `count: 0`.
Los registros antiguos pueden seguir físicamente dentro del caché, pero ya
no forman parte de las particiones operativas y no se informan como errores.
