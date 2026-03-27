"""
DragonBank - Modele Compte Bancaire
=====================================
Classe DAO gerant toutes les operations en base de donnees
relatives aux comptes bancaires (courant, livret A, assurance vie).

Version : 3.0
"""

import uuid
import decimal
import logging

from database import serialiser_ligne, serialiser_lignes, enregistrer_audit
from config import TAUX_INTERETS, TYPES_COMPTE_UNIQUES

journaliseur = logging.getLogger('dragonbank.compte')


class CompteDAO:
    """
    Objet d'acces aux donnees pour la table accounts.

    Encapsule toutes les requetes SQL liees aux comptes bancaires
    et applique les regles metier (unicite du Livret A, validation
    du solde avant virement...).
    """

    # =========================================================
    # LECTURE
    # =========================================================

    def lister_par_utilisateur(self, connexion, id_utilisateur):
        """
        Retourne tous les comptes actifs d'un utilisateur.

        Args:
            connexion        : Connexion PostgreSQL active.
            id_utilisateur   : UUID de l'utilisateur.

        Returns:
            list[dict]: Liste des comptes tries par date de creation.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT id, account_number, account_type, balance, currency,
                   status, interest_rate, created_at
            FROM accounts
            WHERE user_id = %s AND status = 'active'
            ORDER BY created_at ASC
            """,
            (id_utilisateur,)
        )
        return serialiser_lignes(curseur.fetchall())

    def trouver_par_id(self, connexion, id_compte, id_utilisateur):
        """
        Recupere un compte par son UUID en verifiant la propriete.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_compte       : UUID du compte.
            id_utilisateur  : UUID du proprietaire attendu.

        Returns:
            dict : Donnees du compte.
            None : Si introuvable ou n'appartient pas a l'utilisateur.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT id, account_number, account_type, balance, currency,
                   status, interest_rate, created_at, updated_at
            FROM accounts
            WHERE id = %s AND user_id = %s
            """,
            (id_compte, id_utilisateur)
        )
        return serialiser_ligne(curseur.fetchone())

    def trouver_actif(self, connexion, id_compte, id_utilisateur):
        """
        Recupere un compte actif en verifiant la propriete.

        Utilise lors des virements pour s'assurer que le compte
        est actif (ni ferme ni gele) et appartient a l'utilisateur.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_compte       : UUID du compte.
            id_utilisateur  : UUID du proprietaire.

        Returns:
            dict : Donnees du compte actif.
            None : Si introuvable, inactif ou acces refuse.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT id, balance, account_number, account_type
            FROM accounts
            WHERE id = %s AND user_id = %s AND status = 'active'
            """,
            (id_compte, id_utilisateur)
        )
        return curseur.fetchone()

    def trouver_par_numero(self, connexion, numero_compte):
        """
        Recherche un compte actif par son numero de compte.

        Utilise lors des virements vers un beneficiaire pour trouver
        le compte destination a partir du numero enregistre.

        Args:
            connexion         : Connexion PostgreSQL active.
            numero_compte (str): Numero de compte (format DRGxxxxx).

        Returns:
            dict : Donnees du compte.
            None : Si introuvable ou inactif.
        """
        curseur = connexion.cursor()
        curseur.execute(
            "SELECT id FROM accounts WHERE account_number = %s AND status = 'active'",
            (numero_compte,)
        )
        return curseur.fetchone()

    # =========================================================
    # CREATION
    # =========================================================

    def ouvrir(self, connexion, id_utilisateur, type_compte, depot_initial=None):
        """
        Ouvre un nouveau compte bancaire.

        Applique les regles metier :
          - Unicite du Livret A et de l'Assurance Vie.
          - Enregistrement du depot initial comme transaction si > 0.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_utilisateur  : UUID de l'utilisateur.
            type_compte (str): 'courant', 'livret_a' ou 'assurance_vie'.
            depot_initial   : Montant en euros (Decimal ou None).

        Returns:
            dict: Les donnees du compte cree.

        Raises:
            ValueError: Si le type est invalide ou si un compte unique existe deja.
        """
        if type_compte not in TAUX_INTERETS:
            raise ValueError(
                "Type de compte invalide. Valeurs acceptees : "
                + ", ".join(TAUX_INTERETS.keys())
            )

        if type_compte in TYPES_COMPTE_UNIQUES:
            if self._existe_compte_unique(connexion, id_utilisateur, type_compte):
                raise ValueError("Vous possedez deja un compte " + type_compte)

        if depot_initial is None:
            depot_initial = decimal.Decimal('0.00')
            
        # Bonus d'ouverture de 100e uniquement pour le compte courant
        if type_compte == 'courant':
            depot_initial += decimal.Decimal('100.00')

        taux = float(TAUX_INTERETS[type_compte])
        numero = 'DRG' + str(uuid.uuid4().int)[:13].zfill(13)

        curseur = connexion.cursor()
        curseur.execute(
            """
            INSERT INTO accounts
                (user_id, account_number, account_type, balance, interest_rate)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, account_number, account_type, balance, interest_rate, created_at
            """,
            (id_utilisateur, numero, type_compte, float(depot_initial), taux)
        )
        compte = curseur.fetchone()

        # Enregistrement du depot initial et bonus comme transaction tracable
        if depot_initial > 0:
            description_depot = "Depot initial a l'ouverture du compte"
            if type_compte == 'courant':
                description_depot += " (incluant 100e de bonus)"

            curseur.execute(
                """
                INSERT INTO transactions
                    (to_account_id, transaction_type, amount, description, status, executed_at)
                VALUES (%s, 'depot', %s, %s, 'completed', NOW())
                """,
                (str(compte['id']), float(depot_initial), description_depot)
            )

        journaliseur.info("Compte %s ouvert pour l'utilisateur %s", type_compte, id_utilisateur)
        return serialiser_ligne(compte)

    # =========================================================
    # MISE A JOUR DU SOLDE
    # =========================================================

    def debiter(self, connexion, id_compte, montant):
        """
        Deduit un montant du solde d'un compte.

        Args:
            connexion  : Connexion PostgreSQL active.
            id_compte  : UUID du compte a debiter.
            montant    : Montant a deduire (Decimal ou float).
        """
        connexion.cursor().execute(
            'UPDATE accounts SET balance = balance - %s WHERE id = %s',
            (float(montant), id_compte)
        )

    def crediter(self, connexion, id_compte, montant):
        """
        Ajoute un montant au solde d'un compte.

        Args:
            connexion  : Connexion PostgreSQL active.
            id_compte  : UUID du compte a crediter.
            montant    : Montant a ajouter (Decimal ou float).
        """
        connexion.cursor().execute(
            'UPDATE accounts SET balance = balance + %s WHERE id = %s',
            (float(montant), id_compte)
        )

    # =========================================================
    # UTILITAIRES PRIVES
    # =========================================================

    def _existe_compte_unique(self, connexion, id_utilisateur, type_compte):
        """
        Verifie si l'utilisateur possede deja un compte du type donne.

        Methode privee (prefixe _) appelee avant l'ouverture
        d'un Livret A ou d'une Assurance Vie.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_utilisateur  : UUID de l'utilisateur.
            type_compte (str): Type de compte a verifier.

        Returns:
            bool: True si un compte actif de ce type existe deja.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT id FROM accounts
            WHERE user_id = %s AND account_type = %s AND status = 'active'
            """,
            (id_utilisateur, type_compte)
        )
        return curseur.fetchone() is not None
