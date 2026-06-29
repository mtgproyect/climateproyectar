# Fase 2C: completar las 10.601 localidades

Los 261 IDs pendientes ya tienen pronóstico y tiempo actual verificados. Este paquete convierte esos resultados en una fuente estable y completa el catálogo maestro.

## Reemplazar

```text
scripts/construir_catalogo_maestro.py
```

## Agregar

```text
scripts/incorporar_pendientes_directos.py
scripts/validar_cobertura_operativa.py
tests/test_incorporacion_directa.py
.github/workflows/incorporar-pendientes.yml
```

No borres:

```text
docs/data/pendientes_directos_resultados.json
docs/data/estado_diagnostico_directo.json
```

## Ejecutar

```text
Actions
→ Incorporar pendientes directos
→ Run workflow
```

No lleva parámetros y no vuelve a consultar los endpoints. Usa los resultados ya guardados.

## Resultado esperado

```text
Localidades: 10601
Con estación: 10601
Con referencia de pronóstico: 10601
Registros directos aceptados: 261
Registros rechazados: 0
```

`forecast_reference_id` se fija en el mismo `id` porque ese ID respondió con siete días de pronóstico. `station_number` se toma de `weather.station_id`. El nombre de la estación se completa cuando ese mismo número ya tiene un nombre único conocido; de lo contrario puede quedar en `null` sin impedir el uso operativo.
