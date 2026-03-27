"""
DragonBank - Validateurs
=========================
Centralise toutes les fonctions de validation des donnees
recues depuis les requetes HTTP.

Principe : chaque validateur retourne soit la valeur nettoyee,
soit leve une ValueError avec un message explicite.
Les routes n'ont ainsi pas a contenir de logique de validation.

Version : 3.0
"""

import re
import decimal

from config import (
    MONTANT_MINIMUM_VIREMENT,
    MONTANT_MAXIMUM_VIREMENT,
    SIMULATION_DUREE_MIN,
    SIMULATION_DUREE_MAX
)


# ============================================================
# EXPRESSIONS REGULIERES
# ============================================================

# Valide le format d'une adresse email (RFC 5322 simplifie).
REGEX_EMAIL = re.compile(
    r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
)


# ============================================================
# VALIDATEURS
# ============================================================

def valider_email(email):
    """
    Valide le format d'une adresse email.

    Args:
        email (str): L'adresse email a valider.

    Returns:
        str: L'email normalise (strip + lowercase).

    Raises:
        ValueError: Si le format est invalide ou si l'email est vide.
    """
    if not email or not email.strip():
        raise ValueError("L'adresse email est obligatoire")

    email_normalise = email.strip().lower()

    if not REGEX_EMAIL.match(email_normalise):
        raise ValueError("Le format de l'adresse email est invalide")

    return email_normalise


def valider_mot_de_passe(mot_de_passe):
    """
    Valide la complexite d'un mot de passe.

    Regles appliquees :
        - Au moins 8 caracteres.
        - Au moins une lettre majuscule (A-Z).
        - Au moins une lettre minuscule (a-z).
        - Au moins un chiffre (0-9).

    Args:
        mot_de_passe (str): Le mot de passe en clair a verifier.

    Returns:
        str: Le mot de passe inchange si valide.

    Raises:
        ValueError: Si une regle n'est pas respectee.
    """
    if not mot_de_passe or len(mot_de_passe) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caracteres")
    if not re.search(r'[A-Z]', mot_de_passe):
        raise ValueError("Le mot de passe doit contenir au moins une majuscule")
    if not re.search(r'[a-z]', mot_de_passe):
        raise ValueError("Le mot de passe doit contenir au moins une minuscule")
    if not re.search(r'\d', mot_de_passe):
        raise ValueError("Le mot de passe doit contenir au moins un chiffre")

    return mot_de_passe


def valider_montant(montant_brut):
    """
    Valide et convertit un montant en Decimal de maniere securisee.

    Utilise Decimal (et non float) pour eviter les erreurs d'arrondi
    inherentes aux nombres a virgule flottante (ex: 0.1 + 0.2 != 0.3).

    Args:
        montant_brut: Le montant brut a valider (str, int ou float).

    Returns:
        Decimal: Le montant valide et converti.

    Raises:
        ValueError: Si le montant est non numerique ou hors limites.
    """
    try:
        montant = decimal.Decimal(str(montant_brut))
    except (decimal.InvalidOperation, TypeError):
        raise ValueError("Le montant doit etre un nombre valide")

    if montant < MONTANT_MINIMUM_VIREMENT:
        raise ValueError(
            "Le montant minimum est de " + str(MONTANT_MINIMUM_VIREMENT) + " euros"
        )
    if montant > MONTANT_MAXIMUM_VIREMENT:
        raise ValueError(
            "Le montant maximum par virement est de " + str(MONTANT_MAXIMUM_VIREMENT) + " euros"
        )

    return montant


def valider_champs_obligatoires(donnees, champs):
    """
    Verifie que tous les champs obligatoires sont presents et non vides.

    Args:
        donnees (dict): Dictionnaire des donnees recues.
        champs (list) : Liste des noms de champs obligatoires.

    Returns:
        None

    Raises:
        ValueError: Liste des champs manquants si au moins un est absent.
    """
    if not donnees:
        raise ValueError("Le corps de la requete JSON est manquant")

    manquants = []
    for champ in champs:
        valeur = donnees.get(champ, '')
        if not valeur or (isinstance(valeur, str) and not valeur.strip()):
            manquants.append(champ)

    if manquants:
        raise ValueError("Champs obligatoires manquants : " + ", ".join(manquants))


def valider_parametres_simulateur(capital, taux, duree, versement):
    """
    Valide les parametres d'entree du simulateur d'epargne.

    Args:
        capital   (float): Capital initial en euros.
        taux      (float): Taux annuel en pourcentage.
        duree     (int)  : Duree en annees.
        versement (float): Versement mensuel en euros.

    Returns:
        None

    Raises:
        ValueError: Si un parametre est invalide.
    """
    if capital < 0:
        raise ValueError("Le capital initial ne peut pas etre negatif")
    if taux < 0 or taux > 100:
        raise ValueError("Le taux annuel doit etre compris entre 0 et 100 %")
    if duree < SIMULATION_DUREE_MIN or duree > SIMULATION_DUREE_MAX:
        raise ValueError(
            "La duree doit etre comprise entre "
            + str(SIMULATION_DUREE_MIN) + " et "
            + str(SIMULATION_DUREE_MAX) + " ans"
        )
    if versement < 0:
        raise ValueError("Le versement mensuel ne peut pas etre negatif")
