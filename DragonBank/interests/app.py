"""
DragonBank - Service de Calcul des Interets
============================================
Microservice independant charge de calculer et d'appliquer
les interets sur les comptes epargne de maniere periodique.

Fonctionnement general :
    1. Au demarrage, le service attend que la base de donnees soit accessible.
    2. Un premier calcul est effectue immediatement apres la connexion.
    3. Le calcul est ensuite repete a intervalle regulier (configurable).

Types de comptes traites :
    - Livret A       : taux configurable (3 % par cycle par defaut).
    - Assurance Vie  : taux configurable (2 % par cycle par defaut).

Toutes les operations sont atomiques (transaction SQL) et tracees dans
les tables interest_history et transactions pour la conformite et l'audit.

Variables d'environnement disponibles :
    DATABASE_URL               : URL de connexion PostgreSQL.
    INTEREST_RATE_LIVRET_A     : Taux d'interet pour le Livret A (ex : 0.03).
    INTEREST_RATE_ASSURANCE_VIE: Taux d'interet pour l'Assurance Vie (ex : 0.02).
    INTERVAL_SECONDS           : Duree entre deux cycles de calcul (ex : 86400 pour 24h).
    DB_RETRY_MAX               : Nombre maximum de tentatives de connexion a la DB.
    DB_RETRY_DELAY             : Delai en secondes entre deux tentatives de connexion.

Version : 3.0
"""

import os
import time
import decimal
import logging
from datetime import datetime
from datetime import timezone

import psycopg2
import psycopg2.extras


# ============================================================
# CONFIGURATION
# ============================================================

# URL de connexion a la base de donnees PostgreSQL.
def _get_secure_db_url():
    ext_url = os.environ.get('DATABASE_URL')
    if ext_url: return ext_url

    user = os.environ.get('POSTGRES_USER', 'dragonadmin')
    host = os.environ.get('POSTGRES_HOST', 'db')
    port = os.environ.get('POSTGRES_PORT', '5432')
    dbname = os.environ.get('POSTGRES_DB', 'dragonbank')
    
    password = 'dragonpass'
    secret_path = os.environ.get('POSTGRES_PASSWORD_FILE', '/run/secrets/db_password')
    if os.path.exists(secret_path):
        with open(secret_path, 'r') as f:
            password = f.read().strip()
            
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

URL_BASE_DE_DONNEES = _get_secure_db_url()

# Taux d'interet applique par cycle au Livret A.
# La valeur 0.03 correspond a 3 % par cycle d'execution.
TAUX_LIVRET_A = decimal.Decimal(os.environ.get('INTEREST_RATE_LIVRET_A', '0.03'))

# Taux d'interet applique par cycle a l'Assurance Vie.
# La valeur 0.02 correspond a 2 % par cycle d'execution.
TAUX_ASSURANCE_VIE = decimal.Decimal(os.environ.get('INTEREST_RATE_ASSURANCE_VIE', '0.02'))

# Duree en secondes entre deux cycles de calcul des interets.
# La valeur 86400 correspond a 24 heures.
INTERVALLE_SECONDES = int(os.environ.get('INTERVAL_SECONDS', '86400'))

# Nombre maximum de tentatives de connexion a la DB au demarrage.
TENTATIVES_CONNEXION_MAX = int(os.environ.get('DB_RETRY_MAX', '30'))

# Delai en secondes entre deux tentatives de connexion.
DELAI_ENTRE_TENTATIVES = int(os.environ.get('DB_RETRY_DELAY', '2'))

# Precision utilisee pour l'arrondi des interets calcules.
# Deux decimales correspondent a la precision centimale (euros et centimes).
PRECISION_ARRONDI = decimal.Decimal('0.01')

# Table associant chaque type de compte a son taux d'interet.
TAUX_PAR_TYPE = {
    'livret_a':      TAUX_LIVRET_A,
    'assurance_vie': TAUX_ASSURANCE_VIE,
}


# ============================================================
# CONFIGURATION DES JOURNAUX (LOGS)
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] interests - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Journaliseur dedie au service des interets.
journaliseur = logging.getLogger('dragonbank.interests')


# ============================================================
# UTILITAIRES - BASE DE DONNEES
# ============================================================

