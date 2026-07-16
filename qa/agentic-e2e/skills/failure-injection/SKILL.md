# Skill: Failure Injection

Applique un mode déclaré à l'adapter, la fixture ou l'environnement isolé. Chaque injection possède : `id`, `target`, `activation`, `expected_detection`, `cleanup`.

Le cleanup s'exécute dans un bloc final même si le scénario échoue. Une injection non prouvée rend le scénario `inconclusive`.
