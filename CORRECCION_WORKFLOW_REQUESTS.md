# Corrección del workflow de inventario

El inventario se generaba correctamente, pero la suite completa de pruebas
fallaba al importar scripts que dependen de `requests`.

## Reemplazar

```text
.github/workflows/generar-inventario.yml
```

El workflow corregido agrega:

```yaml
- name: Instalar dependencias
  run: |
    python -m pip install --upgrade pip
    python -m pip install requests
```

## Después de subirlo

Ejecutar nuevamente:

```text
Actions
-> Generar inventario operativo
-> Run workflow
```

La ejecución anterior falló antes del paso `Guardar inventario`, por lo que
es necesario volver a ejecutar el workflow completo.

Resultado esperado:

```text
Referencias de pronóstico únicas: 475
Estaciones únicas: 121
Consultas por actualización completa: 596
```

Después, ejecutar el workflow de descarga con:

```text
mode: stations
shard: 1
batch_size: 100
sleep_seconds: 1.5
```
