# climateproyectar

Repositorio paralelo para construir y validar el catálogo maestro de
localidades del proyecto meteorológico.

## Objetivo de esta primera etapa

Crear una única fuente de verdad antes de dividir localidades entre workers o
repositorios regionales.

El catálogo maestro conserva los identificadores usados por el sistema
anterior:

- `id`: ID operativo principal, equivalente a `smn_id_interno`.
- `forecast_reference_id`: segundo ID que se prueba cuando falla el ID propio.
- `forecast_candidate_ids`: orden exacto de consulta del pronóstico.
- `station_number`: número de la estación de observación.
- `smn_id`: identificador adicional del catálogo completo.

Todavía no se realizan consultas masivas de pronósticos.

## Fuentes

- Catálogo completo de 10.601 localidades.
- Catálogo actual de producción de `wilowsnets/clima-argentina`.
- 79 localidades enriquecidas manualmente.
- Observaciones iniciales de las bases antárticas.
- Verificaciones manuales confirmadas mediante el buscador geográfico del SMN.

## Archivos generados

- `docs/data/catalogo_maestro.json`
- `docs/data/informe_validacion.json`
- `docs/data/conflictos.json`

## Ejecución local

```bash
python -m venv .venv
```

En Linux o macOS:

```bash
source .venv/bin/activate
```

En Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Después:

```bash
pip install -r requirements.txt
python scripts/descargar_produccion.py
python scripts/construir_catalogo_maestro.py --require-production
python scripts/validar_catalogo_maestro.py
python -m unittest discover -s tests -v
```

## Ejecución en GitHub

1. Abrir la pestaña **Actions**.
2. Elegir **Construir catálogo maestro**.
3. Presionar **Run workflow**.
4. Esperar que todas las validaciones terminen correctamente.

El workflow descarga el catálogo actual del repositorio en producción, genera
el maestro y guarda los resultados mediante un commit automático.

## Regla de identidad

Nunca se fusiona una localidad solamente por nombre. La clave primaria es el
campo `id`. Provincia, departamento, nombre y coordenadas se utilizan como
controles secundarios.

## Próxima etapa

Después de validar el catálogo maestro se crearán:

1. El descubrimiento de IDs de pronóstico que responden.
2. La asignación de estaciones de observación.
3. La división entre `core` y `extended`.
4. La distribución regional entre workers.
