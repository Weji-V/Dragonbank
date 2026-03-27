"""
DragonBank - Modele Beneficiaire
==================================
Classe DAO gerant les operations en base de donnees
relatives aux beneficiaires de virements.

Version : 3.0
"""

import logging

from database import serialiser_ligne, serialiser_lignes

journaliseur = logging.getLogger('dragonbank.beneficiaire')


class BeneficiaireDAO:
    """
    Objet d'acces aux donnees pour la table beneficiaries.

    Applique les regles metier :
      - Interdiction de s'ajouter soi-meme comme beneficiaire.
      - Unicite du numero de compte par utilisateur.
    """

    # =========================================================
    # LECTURE
    # =========================================================

    def lister_par_utilisateur(self, connexion, id_utilisateur):
        """
        Retourne tous les beneficiaires enregistres par un utilisateur.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_utilisateur  : UUID de l'utilisateur.

        Returns:
            list[dict]: Liste des beneficiaires tries alphabetiquement.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT id, beneficiary_name, bank_name, account_number,
                   iban, bic, status, created_at
            FROM beneficiaries
            WHERE user_id = %s
            ORDER BY beneficiary_name ASC
            """,
            (id_utilisateur,)
        )
        return serialiser_lignes(curseur.fetchall())

    def trouver_approuve(self, connexion, id_beneficiaire, id_utilisateur):
        """
        Recupere un beneficiaire approuve appartenant a l'utilisateur.

        Utilise lors des virements pour verifier que le beneficiaire
        est bien enregistre et approuve.

        Args:
            connexion          : Connexion PostgreSQL active.
            id_beneficiaire    : UUID du beneficiaire.
            id_utilisateur     : UUID de l'utilisateur proprietaire.

        Returns:
            dict : Donnees du beneficiaire.
            None : Si introuvable, non approuve ou acces refuse.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT id, beneficiary_name, account_number, bank_name
            FROM beneficiaries
            WHERE id = %s AND user_id = %s AND status = 'approved'
            """,
            (id_beneficiaire, id_utilisateur)
        )
        return curseur.fetchone()

    # =========================================================
    # CREATION
    # =========================================================

    def ajouter(self, connexion, id_utilisateur, nom, numero_compte,
                nom_banque='DragonBank', iban=None, bic=None):
        """
        Enregistre un nouveau beneficiaire.

        Verifie que l'utilisateur ne s'ajoute pas lui-meme
        et qu'il n'y a pas de doublon sur le numero de compte.

        Args:
            connexion          : Connexion PostgreSQL active.
            id_utilisateur     : UUID de l'utilisateur.
            nom (str)          : Nom du beneficiaire.
            numero_compte (str): Numero de compte du beneficiaire.
            nom_banque (str)   : Nom de la banque (defaut: DragonBank).
            iban (str)         : Code IBAN (optionnel).
            bic (str)          : Code BIC/SWIFT (optionnel).

        Returns:
            dict: Les donnees du beneficiaire cree.

        Raises:
            ValueError: Si auto-ajout ou doublon detecte.
        """
        # Interdiction de s'ajouter soi-meme
        if self._est_propre_compte(connexion, id_utilisateur, numero_compte):
            raise ValueError(
                "Vous ne pouvez pas vous ajouter vous-meme comme beneficiaire"
            )

        # Verification de l'absence de doublon
        if self._existe_deja(connexion, id_utilisateur, numero_compte):
            raise ValueError("Ce beneficiaire est deja enregistre")

        curseur = connexion.cursor()
        curseur.execute(
            """
            INSERT INTO beneficiaries
                (user_id, beneficiary_name, bank_name, account_number, iban, bic)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, beneficiary_name, bank_name, account_number,
                      iban, bic, status, created_at
            """,
            (id_utilisateur, nom, nom_banque, numero_compte,
             iban or None, bic or None)
        )
        journaliseur.info("Beneficiaire '%s' ajoute pour l'utilisateur %s", nom, id_utilisateur)
        return serialiser_ligne(curseur.fetchone())

    # =========================================================
    # SUPPRESSION
    # =========================================================

    def supprimer(self, connexion, id_beneficiaire, id_utilisateur):
        """
        Supprime un beneficiaire en verifiant la propriete.

        Args:
            connexion          : Connexion PostgreSQL active.
            id_beneficiaire    : UUID du beneficiaire.
            id_utilisateur     : UUID de l'utilisateur proprietaire.

        Returns:
            dict : Donnees du beneficiaire supprime (nom inclus).
            None : Si introuvable ou acces refuse.
        """
        curseur = connexion.cursor()
        curseur.execute(
            'DELETE FROM beneficiaries WHERE id = %s AND user_id = %s'
            ' RETURNING id, beneficiary_name',
            (id_beneficiaire, id_utilisateur)
        )
        return curseur.fetchone()

    # =========================================================
    # UTILITAIRES PRIVES
    # =========================================================

    def _est_propre_compte(self, connexion, id_utilisateur, numero_compte):
        """
        Verifie si le numero correspond a un compte de l'utilisateur.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_utilisateur  : UUID de l'utilisateur.
            numero_compte   : Numero a verifier.

        Returns:
            bool: True si c'est l'un de ses propres comptes.
        """
        curseur = connexion.cursor()
        curseur.execute(
            'SELECT id FROM accounts WHERE user_id = %s AND account_number = %s',
            (id_utilisateur, numero_compte)
        )
        return curseur.fetchone() is not None

    def _existe_deja(self, connexion, id_utilisateur, numero_compte):
        """
        Verifie si un beneficiaire avec ce numero est deja enregistre.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_utilisateur  : UUID de l'utilisateur.
            numero_compte   : Numero a verifier.

        Returns:
            bool: True si le beneficiaire existe deja.
        """
        curseur = connexion.cursor()
        curseur.execute(
            'SELECT id FROM beneficiaries WHERE user_id = %s AND account_number = %s',
            (id_utilisateur, numero_compte)
        )
        return curseur.fetchone() is not None
