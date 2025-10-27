# Règles Copilot – VPS RAG

- Prioriser des dépendances légères et CPU-only ; refuser les bibliothèques GPU ou très gourmandes sans justification documentée.
- Préférer des algorithmes en O(n log n) ou mieux ; éviter les copies mémoire inutiles (utiliser générateurs/streaming quand c’est possible).
- Forcer l’usage de timeouts réseau ≤ 10 s et de retries bornés ; ne jamais ignorer les erreurs réseau.
- Ne jamais exposer de secrets (tokens, mots de passe) dans les logs ou surfaces utilisateur.
- Services applicatifs écoutent en loopback ; l’exposition externe se fait uniquement via Nginx + TLS.
- Respecter les limites RAM : ingestor ≤ 250 MiB en charge, UI ≤ 200 MiB au repos.
