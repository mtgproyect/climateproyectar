# Cómo subir esta base a GitHub

Repositorio de destino:

```text
https://github.com/mtgproyect/climateproyectar
```

## Opción sencilla desde la web

1. Descomprimir `climateproyectar_base.zip`.
2. Entrar al repositorio `climateproyectar`.
3. Presionar **Add file** → **Upload files**.
4. Arrastrar todo el contenido de la carpeta `climateproyectar_base`.
5. Verificar que se incluyan también las carpetas ocultas:
   `.github/workflows`.
6. En el mensaje del commit escribir:

```text
Crear base del catálogo maestro
```

7. Presionar **Commit changes**.

## Primera ejecución

Después de subir:

1. Ir a **Actions**.
2. Abrir **Construir catálogo maestro**.
3. Presionar **Run workflow**.
4. Volver a cargar la página y esperar el resultado.

El workflow actualizará el catálogo con las 297 localidades que actualmente
están en producción y conservará sus referencias operativas.
