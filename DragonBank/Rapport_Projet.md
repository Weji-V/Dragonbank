# 🐉 DragonBank - Rapport de Projet

## 1. Description du Projet et des Conteneurs (Dockers)
Le projet DragonBank repose sur une architecture en micro-services conteneurisée à l'aide de **Docker** et **Docker-Compose**. L'architecture comprend les 4 conteneurs suivants :

- **`db` (Postgres)** : Base de données relationnelle persistante contenant les schémas, les tables, les configurations et l'historique des opérations.
- **`backend` (Python/Flask)** : Le "cerveau" de l'application. Cette API RESTful gère toute la logique métier (authentification, gestion des comptes, validations de virements, audits) en utilisant une architecture saine (*Controllers/Services/DAOs*).
- **`frontend` (Python/Flask + Jinja2)** : L'interface utilisateur web. Elle agit comme un client qui appelle l'API via des requêtes HTTP JSON, et affiche les informations retournées dans une belle interface graphique dynamique propulsée par Bootstrap.
- **`interests` (Python)** : (Conteneur Bonus) Un conteneur "worker" autonome qui calcule et distribue le paiement asynchrone des intérêts journaliers applicables (+3% ou +2%) aux comptes d'épargne (Livret A, Assurance Vie), sans jamais nécessiter d'intervention humaine et sans bloquer l'API principale de la banque.

## 2. Fonctionnement de Chaque Application
- **Frontend** : L'utilisateur se connecte via `/login`. L'application authentifie l'utilisateur, récupère le token JWT de l'API et l'enregistre de manière sécurisée dans la session locale (`session` en base 64 et signée). L'interface requiert ce token pour toutes les vues protégées afin de communiquer avec l'API (tableaux de bord, liste des comptes, demande de virement interne ou de virement intra-partenaires extérieurs).
- **Backend API** : L'API intercepte les requêtes JSON. Elle vérifie l'intégrité de l'identité du client via le token JWT, et applique les règles de validations bancaires (fonds suffisants pour valider l'opération de virement, restrictions de l'IBAN bénéficiaire, etc.). La gestion transactionnelle de la base de données via nos services assure que l'architecture restera toujours consistante (propriétés ACID respectées).
- **Interests** : Service d'arrière-plan avec un timer. Ce module exécute le SQL pour récupérer les encours de l'épargne sur chaque client de DragonBank et génère un virement interne spécial pour matérialiser ce versement de profit au client de manière silencieuse.

## 3. Schéma de Base de données
Le modèle relationnel (cf. `db/init.sql`) a été pensé pour maximiser la sécurité et la traçabilité de toutes les opérations de la banque :
- Les tables fondamentales : **`users`** (les clients, avec la civilité et le mot de passe hashé), **`accounts`** (les comptes bancaires avec association au `user_id` et garantie par une contrainte de balance positive `>= 0`), **`beneficiaries`** (le carnet d'adresses bancaires d'un usager).
- La table **`transactions`** : L'historique immuable de chaque transfert d'argent (qui liste le `from_account`, `to_account`, et le type `virement_interne`, `externe` ou `interets`). 
- Les tables annexes de traçabilité : **`audit_logs`** et **`sessions`** enregistrent toutes les activités douteuses (tentatives d'authentifications répétées, de connexions par d'autres IP, et expiration stricte par token session).

## 4. Notions de Sécurité Implémentées
Pour garantir la fiabilité de cet environnement académique, de nombreuses couches sécuritaires ont été intégrées :
1. **Mots de passe Fortement Hachés** : Conservés côté base de données avec `bcrypt` en utilisant des sels d'entropie (pour se prémunir totalement contre les attaques Rainbow Tables).
2. **Système de Jetons JSON (JWT)** : Utilisés pour vérifier la validité des accès aux points d'API sans requérir le mot de passe sur les appels courants.
3. **Protection et Vérifications des Profils** : Toute intention de changer un e-mail principal ou un mot de passe bancaire (depuis le nouvel Onglet Profil) exigera nécessairement de produire son dernier mot de passe actuel en date. 
4. **Isolations Docker Secrets (Bonus)** : Pour empêcher la divulgation des identifiants Root de la Base de Données au sein des variables ou du code source, Postgres s'initialise au lancement en lisant le mot de passe confiné au sein d'un "Docker Secret" (`db_password.txt`).

## 5. Explication de l'implémentation Docker-Compose
Le fichier `docker-compose.yml` construit le réseau total de manière hermétique et orchestrée :
- **Networks (Cloisonnement)** : Un réseau de Frontend (`dragonbank-frontend-net`) et un réseau de Backend (`dragonbank-backend-net`). Ce bridage fait que le Frontend a le droit de discuter avec l'API, mais empêche physiquement le Frontend et potentiellement des attaques externes de ping la Base de Données directement.
- **Volumes** : Un volume permanent `postgres_data` permet un maintien et une persistance sans perte des transactions et liquidités de la banque même si le conteneur subit un crash inopiné ou une mise à jour.
- **Healthchecks (Bonus)** : La politique adoptée est "Fail Fast / Recover Quick". Les configurations Healthcheck imposent un ordre strict au démarrage absolu : l'interface Frontend s'interdira de démarrer et restera en pause tant que la route Health API de l'architecture Backend Python n'aura pas donné son aval (`curl -f /api/health`).
