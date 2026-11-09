"""Ligne de commande : ``docparse run``, ``docparse eval`` et ``docparse rules``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import pipeline
from . import rules as rules_module
from .evaluate import FIELDS, evaluate, wilson
from .validate import CHECKS, check_skip


def pct(x: float, digits: int = 0) -> str:
    return "—" if x != x else f"{x * 100:.{digits}f}".replace(".", ",") + " %"


def table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = lambda cells: "  " + "   ".join(c.ljust(widths[i]) if i < 2 else c.rjust(widths[i]) for i, c in enumerate(cells))
    return "\n".join([line(headers), "  " + "───".join("─" * w for w in widths), *map(line, rows)])


def _suppliers(args: argparse.Namespace):
    """Liste des fournisseurs connus : None si non demandée, False si le fichier est introuvable."""
    if not args.suppliers:
        return None
    path = Path(args.suppliers)
    if not path.is_file():
        print(f"Introuvable : {path}", file=sys.stderr)
        return False
    return pipeline.load_suppliers(path)


def _options(args: argparse.Namespace):
    """(fournisseurs, extracteur, contrôles ignorés), ou None si une option est invalide (message déjà affiché)."""
    suppliers = _suppliers(args)
    if suppliers is False:
        return None
    extractor = rules_module.extract
    if args.rules:
        path = Path(args.rules)
        if not path.is_file():
            print(f"Introuvable : {path}", file=sys.stderr)
            return None
        try:
            extractor = rules_module.extractor(rules_module.load_rules(path))
        except rules_module.RulesError as exc:
            print(f"Règles invalides ({path}) : {exc}", file=sys.stderr)
            return None
    try:
        skip = sorted(check_skip(args.skip))
    except ValueError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return None
    return suppliers, extractor, skip


def _options_note(args: argparse.Namespace, skip: list[str]) -> str:
    """Rappel affiché avec les résultats : ce qui a été changé par rapport aux règles et contrôles d'origine."""
    lines = []
    if args.rules:
        lines.append(f"Règles supplémentaires : {args.rules} (elles s'ajoutent aux libellés d'origine).")
    if skip:
        lines.append(
            f"Contrôles désactivés : {', '.join(skip)}. Ce qu'ils auraient signalé ne l'est pas : "
            "un document « non signalé » est donc moins fiable qu'avec tous les contrôles."
        )
    return "\n".join(lines)