def creer_connexion():
    """
    Cree et retourne une connexion active a la base de donnees PostgreSQL.

    La connexion utilise RealDictCursor pour que les lignes de resultats
    soient renvoyees sous forme de dictionnaires (acces par nom de colonne).

    L'autocommit est desactive afin de gerer les transactions manuellement,
    ce qui est indispensable pour garantir l'atomicite des operations.

    Returns:
        psycopg2.connection: Connexion active avec autocommit desactive.

    Raises:
        psycopg2.OperationalError: Si la connexion a la base de donnees echoue.
    """
    connexion = psycopg2.connect(
        URL_BASE_DE_DONNEES,
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    connexion.autocommit = False
    return connexion


def attendre_base_de_donnees():
    """
    Attend que la base de donnees soit accessible avant de demarrer le service.

    En environnement Docker, le conteneur de base de donnees peut mettre
    plusieurs secondes a demarrer apres le conteneur du service.
    Cette fonction tente de se connecter a intervalle regulier jusqu'a ce
    que la connexion aboutisse ou que le nombre maximum de tentatives soit atteint.

    Returns:
        bool: True si la connexion a ete etablie, False si toutes les tentatives ont echoue.
    """
    journaliseur.info("Attente de la base de donnees...")

    for numero_tentative in range(1, TENTATIVES_CONNEXION_MAX + 1):
        try:
            connexion = creer_connexion()
            connexion.close()
            journaliseur.info("Connexion a la base de donnees etablie.")
            return True

        except psycopg2.OperationalError as erreur:
            journaliseur.warning(
                "Tentative %d/%d echouee : %s",
                numero_tentative, TENTATIVES_CONNEXION_MAX, str(erreur)
            )
            if numero_tentative < TENTATIVES_CONNEXION_MAX:
                time.sleep(DELAI_ENTRE_TENTATIVES)

    journaliseur.error(
        "Impossible de se connecter a la base de donnees apres %d tentatives.",
        TENTATIVES_CONNEXION_MAX
    )
    return False


# ============================================================
# LOGIQUE METIER - CALCUL DES INTERETS
# ============================================================

def calculer_interets():
    """
    Calcule et applique les interets sur tous les comptes epargne actifs.

    Pour chaque compte epargne (Livret A ou Assurance Vie) dont le solde
    est strictement positif, la fonction :

        1. Recupere le solde actuel et le taux applicable.
        2. Calcule le montant des interets : montant = solde x taux.
        3. Arrondit le montant au centime superieur (arrondi bancaire ROUND_HALF_UP).
        4. Met a jour le solde du compte dans la table accounts.
        5. Insere un enregistrement dans la table interest_history.
        6. Cree une transaction de type 'interets' pour la traçabilite.

    Toutes ces operations sont effectuees dans une seule transaction SQL
    afin de garantir l'atomicite (soit tout est valide, soit rien ne l'est).

    Returns:
        dict: Dictionnaire contenant :
            - 'comptes_traites' (int)  : Nombre de comptes ayant recu des interets.
            - 'total_interets' (float) : Somme totale des interets verses.
            - 'horodatage' (str)       : Date et heure du calcul au format ISO 8601.
    """
    horodatage = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    journaliseur.info("=" * 60)
    journaliseur.info("CALCUL DES INTERETS - %s", horodatage)
    journaliseur.info("=" * 60)

    connexion = creer_connexion()
    try:
        curseur = connexion.cursor()

        # -----------------------------------------------------------
        # Recuperation de tous les comptes epargne eligibles
        # (statut actif et solde strictement positif)
        # -----------------------------------------------------------
        curseur.execute(
            """
            SELECT id, user_id, account_number, account_type, balance, interest_rate
            FROM accounts
            WHERE status = 'active'
              AND account_type IN ('livret_a', 'assurance_vie')
              AND balance > 0
            ORDER BY account_type, account_number
            """
        )
        comptes = curseur.fetchall()

        if not comptes:
            journaliseur.info("Aucun compte epargne eligible au calcul des interets.")
            return {
                'comptes_traites': 0,
                'total_interets':  0.0,
                'horodatage':      horodatage
            }

        total_interets  = decimal.Decimal('0.00')
        comptes_traites = 0

        # -----------------------------------------------------------
        # Traitement de chaque compte eligible
        # -----------------------------------------------------------
        for compte in comptes:
            id_compte    = str(compte['id'])
            numero_compte = compte['account_number']
            type_compte  = compte['account_type']
            solde        = decimal.Decimal(str(compte['balance']))

            # Le taux stocke en base a la priorite sur la variable d'environnement.
            # Cela permet de personnaliser le taux par compte si necessaire.
            taux_stocke = decimal.Decimal(str(compte['interest_rate']))
            if taux_stocke > 0:
                taux = taux_stocke
            else:
                taux = TAUX_PAR_TYPE.get(type_compte, decimal.Decimal('0'))

            if taux <= 0:
                journaliseur.debug("Compte %s ignore (taux nul)", numero_compte)
                continue

            # Calcul des interets avec arrondi bancaire au centime
            montant_interets = (solde * taux).quantize(
                PRECISION_ARRONDI,
                rounding=decimal.ROUND_HALF_UP
            )

            if montant_interets <= 0:
                journaliseur.debug("Compte %s ignore (interets < 0.01 euro)", numero_compte)
                continue

            nouveau_solde = solde + montant_interets

            # Mise a jour du solde dans la table accounts
            curseur.execute(
                'UPDATE accounts SET balance = %s, updated_at = NOW() WHERE id = %s',
                (float(nouveau_solde), id_compte)
            )

            # Enregistrement dans l'historique des interets
            curseur.execute(
                """
                INSERT INTO interest_history
                    (account_id, amount, rate, balance_before, balance_after)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    id_compte,
                    float(montant_interets),
                    float(taux),
                    float(solde),
                    float(nouveau_solde)
                )
            )

            # Creation d'une transaction pour la traçabilite dans le releve de compte
            libelle = 'Interets ' + type_compte.replace('_', ' ').title()
            libelle = libelle + ' (' + '{:.2f}'.format(float(taux) * 100) + ' %/cycle)'

            curseur.execute(
                """
                INSERT INTO transactions
                    (to_account_id, transaction_type, amount, description, status, executed_at)
                VALUES (%s, 'interets', %s, %s, 'completed', NOW())
                """,
                (id_compte, float(montant_interets), libelle)
            )

            total_interets  = total_interets + montant_interets
            comptes_traites = comptes_traites + 1

            journaliseur.info(
                "  OK  %-20s (%s) : %10.2f euros -> %10.2f euros  (+%6.2f euros a %.2f %%)",
                numero_compte,
                type_compte,
                float(solde),
                float(nouveau_solde),
                float(montant_interets),
                float(taux) * 100
            )

        # Validation de toutes les operations en une seule transaction atomique
        connexion.commit()

        journaliseur.info("=" * 60)
        journaliseur.info(
            "Bilan : %d compte(s) traite(s), total verse : %.2f euros",
            comptes_traites, float(total_interets)
        )
        journaliseur.info("=" * 60)

        return {
            'comptes_traites': comptes_traites,
            'total_interets':  float(total_interets),
            'horodatage':      horodatage
        }

    except Exception as erreur:
        connexion.rollback()
        journaliseur.error("ERREUR lors du calcul des interets : %s", str(erreur), exc_info=True)
        return {'erreur': str(erreur)}

    finally:
        connexion.close()


# ============================================================
# BOUCLE PRINCIPALE DU SERVICE
# ============================================================

def lancer_planificateur():
    """
    Lance la boucle principale de calcul des interets.

    Un premier calcul est effectue immediatement au demarrage afin
    de verifier le bon fonctionnement du service et de ne pas attendre
    un cycle complet.

    Les calculs suivants sont espaces de INTERVALLE_SECONDES secondes.
    Si une erreur survient lors d'un calcul, elle est enregistree dans
    les journaux mais le service continue de fonctionner normalement.

    Cette boucle est infinie et ne se termine que lors de l'arret du conteneur.
    """
    journaliseur.info("Premier calcul des interets au demarrage...")
    calculer_interets()

    journaliseur.info(
        "Prochain calcul dans %d secondes (%dh %dmin)",
        INTERVALLE_SECONDES,
        INTERVALLE_SECONDES // 3600,
        (INTERVALLE_SECONDES % 3600) // 60
    )

    while True:
        time.sleep(INTERVALLE_SECONDES)
        calculer_interets()


# ============================================================
# POINT D'ENTREE
# ============================================================

def main():
    """
    Point d'entree principal du service de calcul des interets.

    Affiche la configuration active, attend que la base de donnees
    soit accessible, puis lance la boucle de planification.

    En cas d'echec de connexion a la base de donnees apres le nombre
    maximum de tentatives, le service s'arrete avec le code de sortie 1.
    """
    print("DragonBank - Service de Calcul des Interets v3.0")
    print("=" * 60)
    print("Taux Livret A       : " + '{:.2f}'.format(float(TAUX_LIVRET_A) * 100) + " % / cycle")
    print("Taux Assurance Vie  : " + '{:.2f}'.format(float(TAUX_ASSURANCE_VIE) * 100) + " % / cycle")
    print("Intervalle          : " + str(INTERVALLE_SECONDES) + " secondes")
    if '@' in URL_BASE_DE_DONNEES:
        hote = URL_BASE_DE_DONNEES.split('@')[1]
    else:
        hote = 'configuree'
    print("Base de donnees     : " + hote)
    print("=" * 60)

    # Attente de la disponibilite de la base de donnees
    connexion_etablie = attendre_base_de_donnees()
    if not connexion_etablie:
        journaliseur.critical("Arret du service : base de donnees inaccessible.")
        raise SystemExit(1)

    # Lancement de la boucle de calcul
    lancer_planificateur()


if __name__ == '__main__':
    main()
