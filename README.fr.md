# docparse

*[English version](README.md)*

Transforme des **factures (PDF ou texte) en tableau**, contrôle chaque résultat par l'arithmétique, et **mesure honnêtement la précision** : combien de documents faux sont signalés « à vérifier », et combien passent sans bruit (les *erreurs silencieuses*).

> **Tous les documents de ce dépôt sont fictifs**, générés par `src/docparse/synth.py`. Les chiffres ci-dessous montrent la **méthode**, pas la performance sur de vrais documents : le générateur et l'extracteur ont été écrits par la même personne.

## Ce que ce projet démontre

| Compétence | Où la voir |
|---|---|
| **Extraction + contrôle** : chaque champ non reconnu reste vide au lieu d'être deviné, puis l'arithmétique (lignes, HT, TVA, total) est vérifiée | `rules.py`, `validate.py` |
| **Mesure de précision** : intervalles de Wilson à 95 %, erreurs silencieuses comptées à part, résultats par mise en page | `evaluate.py` |
| **Défauts trouvés par la mesure, puis corrigés** (voir plus bas) | `tests/` |
| **Configurable sans toucher au code** : ajouter ses libellés et noms de mois (`--rules`), couper certains contrôles (`--skip`), et le résultat rappelle les deux | `rules.py`, `validate.py`, `examples/` |
| **Interface pour un modèle de langage** : sa réponse passe par les mêmes contrôles ; testée avec un faux modèle | `llm.py` |
| **Qualité** : 165 tests ; modifications volontaires du code (« mutants ») toutes détectées : 15 sur le code d'origine, 37 sur 38 sur le code des options (la 38ᵉ n'a changé aucun résultat sur 20 000 cas aléatoires) | `tests/` |

## Démarrage

```bash
pip install -e ".[dev]"
pytest                                                    # 165 tests, quelques secondes
docparse run data/sample/invoices --out resultats.csv     # lit, contrôle, écrit un CSV (--delimiter ";" pour Excel en français)
docparse eval data/sample/invoices --truth data/sample/truth.json
docparse eval data/sample_noisy/invoices --truth data/sample_noisy/truth.json --suppliers data/sample/suppliers.txt
docparse rules                                            # libellés, mois, contrôles par défaut, et format du fichier --rules
```

`--suppliers` prend un fichier texte, un fournisseur par ligne : un nom absent de la liste est signalé.

## L'adapter à tes documents

L'extracteur lit un ensemble fixe de libellés. Sans toucher au code, tu peux **ajouter** des libellés et des noms de mois avec un petit fichier JSON (`docparse rules` affiche les valeurs par défaut et le format du fichier) :

```json
{
  "labels": {
    "total": ["net à payer", "montant dû"],
    "subtotal": ["base imposable"],
    "invoice_number": ["pièce"],
    "supplier": ["raison sociale"],
    "due_date": ["date limite"]
  },
  "months": { "enero": 1, "märz": 3 }
}
```

```bash
docparse run factures/ --rules mes-regles.json
docparse eval factures/ --truth verite.json --rules mes-regles.json   # mesure ce que les règles changent, ne le suppose pas
docparse run factures/ --skip lines,lines-sum                         # factures sans tableau de lignes : on coupe ces deux contrôles
```

- Les libellés sont du texte simple, pas des expressions régulières. La casse et les espaces multiples sont indifférents ; un libellé doit commencer et finir par une lettre ou un chiffre. Pour les montants (total, HT), tes libellés sont essayés **avant** ceux d'origine : un « total » générique ne peut pas masquer ton « net à payer ».
- Les règles **ajoutent** seulement : on ne peut pas retirer un libellé par défaut.
- Une erreur dans le fichier (clé inconnue, champ inconnu, numéro de mois hors de 1–12, libellé trop long) est refusée avec un message qui désigne l'entrée fautive. Jamais ignorée en silence.
- `--skip` prend des noms de contrôles (`required`, `known-supplier`, `lines`, `date`, `line-amount`, `lines-sum`, `vat-total`, `vat-rate`, `vat-gap` ; un nom inconnu est une erreur). **Couper des contrôles a un coût, et le résultat le rappelle à chaque fois** : sur l'échantillon, couper `required` seul rend silencieuses 12 erreurs qui étaient signalées (les erreurs silencieuses passent de 2 à 14).
- Illustration : sur l'échantillon, `examples/rules.example.json` rend lisibles les 10 documents de la mise en page inconnue T3 (précision sur le HT et le total : de 50/60 et 48/60 à 60/60 et 58/60), mais ils restent signalés : leur fournisseur n'a pas de libellé, c'est simplement la première ligne. J'ai écrit ce fichier en regardant ces documents : il montre le mécanisme, il ne mesure pas à quel point de telles règles se transposent à d'autres documents.

## Résultats (60 factures fictives par jeu)

Trois mises en page : **T1** (français, €), **T2** (anglais, $) que l'extracteur connaît, et **T3** (libellés qu'il ne connaît pas : il doit s'abstenir et signaler). Avec une probabilité donnée (le « bruit »), un caractère est remplacé par un sosie (0↔O, 1↔l, 5↔S, 8↔B), comme le ferait un OCR approximatif. Les graines (7 et 11) ont été choisies avant de voir les résultats et n'ont jamais été changées. Le générateur a été modifié une fois après un premier essai (flux de bruit séparé du contenu, pour que les tests soient plus simples) : les chiffres ci-dessous sont ceux de la version finale du code.

