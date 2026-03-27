"""
DragonBank - Authentification
==============================
Gere la generation et la verification des tokens JWT,
ainsi que le decorateur de protection des routes Flask.

Version : 3.0
"""

import uuid
import logging
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from functools import wraps

import jwt
import bcrypt
from flask import request
from flask import jsonify
from flask import current_app

from config import DUREE_TOKEN_HEURES, COUT_HACHAGE_BCRYPT

journaliseur = logging.getLogger('dragonbank.auth')


# ============================================================
# UTILITAIRES IP
# ============================================================

def obtenir_ip_client():
    """
    Retourne l'adresse IP reelle du client.

    Lorsque l'application est derriere un reverse proxy (Nginx, Traefik),
    l'en-tete X-Forwarded-For contient la liste des IPs traversees.
    La premiere est celle du client d'origine.

    Returns:
        str: L'adresse IP du client.
    """
    entete = request.headers.get('X-Forwarded-For')
    if entete:
        return entete.split(',')[0].strip()
    return request.remote_addr


# ============================================================
# GESTION DES MOTS DE PASSE
# ============================================================

def hacher_mot_de_passe(mot_de_passe_clair):
    """
    Hache un mot de passe avec bcrypt.

    Args:
        mot_de_passe_clair (str): Le mot de passe en clair.

    Returns:
        str: Le hash bcrypt encode en UTF-8.
    """
    sel = bcrypt.gensalt(rounds=COUT_HACHAGE_BCRYPT)
    return bcrypt.hashpw(
        mot_de_passe_clair.encode('utf-8'),
        sel
    ).decode('utf-8')


def verifier_mot_de_passe(mot_de_passe_clair, hash_stocke):
    """
    Verifie un mot de passe contre son hash bcrypt stocke.

    Args:
        mot_de_passe_clair (str): Le mot de passe en clair soumis.
        hash_stocke (str)       : Le hash bcrypt stocke en base.

    Returns:
        bool: True si le mot de passe correspond, False sinon.
    """
    return bcrypt.checkpw(
        mot_de_passe_clair.encode('utf-8'),
        hash_stocke.encode('utf-8')
    )


def simuler_verification_bcrypt():
    """
    Effectue un hachage bcrypt fictif pour consommer du temps CPU.

    Utilise pour uniformiser le temps de reponse lors d'un echec
    de connexion, qu'il s'agisse d'un email inconnu ou d'un mauvais
    mot de passe (contre-mesure aux attaques temporelles).
    """
    hacher_mot_de_passe('dummy')


# ============================================================
# TOKENS JWT
# ============================================================

def generer_token(id_utilisateur, email):
    """
    Genere un token JWT signe pour authentifier un utilisateur.

    Charge utile du token :
        - user_id : UUID de l'utilisateur.
        - email   : Adresse email.
        - iat     : Date de creation (issued at).
        - exp     : Date d'expiration.
        - jti     : Identifiant unique du token (JWT ID).

    Args:
        id_utilisateur (str): UUID de l'utilisateur.
        email (str)         : Adresse email.

    Returns:
        str: Le token JWT encode et signe.
    """
    maintenant = datetime.now(timezone.utc)
    charge_utile = {
        'user_id': str(id_utilisateur),
        'email':   email,
        'iat':     maintenant,
        'exp':     maintenant + timedelta(hours=DUREE_TOKEN_HEURES),
        'jti':     str(uuid.uuid4())
    }
    return jwt.encode(
        charge_utile,
        current_app.config['SECRET_KEY'],
        algorithm='HS256'
    )


# ============================================================
# DECORATEUR DE PROTECTION DES ROUTES
# ============================================================

def token_requis(fonction):
    """
    Decorateur protegeant une route Flask par verification du token JWT.

    Extrait le token depuis l'en-tete Authorization (format Bearer),
    le valide, puis injecte l'identifiant de l'utilisateur comme
    premier argument de la fonction decoree.

    Usage :
        @app.route('/api/exemple')
        @token_requis
        def ma_route(id_utilisateur_courant):
            ...

    Returns:
        401: Token manquant, expire ou invalide.
    """
    @wraps(fonction)
    def enveloppe(*args, **kwargs):

        # --- Extraction du token ---
        token = None
        entete = request.headers.get('Authorization', '')
        if entete.startswith('Bearer '):
            token = entete.split(' ', 1)[1].strip()

        if not token:
            journaliseur.warning("Acces sans token depuis %s", obtenir_ip_client())
            return jsonify({'error': "Token d'authentification manquant"}), 401

        # --- Verification et decodage ---
        try:
            charge = jwt.decode(
                token,
                current_app.config['SECRET_KEY'],
                algorithms=['HS256']
            )
            id_utilisateur_courant = charge['user_id']

        except jwt.ExpiredSignatureError:
            journaliseur.info("Token expire depuis %s", obtenir_ip_client())
            return jsonify({'error': 'Session expiree, veuillez vous reconnecter'}), 401

        except jwt.InvalidTokenError as erreur:
            journaliseur.warning("Token invalide depuis %s : %s", obtenir_ip_client(), str(erreur))
            return jsonify({'error': 'Token invalide'}), 401

        return fonction(id_utilisateur_courant, *args, **kwargs)

    return enveloppe
