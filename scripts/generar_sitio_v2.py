from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_minified(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(serialized)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def slim_operational_record(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": record.get("status"),
        "fresh": bool(record.get("fresh")),
        "historical": bool(record.get("historical")),
        "data_source": record.get("data_source"),
        "fetched_at": record.get("fetched_at"),
        "payload": record.get("payload"),
    }
    if record.get("last_refresh_attempt_at") is not None:
        result["last_refresh_attempt_at"] = record.get(
            "last_refresh_attempt_at"
        )
    if record.get("last_refresh_error") is not None:
        result["last_refresh_error"] = record.get(
            "last_refresh_error"
        )
    return result


def build_web_publication(
    *,
    root: Path = ROOT,
    expect_localities: int = 10601,
    expect_forecasts: int = 475,
    expect_stations: int = 121,
) -> dict[str, Any]:
    source_dir = root / "docs" / "data" / "publicacion"
    output_dir = root / "docs" / "data" / "web"
    forecast_dir = output_dir / "pronosticos"

    source_manifest = load_json(source_dir / "manifiesto.json")
    localities_source = load_json(source_dir / "localidades.json")
    forecasts_source = load_json(source_dir / "pronosticos.json")
    stations_source = load_json(source_dir / "estaciones.json")

    localities = localities_source.get("records")
    forecasts = forecasts_source.get("records")
    stations = stations_source.get("records")
    if not isinstance(localities, dict):
        raise RuntimeError("localidades.json no contiene records válidos.")
    if not isinstance(forecasts, dict):
        raise RuntimeError("pronosticos.json no contiene records válidos.")
    if not isinstance(stations, dict):
        raise RuntimeError("estaciones.json no contiene records válidos.")

    if len(localities) != expect_localities:
        raise RuntimeError(
            f"Se encontraron {len(localities)} localidades; "
            f"se esperaban {expect_localities}."
        )
    if len(forecasts) != expect_forecasts:
        raise RuntimeError(
            f"Se encontraron {len(forecasts)} pronósticos; "
            f"se esperaban {expect_forecasts}."
        )
    if len(stations) != expect_stations:
        raise RuntimeError(
            f"Se encontraron {len(stations)} estaciones; "
            f"se esperaban {expect_stations}."
        )

    active_forecasts = {int(key) for key in forecasts}
    active_stations = {int(key) for key in stations}

    columns = [
        "id",
        "name",
        "department",
        "province",
        "type",
        "forecast_reference_id",
        "operational_station_number",
        "source_station_number",
        "station_name",
        "distance_km",
        "lat",
        "lon",
    ]
    rows: list[list[Any]] = []
    seen: set[int] = set()

    for raw_id, item in sorted(
        localities.items(),
        key=lambda pair: int(pair[0]),
    ):
        if not isinstance(item, dict):
            raise RuntimeError(f"Localidad inválida: {raw_id}.")
        locality_id = as_int(item.get("id"))
        forecast_id = as_int(item.get("forecast_reference_id"))
        station_id = as_int(item.get("operational_station_number"))
        if locality_id is None or locality_id != int(raw_id):
            raise RuntimeError(f"ID inconsistente en la localidad {raw_id}.")
        if locality_id in seen:
            raise RuntimeError(f"Localidad duplicada: {locality_id}.")
        seen.add(locality_id)
        if forecast_id not in active_forecasts:
            raise RuntimeError(
                f"La localidad {locality_id} apunta al pronóstico "
                f"inexistente {forecast_id}."
            )
        if station_id not in active_stations:
            raise RuntimeError(
                f"La localidad {locality_id} apunta a la estación "
                f"inexistente {station_id}."
            )
        coord = item.get("coord")
        if not isinstance(coord, dict):
            coord = {}
        rows.append(
            [
                locality_id,
                item.get("name"),
                item.get("department"),
                item.get("province"),
                item.get("type"),
                forecast_id,
                station_id,
                as_int(item.get("source_station_number")),
                item.get("station_name"),
                as_float(item.get("distance_km")),
                as_float(coord.get("lat")),
                as_float(coord.get("lon")),
            ]
        )

    generated_at = utc_now()
    output_dir.mkdir(parents=True, exist_ok=True)
    if forecast_dir.exists():
        shutil.rmtree(forecast_dir)
    forecast_dir.mkdir(parents=True, exist_ok=True)

    localities_path = output_dir / "localidades.min.json"
    stations_path = output_dir / "estaciones.min.json"

    write_json_minified(
        localities_path,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "columns": columns,
            "count": len(rows),
            "records": rows,
        },
    )

    station_records = {
        str(station_id): slim_operational_record(stations[str(station_id)])
        for station_id in sorted(active_stations)
    }
    write_json_minified(
        stations_path,
        {
            "schema_version": 1,
            "generated_at": generated_at,
            "count": len(station_records),
            "records": station_records,
        },
    )

    forecast_hash = hashlib.sha256()
    stale_forecasts: list[int] = []
    for forecast_id in sorted(active_forecasts):
        source_record = forecasts[str(forecast_id)]
        if not isinstance(source_record, dict):
            raise RuntimeError(f"Pronóstico inválido: {forecast_id}.")
        record = {
            "schema_version": 1,
            "generated_at": generated_at,
            "forecast_reference_id": forecast_id,
            **slim_operational_record(source_record),
        }
        if record["status"] not in {"success", "stale"}:
            raise RuntimeError(
                f"El pronóstico {forecast_id} no está resuelto."
            )
        if record["status"] == "stale":
            stale_forecasts.append(forecast_id)
        path = forecast_dir / f"{forecast_id}.json"
        write_json_minified(path, record)
        digest = sha256_file(path)
        forecast_hash.update(f"{forecast_id}:{digest}\n".encode("utf-8"))

    stale_stations = [
        station_id
        for station_id in sorted(active_stations)
        if station_records[str(station_id)].get("status") == "stale"
    ]

    manifest = {
        "schema_version": 1,
        "generated_at": generated_at,
        "source_publication_generated_at": source_manifest.get(
            "generated_at"
        ),
        "counts": {
            "localities": len(rows),
            "forecast_references": len(active_forecasts),
            "stations": len(active_stations),
            "fresh_forecasts": len(active_forecasts) - len(stale_forecasts),
            "stale_forecasts": len(stale_forecasts),
            "fresh_stations": len(active_stations) - len(stale_stations),
            "stale_stations": len(stale_stations),
        },
        "stale": {
            "forecast_reference_ids": stale_forecasts,
            "station_numbers": stale_stations,
        },
        "files": {
            "localities": {
                "path": "localidades.min.json",
                "bytes": localities_path.stat().st_size,
                "sha256": sha256_file(localities_path),
            },
            "stations": {
                "path": "estaciones.min.json",
                "bytes": stations_path.stat().st_size,
                "sha256": sha256_file(stations_path),
            },
            "forecasts": {
                "directory": "pronosticos",
                "count": len(active_forecasts),
                "combined_sha256": forecast_hash.hexdigest(),
            },
        },
        "validation": {
            "all_localities_mapped": True,
            "duplicate_locality_ids": False,
            "missing_forecasts": 0,
            "missing_stations": 0,
            "errors": 0,
        },
    }
    write_json_minified(output_dir / "manifiesto.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Genera la publicación compacta consumida por la interfaz V2."
        )
    )
    parser.add_argument("--expect-localities", type=int, default=10601)
    parser.add_argument("--expect-forecasts", type=int, default=475)
    parser.add_argument("--expect-stations", type=int, default=121)
    args = parser.parse_args()

    manifest = build_web_publication(
        expect_localities=args.expect_localities,
        expect_forecasts=args.expect_forecasts,
        expect_stations=args.expect_stations,
    )
    counts = manifest["counts"]
    print("Publicación web V2 generada correctamente.")
    print(f"Localidades: {counts['localities']}")
    print(f"Pronósticos: {counts['forecast_references']}")
    print(f"Estaciones: {counts['stations']}")
    print(
        "Pronósticos actuales/históricos: "
        f"{counts['fresh_forecasts']}/{counts['stale_forecasts']}"
    )


if __name__ == "__main__":
    main()