| Jeu | Entièrement justes | Faux et signalés | Erreurs silencieuses |
|---|---|---|---|
| `sample`, bruit 15 %, sans liste de fournisseurs | 45/60 (75 %, IC [63 % ; 84 %]) | 13 | 2 (deux noms de fournisseur) |
| `sample`, avec la liste | 45/60 | 15 | 0 |
| `sample_noisy`, bruit 80 %, sans liste | 19/60 (32 %, IC [21 % ; 44 %]) | 36 | 5 (3 numéros de facture, 2 noms) |
| `sample_noisy`, avec la liste | 19/60 | 38 | 3 (3 numéros de facture) |

**Comment lire ces lignes.**

- Les documents en mise en page inconnue (T3) sont **tous** signalés et jamais faussement validés : avec les libellés d'origine, l'extracteur s'abstient.
- Les contrôles d'arithmétique attrapent les fautes de lecture qui touchent un montant. Ils **ne voient pas** une faute dans un nom ou un numéro de facture : c'est ce qui reste en erreurs silencieuses.
- La liste de fournisseurs connus en rattrape une partie (les noms), pas les numéros de facture.
- Aucune fausse alerte sur ces jeux : un document juste n'est jamais signalé à tort. Ce n'est pas une garantie sur de vrais documents.

## Défauts trouvés en construisant, et corrigés

1. **Montants préfixés par la devise** (`Subtotal: $1,234.50`) : l'évaluation a montré 0 facture anglaise juste sur 17. Corrigé, test de régression `test_currency_symbol_before_amount_regression`.
2. **Tolérance d'un centime** : `100.01 - 100.00` vaut `0.0100000000000051` en flottant, donc un écart d'exactement un centime était refusé. Corrigé par un arrondi à 6 décimales avant comparaison.
3. **Garde-fous inutiles retirés** : une expression régulière redondante et un test de type JSON inatteignable, découverts parce que leur suppression ne cassait aucun test.
4. **« Total H.T. » n'était jamais lu** : le libellé était suivi d'un `\b`, qui ne peut pas correspondre juste après un point. Découvert en vérifiant que chaque libellé affiché par `docparse rules` est vraiment lu ; corrigé, test `test_total_h_t_with_dots_is_read_as_subtotal`.

## Limites

- **Données fictives uniquement.** De vraies factures varient bien davantage : l'extracteur par règles ne lit que les mises en page qu'il connaît. Pour un client, la démarche est : prendre 20 de ses vraies factures, écrire la bonne réponse à la main, lancer `docparse eval`, et annoncer le taux mesuré, pas un taux espéré.
- **Pas d'OCR.** Un PDF scanné sans couche de texte est signalé « aucun texte lisible ».
- **Interface LLM non testée contre une vraie API** (tests avec un faux modèle). Envoyer des factures de clients à un service externe pose une question de protection des données à régler avec le client avant.
- Les libellés ajoutés sont du texte exact : une formulation qui varie vaut un libellé par formulation. Les règles ne lisent pas un champ sans libellé (un nom de fournisseur en première ligne, par exemple) : il reste vide et est signalé.
- Dates lues en `jj/mm/aaaa` (jamais `mm/jj`), montants à trois décimales non gérés, `1,234` lu comme mille deux cent trente-quatre.
- Testé en local sous Python 3.12 et 3.13 (syntaxe 3.10 vérifiée, non exécutée). Un workflow GitHub Actions (Python 3.10 et 3.12) a été ajouté au dernier commit ; son premier lancement n'avait pas été vérifié au moment de l'écriture.
- Les modifications volontaires du code (« mutants ») sont écrites à la main : 15 sur 15 détectées sur le code d'origine (non relancées depuis l'ajout des options) et 37 sur 38 sur le code des options ; la 38ᵉ n'a changé aucun résultat sur 20 000 cas aléatoires. Cela ne prouve pas l'absence de défauts.

## Structure

```
src/docparse/   schema · amounts · rules · validate · pdf · pipeline · evaluate · llm · synth · cli
tests/          165 tests (valeurs pivots figées dans test_pipeline_cli.py : si elles changent, ce README est à revoir)
examples/       rules.example.json (le fichier montré plus haut)
data/sample/    60 factures PDF fictives + truth.json + suppliers.txt
data/sample_noisy/   60 factures très bruitées + truth.json
scripts/make_sample.py   régénère les deux jeux (nécessite fpdf2 et une police Unicode à chasse fixe)
```

## Utiliser un modèle de langage

```python
from pathlib import Path
from docparse.llm import LLMExtractor
from docparse.pipeline import process

def complete(prompt: str) -> str:
    ...  # ton appel à l'API de ton choix, qui renvoie le texte de la réponse

results = process(Path("factures/"), extractor=LLMExtractor(complete))
for r in results:
    print(r.source, "à vérifier" if r.needs_review else "ok", r.issues)
```

## Licence

© 2026 Samuel Mateo. Tous droits réservés.

Le code et les données fictives sont publiés pour être lus et évalués. Sans accord écrit de l'auteur, ils ne peuvent être ni copiés, ni modifiés, ni redistribués.
