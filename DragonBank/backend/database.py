"""
DragonBank - Utilitaires Base de Donnees
=========================================
Gere la connexion a PostgreSQL et la serialisation
des resultats de requetes en types JSON-compatibles.

Version : 3.0
"""

import uuid
import decimal
import logging
from datetime import datetime

import psycopg2
import psycopg2.extras

from config import URL_BASE_DE_DONNEES

journaliseur = logging.getLogger('dragonbank.database')


# ============================================================
# CONNEXION
# ============================================================

def creer_connexion():
    """
    Cree et retourne une connexion active a la base de donnees PostgreSQL.

    Utilise RealDictCursor pour que les resultats soient des
    dictionnaires (acces par nom de colonne) plutot que des tuples.

    L'autocommit est desactive : chaque route doit appeler
    commit() ou rollback() explicitement.

    Returns:
        psycopg2.connection: Connexion avec autocommit desactive.

    Raises:
        psycopg2.OperationalError: Si la connexion echoue.
    """
    connexion = psycopg2.connect(
        URL_BASE_DE_DONNEES,
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    connexion.autocommit = False
    return connexion


# ============================================================
# SERIALISATION JSON
# ============================================================

def serialiser_valeur(valeur):
    """
    Convertit une valeur PostgreSQL en type serialisable JSON.

    Certains types retournes par psycopg2 (Decimal, datetime, UUID)
    ne sont pas nativement serialisables par json.dumps().

    Args:
        valeur: La valeur a convertir.

    Returns:
        float  : si la valeur est un Decimal.
        str    : si la valeur est un datetime ou un UUID.
        valeur : inchangee pour tous les autres types.
    """
    if isinstance(valeur, decimal.Decimal):
        return float(valeur)
    if isinstance(valeur, datetime):
        return valeur.isoformat()
    if isinstance(valeur, uuid.UUID):
        return str(valeur)
    return valeur


def serialiser_ligne(ligne):
    """
    Serialise une ligne de resultat PostgreSQL en dictionnaire Python.

    Args:
        ligne: Une RealDictRow psycopg2, ou None.

    Returns:
        dict : Toutes les colonnes avec leurs valeurs converties.
        None : Si la ligne est None.
    """
    if ligne is None:
        return None

    resultat = {}
    for cle, valeur in dict(ligne).items():
        resultat[cle] = serialiser_valeur(valeur)
    return resultat


def serialiser_lignes(lignes):
    """
    Serialise une liste de lignes de resultat PostgreSQL.

    Args:
        lignes: Liste de RealDictRow psycopg2.

    Returns:
        list[dict]: Liste de dictionnaires serialises.
    """
    resultat = []
    for ligne in lignes:
        resultat.append(serialiser_ligne(ligne))
    return resultat


# ============================================================
# AUDIT
# ============================================================

def enregistrer_audit(curseur, id_utilisateur, action, details, adresse_ip):
    """
    Insere une entree dans la table des journaux d'audit.

    Trace toutes les actions sensibles (connexion, virement, ouverture
    de compte) pour la conformite reglementaire (RGPD, DSP2).

    Args:
        curseur        : Curseur de base de donnees actif.
        id_utilisateur : UUID de l'utilisateur.
        action (str)   : Code de l'action (ex: 'LOGIN', 'TRANSFER_INTERNAL').
        details (dict) : Informations complementaires en JSONB.
        adresse_ip (str): IP du client.

    Note:
        Ne commit pas. La validation est a la charge de l'appelant.
    """
    curseur.execute(
        """
        INSERT INTO audit_logs (user_id, action, details, ip_address)
        VALUES (%s, %s, %s::jsonb, %s)
        """,
        (id_utilisateur, action, psycopg2.extras.Json(details), adresse_ip)
    )
