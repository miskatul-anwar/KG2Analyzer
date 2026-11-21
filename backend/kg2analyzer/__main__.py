"""Command line: uv run kg2analyzer {serve,evaluate,materialize,ask}."""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="kg2analyzer", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the web UI + API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--benchmark", choices=["enterprise", "northwind"], help="preload a benchmark")
    sub.add_parser("evaluate", help="reproduce the thesis result tables as JSON")
    m = sub.add_parser("materialize", help="run KG2MD on an RDF file and write QB4OLAP N-Quads")
    m.add_argument("file")
    m.add_argument("--name", default="kg")
    m.add_argument("--out", default="-")
    a = sub.add_parser("ask", help="ask a question over the enterprise benchmark")
    a.add_argument("question")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        from kg2analyzer import server

        if args.benchmark:
            server.AZ.load_benchmark(args.benchmark)
        uvicorn.run(server.app, host=args.host, port=args.port)
    elif args.cmd == "evaluate":
        from kg2analyzer.benchmark.evaluate import main as ev

        ev()
    elif args.cmd == "materialize":
        from kg2analyzer.analyzer import KG2Analyzer

        az = KG2Analyzer()
        az.load_kg(args.name, args.file)
        out = az.export_nquads()
        (sys.stdout.write(out) if args.out == "-" else open(args.out, "w").write(out))
        print(json.dumps(az.phase1_report(az.store and list(az.results)[0])["cubes"], indent=1, default=str)[:4000],
              file=sys.stderr)
    elif args.cmd == "ask":
        from kg2analyzer.analyzer import KG2Analyzer

        az = KG2Analyzer()
        az.load_benchmark()
        ans = az.ask(args.question)
        print(json.dumps(ans.to_dict(), indent=1, default=str))


if __name__ == "__main__":
    main()
