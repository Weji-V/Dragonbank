"""
DragonBank - Configuration
===========================
Centralise toutes les constantes et parametres de l'application.
Toutes les valeurs configurables sont recuperees depuis les variables
d'environnement afin de ne jamais stocker de donnees sensibles
dans le code source (bonne pratique Docker / 12-factor app).

Version : 3.0
"""

import os
import decimal


# ============================================================
# SECURITE
# ============================================================

# Cle secrete pour la signature des tokens JWT.
# OBLIGATOIRE en production via variable d'environnement.
CLE_SECRETE = os.environ.get('SECRET_KEY', 'dev-secret-key-changez-moi-en-production')

# Duree de validite d'un token JWT en heures.
DUREE_TOKEN_HEURES = int(os.environ.get('JWT_EXPIRATION_HOURS', 24))

# Nombre de rounds bcrypt pour le hachage des mots de passe.
# 12 = bon equilibre securite / performance.
COUT_HACHAGE_BCRYPT = 12


# ============================================================
# BASE DE DONNEES
# ============================================================

# URL de connexion PostgreSQL.
# Format : postgresql://utilisateur:motdepasse@hote:port/base
# URL de connexion PostgreSQL.
# Format : postgresql://utilisateur:motdepasse@hote:port/base
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


# ============================================================
# REGLES METIER - VIREMENTS
# ============================================================

# Montant minimum autorise pour un virement (en euros).
MONTANT_MINIMUM_VIREMENT = decimal.Decimal('0.01')

# Montant maximum autorise pour un virement (en euros).
MONTANT_MAXIMUM_VIREMENT = decimal.Decimal('50000.00')

# Solde de bienvenue credite a l'ouverture du premier compte courant.
SOLDE_BIENVENUE = decimal.Decimal('100.00')


# ============================================================
# REGLES METIER - COMPTES
# ============================================================

# Taux d'interet par cycle selon le type de compte.
TAUX_INTERETS = {
    'courant':       decimal.Decimal('0.0000'),  # 0 % - pas d'interet
    'livret_a':      decimal.Decimal('0.0300'),  # 3 % - taux reglemente
    'assurance_vie': decimal.Decimal('0.0200'),  # 2 % - fonds euros
}

# Types de comptes dont l'unicite est imposee par la reglementation.
# Un client ne peut detenir qu'un seul compte de ces types.
TYPES_COMPTE_UNIQUES = ('livret_a', 'assurance_vie')

# Champs du profil que l'utilisateur est autorise a modifier.
# Tous les autres champs (email, mot de passe, is_active) sont proteges.
CHAMPS_PROFIL_MODIFIABLES = ['first_name', 'last_name', 'phone', 'address']


# ============================================================
# REGLES METIER - TRANSACTIONS
# ============================================================

# Nombre de transactions retournees par defaut par l'historique.
LIMITE_TRANSACTIONS_DEFAUT = 50

# Nombre maximum de transactions retournables en une seule requete.
LIMITE_TRANSACTIONS_MAX = 200


# ============================================================
# SIMULATEUR D'EPARGNE
# ============================================================

# Duree minimale de simulation en annees.
SIMULATION_DUREE_MIN = 1

# Duree maximale de simulation en annees.
SIMULATION_DUREE_MAX = 40
