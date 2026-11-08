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
| **Interface pour un modèle de langage** : sa réponse passe par les mêmes contrôles ; testée avec un faux modèle | `llm.py` |
| **Qualité** : 95 tests, 15 modifications volontaires du code toutes détectées | `tests/` |

## Démarrage

```bash
pip install -e ".[dev]"
pytest                                                    # 95 tests, moins d'une seconde
docparse run data/sample/invoices --out resultats.csv     # lit, contrôle, écrit un CSV (--delimiter ";" pour Excel en français)
docparse eval data/sample/invoices --truth data/sample/truth.json
docparse eval data/sample_noisy/invoices --truth data/sample_noisy/truth.json --suppliers data/sample/suppliers.txt
```

`--suppliers` prend un fichier texte, un fournisseur par ligne : un nom absent de la liste est signalé.

## Résultats (60 factures fictives par jeu)

Trois mises en page : **T1** (français, €), **T2** (anglais, $) que l'extracteur connaît, et **T3** (libellés qu'il ne connaît pas : il doit s'abstenir et signaler). Avec une probabilité donnée (le « bruit »), un caractère est remplacé par un sosie (0↔O, 1↔l, 5↔S, 8↔B), comme le ferait un OCR approximatif. Les graines (7 et 11) ont été choisies avant de voir les résultats et n'ont jamais été changées. Le générateur a été modifié une fois après un premier essai (flux de bruit séparé du contenu, pour que les tests soient plus simples) : les chiffres ci-dessous sont ceux de la version finale du code.

| Jeu | Entièrement justes | Faux et signalés | Erreurs silencieuses |
|---|---|---|---|
| `sample`, bruit 15 %, sans liste de fournisseurs | 45/60 (75 %, IC [63 % ; 84 %]) | 13 | 2 (deux noms de fournisseur) |
| `sample`, avec la liste | 45/60 | 15 | 0 |
| `sample_noisy`, bruit 80 %, sans liste | 19/60 (32 %, IC [21 % ; 44 %]) | 36 | 5 (3 numéros de facture, 2 noms) |
| `sample_noisy`, avec la liste | 19/60 | 38 | 3 (3 numéros de facture) |

**Comment lire ces lignes.**

- Les documents en mise en page inconnue (T3) sont **tous** signalés et jamais faussement validés : l'extracteur s'abstient.
- Les contrôles d'arithmétique attrapent les fautes de lecture qui touchent un montant. Ils **ne voient pas** une faute dans un nom ou un numéro de facture : c'est ce qui reste en erreurs silencieuses.
- La liste de fournisseurs connus en rattrape une partie (les noms), pas les numéros de facture.
- Aucune fausse alerte sur ces jeux : un document juste n'est jamais signalé à tort. Ce n'est pas une garantie sur de vrais documents.

## Défauts trouvés en construisant, et corrigés

1. **Montants préfixés par la devise** (`Subtotal: $1,234.50`) : l'évaluation a montré 0 facture anglaise juste sur 17. Corrigé, test de régression `test_currency_symbol_before_amount_regression`.
2. **Tolérance d'un centime** : `100.01 - 100.00` vaut `0.0100000000000051` en flottant, donc un écart d'exactement un centime était refusé. Corrigé par un arrondi à 6 décimales avant comparaison.
3. **Garde-fous inutiles retirés** : une expression régulière redondante et un test de type JSON inatteignable, découverts parce que leur suppression ne cassait aucun test.

## Limites

- **Données fictives uniquement.** De vraies factures varient bien davantage : l'extracteur par règles ne lit que les mises en page qu'il connaît. Pour un client, la démarche est : prendre 20 de ses vraies factures, écrire la bonne réponse à la main, lancer `docparse eval`, et annoncer le taux mesuré, pas un taux espéré.
- **Pas d'OCR.** Un PDF scanné sans couche de texte est signalé « aucun texte lisible ».
- **Interface LLM non testée contre une vraie API** (tests avec un faux modèle). Envoyer des factures de clients à un service externe pose une question de protection des données à régler avec le client avant.
- Dates lues en `jj/mm/aaaa` (jamais `mm/jj`), montants à trois décimales non gérés, `1,234` lu comme mille deux cent trente-quatre.
- Testé uniquement avec Python 3.13 ; aucune intégration continue exécutée.
- Les modifications volontaires du code (« mutants ») sont écrites à la main : 15 sur 15 détectées. Cela ne prouve pas l'absence de défauts.

## Structure

```
src/docparse/   schema · amounts · rules · validate · pdf · pipeline · evaluate · llm · synth · cli
tests/          95 tests (valeurs pivots figées dans test_pipeline_cli.py : si elles changent, ce README est à revoir)
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