def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"Introuvable : {root}", file=sys.stderr)
        return 1
    options = _options(args)
    if options is None:
        return 1
    suppliers, extractor, skip = options
    results = pipeline.process(root, extractor=extractor, known_suppliers=suppliers, skip=skip)
    if not results:
        print(f"Aucun document .pdf ou .txt dans {root}", file=sys.stderr)
        return 1
    rows = [[r.source, r.invoice.number or "—", f"{r.invoice.total:.2f}" if r.invoice.total is not None else "—", "OUI" if r.needs_review else "non"] for r in results]
    print(table(["Fichier", "Numéro", "Total", "À vérifier"], rows))
    flagged = sum(r.needs_review for r in results)
    print(f"\n{len(results)} document(s) lu(s), {flagged} à vérifier à la main.")
    note = _options_note(args, skip)
    if note:
        print(note)
    if args.out:
        pipeline.write_csv(results, Path(args.out), args.delimiter)
        print(f"Résultats écrits dans {args.out} (colonne « problemes » : le détail).")
    print("Rappel : un document non signalé n'est pas garanti juste ; voir « docparse eval » pour mesurer les erreurs silencieuses.")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    root, truth_path = Path(args.path), Path(args.truth)
    for path in (root, truth_path):
        if not path.exists():
            print(f"Introuvable : {path}", file=sys.stderr)
            return 1
    truth = json.loads(truth_path.read_text(encoding="utf-8"))["files"]
    options = _options(args)
    if options is None:
        return 1
    suppliers, extractor, skip = options
    ev = evaluate(pipeline.process(root, extractor=extractor, known_suppliers=suppliers, skip=skip), truth)
    if ev.documents == 0:
        print("Aucun document commun entre le dossier et le fichier de vérité.", file=sys.stderr)
        return 1
    print(f"Évaluation sur {ev.documents} documents (intervalles de Wilson à 95 %)")
    note = _options_note(args, skip)
    print(note + "\n" if note else "")
    rows = []
    for name in FIELDS:
        k = ev.field_correct[name]
        lo, hi = wilson(k, ev.documents)
        rows.append([name, f"{k}/{ev.documents}", pct(k / ev.documents), f"[{pct(lo)} ; {pct(hi)}]"])
    print(table(["Champ", "Justes", "Taux", "IC 95 %"], rows))
    o = ev.overall
    lo, hi = wilson(o.fully_correct, o.documents)
    print(f"\nDocuments entièrement justes : {o.fully_correct}/{o.documents} ({pct(o.fully_correct / o.documents)}, IC [{pct(lo)} ; {pct(hi)}])")
    if o.wrong:
        print(f"Documents faux : {o.wrong}, dont {o.flagged_wrong} signalés « à vérifier » et {o.silent_errors} ERREURS SILENCIEUSES")
    print(f"Fausses alertes (justes mais signalés) : {o.false_alarms}")
    print("\nPar mise en page :")
    print(table(["Modèle", "Docs", "Justes", "Faux signalés", "Silencieuses"],
                [[t, str(g.documents), str(g.fully_correct), str(g.flagged_wrong), str(g.silent_errors)] for t, g in ev.by_template.items()]))
    if ev.silent_error_files:
        print("\nErreurs silencieuses : " + ", ".join(ev.silent_error_files))
    if ev.not_in_truth or ev.not_processed:
        print(f"\nIgnorés : {len(ev.not_in_truth)} document(s) sans vérité, {len(ev.not_processed)} vérité(s) sans document.")
    print("\nLimite : sur des documents fictifs, ces chiffres mesurent la méthode, pas la performance sur de vrais documents.")
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    print("Libellés reconnus par défaut (tu peux en AJOUTER avec --rules, pas en retirer) :\n")
    print("\n".join(f"  {field:<15} {', '.join(labels)}" for field, labels in rules_module.DEFAULT_LABELS.items()))
    by_number: dict[int, list[str]] = {}
    for name, number in rules_module.MONTHS.items():
        by_number.setdefault(number, []).append(name)
    print("\nMois reconnus dans une date écrite « 5 octobre 2026 » :\n")
    print("\n".join(f"  {number:>2}  {', '.join(names)}" for number, names in sorted(by_number.items())))
    print("\nContrôles de cohérence (désactivables avec --skip nom1,nom2) :\n")
    print("\n".join(f"  {name:<15} {description}" for name, description in CHECKS))
    print("\nFichier de règles (JSON) à passer avec --rules ; seules les clés « labels » et « months » existent :\n")
    print(rules_module.EXAMPLE_TEXT.rstrip())
    print(
        "\nPour les montants, un libellé ajouté est essayé AVANT ceux d'origine (ton « net à payer » n'est pas masqué par « total »). "
        "Il s'écrit en toutes lettres, sans expression régulière ; la casse et les espaces multiples sont indifférents, "
        "et il doit commencer et finir par une lettre ou un chiffre. Un nom de mois ne contient que des lettres."
    )
    print(
        "Une clé inconnue ou une faute de frappe est refusée avec un message (jamais ignorée en silence). "
        "Les règles ne rendent pas une facture juste : « docparse eval » mesure toujours les erreurs silencieuses."
    )
    return 0


def _add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--suppliers", help="Fichier texte, un fournisseur par ligne : un nom absent de la liste est signalé")
    parser.add_argument("--rules", help="Fichier JSON de libellés et de mois à ajouter aux règles d'origine (voir « docparse rules »)")
    parser.add_argument(
        "--skip",
        default="",
        type=lambda text: [part.strip() for part in text.split(",") if part.strip()],
        help="Contrôles à ne pas faire, séparés par des virgules (liste : « docparse rules »)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docparse", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="Lit un dossier (ou un fichier) de factures et contrôle chaque résultat")
    r.add_argument("path")
    r.add_argument("--out", help="Écrit un CSV (lisible par Excel)")
    r.add_argument("--delimiter", default=",", help="Séparateur du CSV (« ; » pour Excel en français)")
    _add_options(r)
    r.set_defaults(func=cmd_run)
    e = sub.add_parser("eval", help="Compare les résultats à une vérité connue et compte les erreurs silencieuses")
    e.add_argument("path")
    e.add_argument("--truth", required=True)
    _add_options(e)
    e.set_defaults(func=cmd_eval)
    g = sub.add_parser("rules", help="Affiche les libellés, mois et contrôles par défaut, et le format du fichier --rules")
    g.set_defaults(func=cmd_rules)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
