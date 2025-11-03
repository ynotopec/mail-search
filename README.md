# Mail Search

Outil de recherche rapide dans des archives locales de messages Thunderbird. Le projet vise à fournir une interface capable de retrouver des courriels à partir de requêtes par mots-clés classiques ou d'une recherche sémantique plus avancée, tout en conservant le maximum de traitements en local.

## Objectifs
- **Réactivité** : offrir un temps de réponse minimal pour la recherche dans de grands volumes de messages archivés.
- **Respect de la confidentialité** : limiter les échanges vers l'extérieur et garder les données sur la machine locale.
- **Recherche hybride** : combiner des recherches lexicales traditionnelles et des techniques d'analyse sémantique.

## Contraintes
- Le fonctionnement doit rester majoritairement **hors ligne**.
- Les appels à des services LLM externes doivent être **réduits au strict nécessaire**.
- Compatible avec des archives **Thunderbird** stockées localement.

## Pistes techniques
1. **Indexation locale**
   - Utiliser un moteur d'indexation (ex. `whoosh`, `tantivy` ou `lunr`) pour les recherches par mots-clés.
   - Mettre en place un pipeline d'ingestion des fichiers mbox ou maildir fournis par Thunderbird.
2. **Recherche sémantique**
   - Générer des embeddings localement via des modèles légers (ex. `sentence-transformers` avec backend `onnx` ou `ggml`).
   - Stocker les vecteurs dans une base de données vectorielle locale (ex. `faiss`, `qdrant` en mode self-hosted`).
   - N'utiliser un LLM externe que pour des tâches impossibles à réaliser localement.
3. **Interface utilisateur**
   - Proposer une interface CLI pour débuter.
   - Évoluer vers une interface web légère (ex. `FastAPI` + `Svelte` ou `React`) si nécessaire.

## Plan de travail suggéré
1. **Analyse des archives** : identifier la structure des dossiers Thunderbird à traiter.
2. **Ingestion & indexation** : parser les messages et alimenter l'index lexical + vectoriel.
3. **Moteur de recherche** : implémenter les requêtes combinant mots-clés et similarité sémantique.
4. **Interface** : fournir un MVP CLI permettant de lancer des requêtes et d'afficher les résultats.
5. **Optimisation** : surveiller la latence, la consommation mémoire et la précision des résultats.

## Ressources complémentaires
- [Thunderbird: Exporting emails](https://support.mozilla.org/fr/kb/exporter-sauvegarder-messages) pour obtenir les fichiers d'archives.
- [Sentence Transformers](https://www.sbert.net/) pour les modèles d'embeddings.
- [FAISS](https://github.com/facebookresearch/faiss) ou [Qdrant](https://qdrant.tech/) pour la recherche vectorielle.

## Licence
À définir selon les besoins du projet.
