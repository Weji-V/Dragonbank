"""
DragonBank - Modele Utilisateur
================================
Classe DAO (Data Access Object) gerant toutes les operations
en base de donnees relatives aux utilisateurs.

Pattern DAO : separe la logique d'acces aux donnees
de la logique metier et des routes Flask.

Version : 3.0
"""

import uuid
import logging

from database import serialiser_ligne, enregistrer_audit
from auth import hacher_mot_de_passe, verifier_mot_de_passe, simuler_verification_bcrypt

journaliseur = logging.getLogger('dragonbank.utilisateur')


class UtilisateurDAO:
    """
    Objet d'acces aux donnees pour la table users.

    Chaque methode recoit une connexion active en parametre.
    La gestion des transactions (commit/rollback) reste
    a la charge de la route appelante.
    """

    # =========================================================
    # CREATION
    # =========================================================

    def creer(self, connexion, email, mot_de_passe, prenom, nom,
              telephone=None, adresse=None, date_naissance=None):
        """
        Cree un nouvel utilisateur en base de donnees.

        Args:
            connexion      : Connexion PostgreSQL active.
            email (str)    : Adresse email (deja validee et normalisee).
            mot_de_passe (str): Mot de passe en clair (sera hache ici).
            prenom (str)   : Prenom de l'utilisateur.
            nom (str)      : Nom de famille.
            telephone (str): Numero de telephone (optionnel).
            adresse (str)  : Adresse postale (optionnel).
            date_naissance : Date de naissance au format YYYY-MM-DD (optionnel).

        Returns:
            dict: Les donnees de l'utilisateur cree (sans le hash du mot de passe).

        Raises:
            Exception: Si l'insertion echoue (email duplique, etc.).
        """
        id_utilisateur = str(uuid.uuid4())
        hash_mdp = hacher_mot_de_passe(mot_de_passe)

        curseur = connexion.cursor()
        curseur.execute(
            """
            INSERT INTO users
                (id, email, password_hash, first_name, last_name,
                 phone, address, date_of_birth)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, email, first_name, last_name, created_at
            """,
            (
                id_utilisateur, email, hash_mdp,
                prenom, nom,
                telephone or None,
                adresse or None,
                date_naissance or None
            )
        )
        utilisateur = curseur.fetchone()

        journaliseur.info("Nouvel utilisateur cree : %s", email)
        return serialiser_ligne(utilisateur)

    # =========================================================
    # LECTURE
    # =========================================================

    def trouver_par_email(self, connexion, email):
        """
        Recherche un utilisateur par son adresse email.

        Args:
            connexion  : Connexion PostgreSQL active.
            email (str): Email a rechercher.

        Returns:
            dict : Donnees de l'utilisateur (avec hash) si trouve.
            None : Si aucun utilisateur ne correspond.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT id, email, password_hash, first_name, last_name, is_active
            FROM users
            WHERE email = %s
            """,
            (email,)
        )
        return curseur.fetchone()

    def trouver_par_id(self, connexion, id_utilisateur):
        """
        Recupere le profil complet d'un utilisateur actif par son UUID.

        N'inclut pas le hash du mot de passe dans le resultat.

        Args:
            connexion         : Connexion PostgreSQL active.
            id_utilisateur    : UUID de l'utilisateur.

        Returns:
            dict : Profil de l'utilisateur.
            None : Si introuvable ou desactive.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT id, email, first_name, last_name, phone, address,
                   date_of_birth, created_at, last_login
            FROM users
            WHERE id = %s AND is_active = TRUE
            """,
            (id_utilisateur,)
        )
        return serialiser_ligne(curseur.fetchone())

    def email_existe(self, connexion, email):
        """
        Verifie si une adresse email est deja utilisee.

        Args:
            connexion  : Connexion PostgreSQL active.
            email (str): Email a verifier.

        Returns:
            bool: True si l'email existe deja, False sinon.
        """
        curseur = connexion.cursor()
        curseur.execute('SELECT id FROM users WHERE email = %s', (email,))
        return curseur.fetchone() is not None

    # =========================================================
    # MISE A JOUR
    # =========================================================

    def mettre_a_jour_derniere_connexion(self, connexion, id_utilisateur):
        """
        Met a jour la date de derniere connexion de l'utilisateur.

        Args:
            connexion         : Connexion PostgreSQL active.
            id_utilisateur    : UUID de l'utilisateur.
        """
        curseur = connexion.cursor()
        curseur.execute(
            'UPDATE users SET last_login = NOW() WHERE id = %s',
            (str(id_utilisateur),)
        )

    def mettre_a_jour_profil(self, connexion, id_utilisateur, champs):
        """
        Met a jour les champs modifiables du profil utilisateur.

        Seuls les champs fournis en parametre sont modifies.
        Les champs sensibles (email, mot de passe) sont ignores.

        Args:
            connexion         : Connexion PostgreSQL active.
            id_utilisateur    : UUID de l'utilisateur.
            champs (dict)     : Dictionnaire {nom_champ: nouvelle_valeur}.

        Returns:
            dict: Profil mis a jour.
        """
        clause_set = ', '.join(champ + ' = %s' for champ in champs)
        valeurs = list(champs.values())
        valeurs.append(id_utilisateur)

        curseur = connexion.cursor()
        curseur.execute(
            'UPDATE users SET ' + clause_set
            + ' WHERE id = %s'
              ' RETURNING id, email, first_name, last_name, phone, address',
            valeurs
        )
        return serialiser_ligne(curseur.fetchone())

    def mettre_a_jour_mot_de_passe(self, connexion, id_utilisateur, nouveau_hash):
        """Met a jour le l'empreinte bcrypt de l'utilisateur."""
        curseur = connexion.cursor()
        curseur.execute('UPDATE users SET password_hash = %s WHERE id = %s', (nouveau_hash, id_utilisateur))

    def mettre_a_jour_email(self, connexion, id_utilisateur, nouvel_email):
        """Met a jour l'adresse e-mail."""
        curseur = connexion.cursor()
        curseur.execute('UPDATE users SET email = %s WHERE id = %s', (nouvel_email, id_utilisateur))

    # =========================================================
    # AUTHENTIFICATION
    # =========================================================

    def authentifier(self, connexion, email, mot_de_passe):
        """
        Verifie les identifiants d'un utilisateur.

        Gere la protection contre les attaques temporelles :
        si l'email est inconnu, une verification bcrypt fictive est
        effectuee pour uniformiser le temps de reponse.

        Args:
            connexion          : Connexion PostgreSQL active.
            email (str)        : Email soumis.
            mot_de_passe (str) : Mot de passe en clair soumis.

        Returns:
            dict : Donnees de l'utilisateur si authentification reussie.
            None : Si les identifiants sont incorrects.

        Raises:
            PermissionError: Si le compte est desactive.
        """
        utilisateur = self.trouver_par_email(connexion, email)

        if not utilisateur:
            # On simule le temps bcrypt pour eviter la timing attack
            simuler_verification_bcrypt()
            return None

        if not utilisateur['is_active']:
            raise PermissionError("Ce compte a ete desactive. Contactez le support.")

        if not verifier_mot_de_passe(mot_de_passe, utilisateur['password_hash']):
            journaliseur.warning("Echec de connexion pour : %s", email)
            return None

        return utilisateur
