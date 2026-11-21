"""Command line: uv run kg2analyzer {build,serve,ask,evaluate,benchmark}.

KG inputs (``build``, ``serve --kgs``, ``ask --kgs``) are any mix of RDF files, TBox/ABox pairs
(``x_tbox.ttl`` + ``x_abox.ttl``), one folder per KG, zip archives and owl:sameAs files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _kg_args(p: argparse.ArgumentParser, required: bool) -> None:
    p.add_argument("--kgs" if not required else "kgs", nargs="+" if required else "*", metavar="PATH",
                   help="KG files, folders or zips")
    p.add_argument("--no-link", action="store_true", help="do not discover owl:sameAs links between the KGs")
    p.add_argument("--threshold", type=float, default=0.6, help="auto-link score threshold (default 0.6)")
    p.add_argument("--max-facts", type=int, help="cap the fact cubes per KG")


def _summary(rep: dict) -> str:
    lines = [f"{'KG':<14}{'triples':>9}  {'tau*':>6}  fact cubes (observations, measures)"]
    for k in rep["kgs"]:
        cubes = ", ".join(f"{c['fact_class']} ({c['observations']}, {c['measures']})" for c in k["cubes"]) or "-"
        lines.append(f"{k['kg']:<14}{k['triples']:>9}  {k['otsu_threshold']:>6}  {cubes}")
    i = rep["identity"]
    lines.append(f"identity: {i['supplied_links']} supplied + {i['links_added']} discovered links "
                 f"-> {i['clusters']} entity clusters; {rep['named_graphs']} named graphs; {rep['seconds']['total']}s")
    return "\n".join(lines)


def _build(paths, args):
    from kg2analyzer.analyzer import KG2Analyzer

    az = KG2Analyzer()
    rep = az.ingest_paths(paths, auto_link=not args.no_link, link_threshold=args.threshold, max_facts=args.max_facts)
    print(_summary(rep), file=sys.stderr)
    return az, rep


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="kg2analyzer", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="KGs -> one MDKG per KG + identity graph, written to a folder")
    _kg_args(b, required=True)
    b.add_argument("--out", default="mdkg", help="output folder (default ./mdkg)")

    s = sub.add_parser("serve", help="start the web UI + API, optionally preloaded with your KGs")
    _kg_args(s, required=False)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--benchmark", choices=["enterprise", "northwind"], help="preload a generated benchmark instead")

    a = sub.add_parser("ask", help="ask one question over your KGs (or the enterprise benchmark)")
    a.add_argument("question")
    _kg_args(a, required=False)

    sub.add_parser("evaluate", help="reproduce the thesis result tables as JSON")
    bm = sub.add_parser("benchmark", help="write the generated benchmark KGs to a folder (example input)")
    bm.add_argument("--out", default="benchmark_kgs")
    args = p.parse_args(argv)

    if args.cmd == "build":
        az, rep = _build(args.kgs, args)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for kg in az.results:
            (out / f"{kg}.mdkg.trig").write_text(az.mdkg_trig(kg))
        (out / "identity.ttl").write_text(az.store.identity.serialize(format="turtle"))
        (out / "report.json").write_text(json.dumps(rep, indent=2, default=str))
        print(f"wrote {len(az.results)} MDKG(s), identity.ttl and report.json to {out}/", file=sys.stderr)
    elif args.cmd == "serve":
        import uvicorn

        from kg2analyzer import server

        if args.kgs:
            server.AZ.ingest_paths(args.kgs, auto_link=not args.no_link, link_threshold=args.threshold,
                                   max_facts=args.max_facts)
            print(_summary(server.AZ.last_report), file=sys.stderr)
        elif args.benchmark:
            server.AZ.load_benchmark(args.benchmark)
        uvicorn.run(server.app, host=args.host, port=args.port)
    elif args.cmd == "ask":
        if args.kgs:
            az, _ = _build(args.kgs, args)
        else:
            from kg2analyzer.analyzer import KG2Analyzer

            az = KG2Analyzer()
            az.load_benchmark()
        print(json.dumps(az.ask(args.question).to_dict(), indent=1, default=str))
    elif args.cmd == "evaluate":
        from kg2analyzer.benchmark.evaluate import main as ev

        ev()
    elif args.cmd == "benchmark":
        from kg2analyzer.benchmark.enterprise import build_enterprise_benchmark

        bmk = build_enterprise_benchmark()
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, g in bmk.graphs.items():
            (out / f"{name}.ttl").write_text(g.serialize(format="turtle"))
        print(f"wrote {len(bmk.graphs)} raw KGs to {out}/ (no identity links: build/serve will discover them)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
