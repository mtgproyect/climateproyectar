from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from common import ROOT, as_float, as_int, clean_text, load_json, write_json_atomic

RESULTS_FILE = ROOT / "docs" / "data" / "pendientes_directos_resultados.json"
STATE_FILE = ROOT / "docs" / "data" / "estado_diagnostico_directo.json"
OUTPUT_FILE = ROOT / "data" / "fuentes" / "localidades_directas.json"
REPORT_FILE = ROOT / "docs" / "data" / "informe_incorporacion_directa.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_station_number(weather: dict[str, Any]) -> int | None:
    candidates = weather.get("station_candidates")
    if not isinstance(candidates, list):
        return None
    values: list[int] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        path = str(candidate.get("path") or "").strip().casefold()
        value = as_int(candidate.get("value"))
        if value is not None and (path == "station_id" or path.endswith(".station_id")):
            values.append(value)
    unique = sorted(set(values))
    return unique[0] if len(unique) == 1 else None


def location_from(probe: dict[str, Any], section: str) -> dict[str, Any]:
    payload = probe.get(section)
    if not isinstance(payload, dict):
        return {}
    location = payload.get("location")
    return location if isinstance(location, dict) else {}


def validate_result(item: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    issues: list[str] = []
    locality_id = as_int(item.get("id"))
    probe = item.get("direct_probe")
    if locality_id is None:
        return None, ["La localidad no tiene un ID entero."]
    if not isinstance(probe, dict):
        return None, ["La localidad no contiene direct_probe."]
    if probe.get("status") != "completed":
        issues.append("El diagnóstico no terminó con estado completed.")

    forecast = probe.get("forecast")
    weather = probe.get("weather")
    if not isinstance(forecast, dict) or not forecast.get("available"):
        issues.append("El pronóstico directo no está disponible.")
    if not isinstance(weather, dict) or not weather.get("available"):
        issues.append("El tiempo actual directo no está disponible.")

    forecast_location = location_from(probe, "forecast")
    weather_location = location_from(probe, "weather")
    if as_int(forecast_location.get("id")) != locality_id:
        issues.append("El pronóstico devolvió un ID diferente.")
    if as_int(weather_location.get("id")) != locality_id:
        issues.append("El tiempo actual devolvió un ID diferente.")

    station_number = extract_station_number(weather) if isinstance(weather, dict) else None
    if station_number is None:
        issues.append("No se encontró un station_id único.")
    distance_km = as_float(weather_location.get("distance"))
    if distance_km is None or distance_km < 0:
        issues.append("No se encontró una distancia válida a la estación.")

    if issues:
        return None, issues

    api_name = (
        clean_text(forecast_location.get("name"))
        or clean_text(weather_location.get("name"))
        or clean_text(item.get("name"))
    )
    return {
        "id": locality_id,
        "name": clean_text(item.get("name")),
        "api_name": api_name,
        "department": clean_text(forecast_location.get("department")) or clean_text(item.get("department")),
        "province": clean_text(forecast_location.get("province")) or clean_text(item.get("province")),
        "forecast_reference_id": locality_id,
        "station_number": station_number,
        "station_name": None,
        "distance_km": distance_km,
        "forecast_days_verified": as_int(forecast.get("days")),
        "forecast_verified": True,
        "weather_verified": True,
        "verified_at": clean_text(probe.get("tested_at")),
        "source": "SMN direct forecast and weather endpoints",
    }, []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    results_payload = load_json(RESULTS_FILE)
    state = load_json(STATE_FILE)
    items = results_payload.get("locations")
    if not isinstance(items, list):
        raise RuntimeError("pendientes_directos_resultados.json no contiene una lista válida.")

    records: dict[int, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record, issues = validate_result(item)
        locality_id = as_int(item.get("id"))
        if record is None:
            rejected.append({"id": locality_id, "name": item.get("name"), "issues": issues})
            continue
        records[int(record["id"])] = record

    duplicates = len(records) != len([item for item in items if isinstance(item, dict)])
    station_counts = Counter(int(record["station_number"]) for record in records.values())
    generated_at = utc_now()

    output = {
        "schema_version": 1,
        "source": "SMN direct forecast and weather endpoints",
        "generated_at": generated_at,
        "count": len(records),
        "locations": {str(i): records[i] for i in sorted(records)},
    }
    report = {
        "schema_version": 1,
        "generated_at": generated_at,
        "results_count": as_int(results_payload.get("count")),
        "diagnostic_state": {
            "unresolved_total": state.get("unresolved_total"),
            "directly_tested_total": state.get("directly_tested_total"),
            "forecast_available": state.get("forecast_available"),
            "weather_available": state.get("weather_available"),
            "forecast_and_weather_available": state.get("forecast_and_weather_available"),
        },
        "accepted": len(records),
        "rejected": len(rejected),
        "duplicate_ids": duplicates,
        "unique_stations": len(station_counts),
        "stations_used_by_multiple_localities": sum(count > 1 for count in station_counts.values()),
        "rejected_locations": rejected,
    }

    if args.require_complete:
        expected = 261
        problems: list[str] = []
        for field in ("unresolved_total", "directly_tested_total", "forecast_available", "weather_available", "forecast_and_weather_available"):
            if as_int(state.get(field)) != expected:
                problems.append(f"{field} no vale {expected}.")
        if as_int(results_payload.get("count")) != expected or len(items) != expected:
            problems.append("El archivo de resultados no contiene 261 localidades.")
        if len(records) != expected:
            problems.append(f"Solo se aceptaron {len(records)} de 261 localidades.")
        if rejected:
            problems.append(f"Hay {len(rejected)} resultados rechazados.")
        if duplicates:
            problems.append("Hay IDs duplicados en los resultados.")
        if problems:
            raise RuntimeError(" ".join(problems))

    write_json_atomic(OUTPUT_FILE, output)
    write_json_atomic(REPORT_FILE, report)
    print("Fuente directa generada correctamente.")
    print(f"Registros aceptados: {len(records)}")
    print(f"Registros rechazados: {len(rejected)}")
    print(f"Estaciones únicas entre los 261: {len(station_counts)}")


if __name__ == "__main__":
    main()
