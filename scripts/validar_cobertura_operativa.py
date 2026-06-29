from __future__ import annotations

from collections import Counter
from common import ROOT, as_int, load_json

MASTER_FILE = ROOT / "docs" / "data" / "catalogo_maestro.json"
DIRECT_FILE = ROOT / "data" / "fuentes" / "localidades_directas.json"
DIRECT_REPORT_FILE = ROOT / "docs" / "data" / "informe_incorporacion_directa.json"


def main() -> None:
    master = load_json(MASTER_FILE)
    direct = load_json(DIRECT_FILE)
    report = load_json(DIRECT_REPORT_FILE)
    locations = master.get("localities")
    if not isinstance(locations, list):
        raise RuntimeError("catalogo_maestro.json no contiene una lista válida.")

    without_station = [item.get("id") for item in locations if isinstance(item, dict) and as_int(item.get("station_number")) is None]
    without_forecast = [item.get("id") for item in locations if isinstance(item, dict) and as_int(item.get("forecast_reference_id")) is None]
    candidate_errors: list[int] = []
    stations: list[int] = []
    references: list[int] = []
    for item in locations:
        if not isinstance(item, dict):
            continue
        locality_id = as_int(item.get("id"))
        station = as_int(item.get("station_number"))
        reference = as_int(item.get("forecast_reference_id"))
        candidates = item.get("forecast_candidate_ids")
        if station is not None:
            stations.append(station)
        if reference is not None:
            references.append(reference)
        if locality_id is None or not isinstance(candidates, list) or not candidates or candidates[0] != locality_id or reference not in candidates:
            if locality_id is not None:
                candidate_errors.append(locality_id)

    problems: list[str] = []
    if len(locations) != 10601:
        problems.append(f"El catálogo tiene {len(locations)} localidades.")
    if without_station:
        problems.append(f"Hay {len(without_station)} localidades sin estación.")
    if without_forecast:
        problems.append(f"Hay {len(without_forecast)} localidades sin referencia.")
    if candidate_errors:
        problems.append(f"Hay {len(candidate_errors)} listas de candidatos inválidas.")
    if as_int(direct.get("count")) != 261 or as_int(report.get("accepted")) != 261:
        problems.append("La fuente directa no contiene 261 registros aceptados.")
    if as_int(report.get("rejected")) not in {0, None}:
        problems.append("La incorporación directa contiene rechazos.")
    if problems:
        raise RuntimeError(" ".join(problems))

    print("Cobertura operativa completa.")
    print(f"Localidades: {len(locations)}")
    print(f"Con estación: {len(locations)}")
    print(f"Con referencia de pronóstico: {len(locations)}")
    print(f"Estaciones únicas: {len(set(stations))}")
    print(f"Referencias únicas: {len(set(references))}")
    print(f"Máximo de localidades por estación: {max(Counter(stations).values())}")


if __name__ == "__main__":
    main()
