#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.common import Norm, deduplicate, load_json, utc_now, write_json  # noqa: E402
from lib.generic import GenericPortalConnector  # noqa: E402
from lib.elegis import ElegisConnector  # noqa: E402
from lib.http import HttpClient  # noqa: E402
from lib.sapl import SaplConnector  # noqa: E402

CONFIG_PATH = ROOT / "config" / "states.json"
CATALOG_DIR = ROOT / "docs" / "catalogos"
REPORT_DIR = ROOT / "docs" / "relatorios"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coleta catálogo jurídico de uma UF")
    parser.add_argument("--uf", required=True, help="Sigla da UF")
    parser.add_argument("--max-records", type=int, default=int(os.getenv("MAX_RECORDS_PER_STATE", "20000")))
    parser.add_argument("--max-listing-pages", type=int, default=int(os.getenv("MAX_LISTING_PAGES", "1000")))
    parser.add_argument("--allow-below-minimum", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    uf = args.uf.upper().strip()
    config = load_json(CONFIG_PATH)
    state = next((s for s in config["states"] if s["uf"] == uf), None)
    if not state:
        print(f"UF desconhecida: {uf}", file=sys.stderr)
        return 2

    path = CATALOG_DIR / f"{uf}.json"
    current = load_json(path, {}) or {}
    curated = [
        item
        for item in current.get("normas", [])
        if str(item.get("fonte_catalogo", "")).lower().startswith(("semente", "catálogo interno", "catalogo interno"))
    ]

    client = HttpClient()
    diagnostics: dict[str, object] = {
        "uf": uf,
        "estado": state["estado"],
        "strategy": state["strategy"],
        "started_at": utc_now(),
        "portal": state.get("portal", ""),
        "curated_seed_count": len(curated),
    }

    try:
        if state["strategy"] == "sapl":
            connector = SaplConnector(
                client=client,
                base_url=state["base_url"],
                uf=uf,
                legacy=bool(state.get("legacy")),
            )
            collected = connector.collect(max_records=args.max_records)
        elif state["strategy"] == "elegis":
            connector = ElegisConnector(
                client=client,
                base_url=state["base_url"],
                uf=uf,
            )
            collected = connector.collect(
                max_records=args.max_records,
                max_pages=int(state.get("max_pages", args.max_listing_pages)),
            )
        else:
            connector = GenericPortalConnector(
                client=client,
                uf=uf,
                portal=state["portal"],
                allowed_hosts=state.get("allowed_hosts", []),
                start_urls=state.get("start_urls", []),
                detail_patterns=state.get("detail_patterns", []),
                cc_queries=state.get("cc_queries", []),
                listing_patterns=state.get("listing_patterns", []),
                max_workers=int(state.get("max_workers", 4)),
            )
            collected = connector.collect(
                max_records=min(args.max_records, int(state.get("max_records", args.max_records))),
                max_listing_pages=int(state.get("max_listing_pages", args.max_listing_pages)),
            )

        norms = [Norm(**{k: v for k, v in item.items() if k in Norm.__dataclass_fields__}) for item in curated]
        norms.extend(collected)
        norms = deduplicate(norms)
        minimum = int(state.get("minimum_collected", state.get("minimum_records", config.get("minimum_records_default", 25))))
        collected_count = len(deduplicate(collected))

        catalog = {
            "schema_version": 3,
            "catalog_version": utc_now()[:10].replace("-", "."),
            "updated_at": utc_now(),
            "uf": uf,
            "estado": state["estado"],
            "lexml_slug": current.get("lexml_slug", state["estado"].lower()),
            "portal_oficial": state.get("portal", ""),
            "status": "atualizado" if collected_count >= minimum else "incompleto",
            "minimum_expected": minimum,
            "normas": [n.to_dict() for n in norms],
        }
        write_json(path, catalog)

        diagnostics.update(
            {
                "finished_at": utc_now(),
                "collected_count": collected_count,
                "seed_count": len(curated),
                "final_count": len(norms),
                "minimum_expected": minimum,
                "status": catalog["status"],
                "direct_html_count": sum(1 for n in norms if n.texto_direto),
                "external_document_count": sum(1 for n in norms if n.documento_externo),
            }
        )
        write_json(REPORT_DIR / f"{uf}.json", diagnostics)
        print(json.dumps(diagnostics, ensure_ascii=False, indent=2))

        if collected_count < minimum and not args.allow_below_minimum:
            print(
                f"ERRO: {uf} coletou {collected_count} normas reais; mínimo exigido: {minimum}; sementes preservadas: {len(curated)}",
                file=sys.stderr,
            )
            return 3
        return 0
    except Exception as exc:
        diagnostics.update(
            {
                "finished_at": utc_now(),
                "status": "erro",
                "error": repr(exc),
                "traceback": traceback.format_exc(),
            }
        )
        write_json(REPORT_DIR / f"{uf}.json", diagnostics)
        print(json.dumps(diagnostics, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
