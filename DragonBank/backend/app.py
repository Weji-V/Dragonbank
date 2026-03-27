"""
DragonBank - Backend API
========================
Point d'entree de l'API REST DragonBank.

Ce fichier ne contient que les routes Flask.
Toute la logique est deleguee aux classes metier (Services) :

    config.py         — Constantes et parametres
    database.py       — Connexion et serialisation
    auth.py           — JWT et protection des routes
    validators.py     — Validation des donnees entrantes
    services/
        auth_service.py        - Inscription et connexion
        utilisateur_service.py - Profil utilisateur
        compte_service.py      - Gestion des comptes
        beneficiaire_service.py- Gestion des beneficiaires
        transaction_service.py - Virements et historique
        stats_service.py       - Statistiques tableau de bord
    models/
        simulateur.py  — Logique calcul interets composes

Version : 3.0 (Refactoring Service Layer)
"""

import logging
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_cors import CORS

from config import CLE_SECRETE
from database import creer_connexion
from auth import token_requis
from validators import valider_parametres_simulateur

from services.auth_service import AuthService
from services.utilisateur_service import UtilisateurService
from services.compte_service import CompteService
from services.beneficiaire_service import BeneficiaireService
from services.transaction_service import TransactionService
from services.stats_service import StatsService
from models.simulateur import Simulateur


# ============================================================
# INITIALISATION
# ============================================================

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = CLE_SECRETE

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
journaliseur = logging.getLogger('dragonbank')

# Instances des services (sans etat, reutilisables)
auth_service         = AuthService()
utilisateur_service  = UtilisateurService()
compte_service       = CompteService()
beneficiaire_service = BeneficiaireService()
transaction_service  = TransactionService()
stats_service        = StatsService()
simulateur           = Simulateur()


# ============================================================
# SANTE
# ============================================================

