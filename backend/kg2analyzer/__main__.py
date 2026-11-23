"""Command line: uv run kg2analyzer {build,serve,ask}.

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

    s = sub.add_parser("serve", help="start the web UI + API")
    _kg_args(s, required=False)
    s.add_argument("--mdkgs", nargs="*", metavar="PATH", help="saved MDKG files/folders/zips to preload into Query and Ask")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    a = sub.add_parser("ask", help="ask one question over saved MDKGs (--mdkgs) or raw KGs (--kgs)")
    a.add_argument("question")
    _kg_args(a, required=False)
    a.add_argument("--mdkgs", nargs="*", metavar="PATH", help="saved MDKG files/folders/zips")
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

        if args.kgs:  # raw KGs -> the Build section
            server.WORKSPACES["build"].ingest_paths(args.kgs, auto_link=not args.no_link, link_threshold=args.threshold,
                                                    max_facts=args.max_facts)
            print(_summary(server.WORKSPACES["build"].last_report), file=sys.stderr)
        if args.mdkgs:  # saved MDKGs -> the Query and Ask sections
            from kg2analyzer.ingest import read_paths

            for ws in ("query", "ask"):
                rep = server.WORKSPACES[ws].load_mdkgs(read_paths(args.mdkgs), auto_link=not args.no_link,
                                                       link_threshold=args.threshold)
            print(f"loaded {len(rep['mdkgs'])} MDKG(s) into Query and Ask", file=sys.stderr)
        uvicorn.run(server.app, host=args.host, port=args.port)
    elif args.cmd == "ask":
        if args.mdkgs:
            from kg2analyzer.analyzer import KG2Analyzer
            from kg2analyzer.ingest import read_paths

            az = KG2Analyzer()
            az.load_mdkgs(read_paths(args.mdkgs), auto_link=not args.no_link, link_threshold=args.threshold)
        elif args.kgs:
            az, _ = _build(args.kgs, args)
        else:
            p.error("ask needs --mdkgs PATH [PATH ...] (or --kgs to build first)")
        print(json.dumps(az.ask(args.question).to_dict(), indent=1, default=str))


if __name__ == "__main__":
    main()