@app.route('/api/health', methods=['GET'])
def verification_sante():
    """Healthcheck pour Docker et load balancers."""
    try:
        conn = creer_connexion()
        conn.cursor().execute('SELECT 1')
        conn.close()
        return jsonify({
            'status':    'healthy',
            'service':   'DragonBank Backend API',
            'version':   '3.0',
            'database':  'connected',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200
    except Exception as e:
        journaliseur.error("Health check echoue : %s", str(e))
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500


# ============================================================
# AUTHENTIFICATION
# ============================================================

@app.route('/api/auth/register', methods=['POST'])
def inscription():
    """Cree un nouveau compte utilisateur avec un compte courant de bienvenue."""
    donnees = request.get_json(silent=True)
    try:
        resultat = auth_service.inscrire(donnees)
        return jsonify(resultat), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        journaliseur.error("Erreur inscription : %s", str(e))
        return jsonify({'error': "Erreur interne lors de l'inscription"}), 500


@app.route('/api/auth/login', methods=['POST'])
def connexion_utilisateur():
    """Authentifie un utilisateur et retourne un token JWT."""
    donnees = request.get_json(silent=True)
    try:
        resultat = auth_service.connecter(donnees)
        return jsonify(resultat), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        journaliseur.error("Erreur connexion : %s", str(e))
        return jsonify({'error': 'Erreur interne lors de la connexion'}), 500


# ============================================================
# PROFIL UTILISATEUR
# ============================================================

@app.route('/api/user/profile', methods=['GET'])
@token_requis
def obtenir_profil(id_utilisateur_courant):
    """Retourne le profil de l'utilisateur connecte."""
    try:
        utilisateur = utilisateur_service.obtenir_profil(id_utilisateur_courant)
        return jsonify({'user': utilisateur}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': 'Erreur interne lors de la recuperation du profil'}), 500


@app.route('/api/user/profile', methods=['PUT'])
@token_requis
def modifier_profil(id_utilisateur_courant):
    """Met a jour les champs non sensibles du profil."""
    donnees = request.get_json(silent=True)
    try:
        mis_a_jour = utilisateur_service.modifier_profil(id_utilisateur_courant, donnees)
        return jsonify({'message': 'Profil mis a jour', 'user': mis_a_jour}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Erreur lors de la mise a jour'}), 500


@app.route('/api/user/security/password', methods=['PUT'])
@token_requis
def modifier_mot_de_passe(id_utilisateur_courant):
    """Met a jour le mot de passe utilisateur (necessite le mot de passe actuel)."""
    donnees = request.get_json(silent=True)
    try:
        utilisateur_service.changer_mot_de_passe(id_utilisateur_courant, donnees)
        return jsonify({'message': 'Mot de passe mis a jour avec succes'}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        journaliseur.error("Erreur modification mot de passe : %s", str(e))
        return jsonify({'error': 'Erreur interne'}), 500


@app.route('/api/user/security/email', methods=['PUT'])
@token_requis
def modifier_email(id_utilisateur_courant):
    """Met a jour l'adresse email (necessite le mot de passe actuel)."""
    donnees = request.get_json(silent=True)
    try:
        utilisateur_service.changer_email(id_utilisateur_courant, donnees)
        return jsonify({'message': 'Email mis a jour avec succes. Veuillez vous reconnecter avec votre nouvel email.'}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        journaliseur.error("Erreur modification email : %s", str(e))
        return jsonify({'error': 'Erreur interne'}), 500


# ============================================================
# COMPTES BANCAIRES
# ============================================================

@app.route('/api/accounts', methods=['GET'])
@token_requis
def obtenir_comptes(id_utilisateur_courant):
    """Retourne la liste des comptes actifs."""
    try:
        comptes = compte_service.obtenir_comptes(id_utilisateur_courant)
        return jsonify({'accounts': comptes}), 200
    except Exception:
        return jsonify({'error': 'Erreur lors de la recuperation des comptes'}), 500


@app.route('/api/accounts', methods=['POST'])
@token_requis
def ouvrir_compte(id_utilisateur_courant):
    """Ouvre un nouveau compte bancaire."""
    donnees = request.get_json(silent=True)
    try:
        compte = compte_service.ouvrir_compte(id_utilisateur_courant, donnees)
        return jsonify({'message': 'Compte ouvert avec succes', 'account': compte}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400 if 'invalide' in str(e) else 409
    except Exception as e:
        journaliseur.error("Erreur ouverture compte : %s", str(e))
        return jsonify({'error': "Erreur lors de l'ouverture du compte"}), 500


@app.route('/api/accounts/<id_compte>', methods=['GET'])
@token_requis
def obtenir_detail_compte(id_utilisateur_courant, id_compte):
    """Retourne les details d'un compte specifique."""
    try:
        compte = compte_service.obtenir_detail_compte(id_utilisateur_courant, id_compte)
        return jsonify({'account': compte}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception:
        return jsonify({'error': 'Erreur serveur'}), 500


@app.route('/api/accounts/<id_compte>/history', methods=['GET'])
@token_requis
def historique_solde(id_utilisateur_courant, id_compte):
    """Retourne l'evolution du solde pour le graphique."""
    try:
        historique = compte_service.historique_solde(id_utilisateur_courant, id_compte)
        return jsonify(historique), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception:
        return jsonify({'error': 'Erreur serveur'}), 500


# ============================================================
# BENEFICIAIRES
# ============================================================

@app.route('/api/beneficiaries', methods=['GET'])
@token_requis
def obtenir_beneficiaires(id_utilisateur_courant):
    """Retourne la liste des beneficiaires."""
    try:
        beneficiaires = beneficiaire_service.obtenir_beneficiaires(id_utilisateur_courant)
        return jsonify({'beneficiaries': beneficiaires}), 200
    except Exception:
        return jsonify({'error': 'Erreur serveur'}), 500


@app.route('/api/beneficiaries', methods=['POST'])
@token_requis
def ajouter_beneficiaire(id_utilisateur_courant):
    """Ajoute un nouveau beneficiaire."""
    donnees = request.get_json(silent=True)
    try:
        beneficiaire = beneficiaire_service.ajouter_beneficiaire(id_utilisateur_courant, donnees)
        return jsonify({'message': 'Beneficiaire ajoute', 'beneficiary': beneficiaire}), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400 if 'vous-meme' in str(e) else 409
    except Exception as e:
        return jsonify({'error': "Erreur lors de l'ajout"}), 500


@app.route('/api/beneficiaries/<id_beneficiaire>', methods=['DELETE'])
@token_requis
def supprimer_beneficiaire(id_utilisateur_courant, id_beneficiaire):
    """Supprime un beneficiaire."""
    try:
        beneficiaire_service.supprimer_beneficiaire(id_utilisateur_courant, id_beneficiaire)
        return jsonify({'message': 'Beneficiaire supprime'}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': 'Erreur lors de la suppression'}), 500


# ============================================================
# VIREMENTS
# ============================================================

@app.route('/api/transfers/internal', methods=['POST'])
@token_requis
def virement_interne(id_utilisateur_courant):
    """Virement entre les propres comptes de l'utilisateur."""
    donnees = request.get_json(silent=True)
    try:
        transaction = transaction_service.virement_interne(id_utilisateur_courant, donnees)
        return jsonify({'message': 'Virement effectue', 'transaction': transaction}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400 if 'introuvable' not in str(e) else 404
    except Exception as e:
        journaliseur.error("Erreur virement interne : %s", str(e))
        return jsonify({'error': 'Erreur lors du virement'}), 500


@app.route('/api/transfers/person', methods=['POST'])
@token_requis
def virement_beneficiaire(id_utilisateur_courant):
    """Virement vers un beneficiaire enregistre."""
    donnees = request.get_json(silent=True)
    try:
        transaction = transaction_service.virement_beneficiaire(id_utilisateur_courant, donnees)
        return jsonify({'message': 'Virement effectue', 'transaction': transaction}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400 if 'introuvable' not in str(e) else 404
    except Exception as e:
        return jsonify({'error': 'Erreur lors du virement'}), 500


@app.route('/api/transfers/external', methods=['POST'])
@token_requis
def virement_externe(id_utilisateur_courant):
    """Virement simule depuis/vers une banque externe."""
    donnees = request.get_json(silent=True)
    try:
        transaction, direction = transaction_service.virement_externe(id_utilisateur_courant, donnees)
        sens = 'sortant' if direction == 'outgoing' else 'entrant'
        return jsonify({
            'message': 'Virement externe ' + sens + ' effectue',
            'transaction': transaction
        }), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400 if 'introuvable' not in str(e) else 404
    except Exception as e:
        return jsonify({'error': 'Erreur lors du virement externe'}), 500


# ============================================================
# TRANSACTIONS
# ============================================================

@app.route('/api/transactions', methods=['GET'])
@token_requis
def obtenir_transactions(id_utilisateur_courant):
    """Historique des transactions avec filtres optionnels."""
    id_compte        = request.args.get('account_id')
    type_transaction = request.args.get('type')
    limite           = request.args.get('limit', 50, type=int)

    try:
        transactions = transaction_service.obtenir_transactions(
            id_utilisateur_courant, id_compte, type_transaction, limite
        )
        return jsonify({'transactions': transactions, 'count': len(transactions)}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception:
        return jsonify({'error': 'Erreur serveur'}), 500


@app.route('/api/transactions/export', methods=['GET'])
@token_requis
def exporter_csv(id_utilisateur_courant):
    """Export CSV de l'historique des transactions."""
    id_compte = request.args.get('account_id')
    try:
        csv_response = transaction_service.exporter_csv(id_utilisateur_courant, id_compte)
        return csv_response
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception:
        return jsonify({'error': 'Erreur serveur'}), 500


# ============================================================
# STATISTIQUES
# ============================================================

@app.route('/api/stats', methods=['GET'])
@token_requis
def obtenir_statistiques(id_utilisateur_courant):
    """Tableau de bord statistique de l'utilisateur."""
    try:
        stats = stats_service.obtenir_statistiques(id_utilisateur_courant)
        return jsonify({'stats': stats}), 200
    except Exception:
        return jsonify({'error': 'Erreur serveur'}), 500


# ============================================================
# SIMULATEUR D'EPARGNE
# ============================================================

@app.route('/api/simulator', methods=['POST'])
@token_requis
def simuler_epargne(id_utilisateur_courant):
    """Simulation de croissance d'epargne par interets composes."""
    donnees = request.get_json(silent=True)
    try:
        if not donnees:
            raise ValueError("Donnees JSON manquantes")

        capital   = float(donnees.get('capital_initial', 0))
        taux      = float(donnees.get('taux_annuel', 0))
        duree     = int(donnees.get('duree_annees', 1))
        versement = float(donnees.get('versement_mensuel', 0))

        valider_parametres_simulateur(capital, taux, duree, versement)

        resultat = simulateur.simuler(capital, taux, duree, versement)
        return jsonify(resultat), 200

    except (TypeError, ValueError) as e:
        return jsonify({'error': str(e)}), 400


# ============================================================
# GESTION DES ERREURS HTTP
# ============================================================

@app.errorhandler(404)
def erreur_404(e):
    return jsonify({'error': 'Route introuvable'}), 404

@app.errorhandler(405)
def erreur_405(e):
    return jsonify({'error': 'Methode HTTP non autorisee'}), 405

@app.errorhandler(500)
def erreur_500(e):
    journaliseur.error("Erreur interne : %s", str(e))
    return jsonify({'error': 'Erreur interne du serveur'}), 500


# ============================================================
# POINT D'ENTREE
# ============================================================

if __name__ == '__main__':
    from config import URL_BASE_DE_DONNEES
    print("DragonBank Backend API v3.0 - demarrage...")
    print("Base : " + (URL_BASE_DE_DONNEES.split('@')[1] if '@' in URL_BASE_DE_DONNEES else 'configuree'))
    app.run(host='0.0.0.0', port=5000, debug=False)
