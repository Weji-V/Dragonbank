from database import creer_connexion, enregistrer_audit
from auth import obtenir_ip_client
from models.compte import CompteDAO
from models.transaction import TransactionDAO

class CompteService:
    def __init__(self):
        self.compte_dao = CompteDAO()
        self.transaction_dao = TransactionDAO()

    def obtenir_comptes(self, id_utilisateur_courant):
        conn = creer_connexion()
        try:
            return self.compte_dao.lister_par_utilisateur(conn, id_utilisateur_courant)
        finally:
            conn.close()

    def ouvrir_compte(self, id_utilisateur_courant, donnees):
        donnees = donnees or {}
        conn = creer_connexion()
        try:
            import decimal as _d
            depot_brut = donnees.get('initial_deposit')
            depot = _d.Decimal(str(depot_brut)) if depot_brut else _d.Decimal('0')
            if depot < 0:
                raise ValueError('Le depot initial ne peut pas etre negatif')

            compte = self.compte_dao.ouvrir(
                conn, id_utilisateur_courant,
                donnees.get('account_type', 'courant'),
                depot
            )
            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'OPEN_ACCOUNT',
                              {'type': donnees.get('account_type'), 'depot': float(depot)},
                              obtenir_ip_client())
            conn.commit()
            return compte
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def obtenir_detail_compte(self, id_utilisateur_courant, id_compte):
        conn = creer_connexion()
        try:
            compte = self.compte_dao.trouver_par_id(conn, id_compte, id_utilisateur_courant)
            if not compte:
                raise ValueError('Compte introuvable')
            return compte
        finally:
            conn.close()

    def historique_solde(self, id_utilisateur_courant, id_compte):
        conn = creer_connexion()
        try:
            compte = self.compte_dao.trouver_par_id(conn, id_compte, id_utilisateur_courant)
            if not compte:
                raise ValueError('Compte introuvable')

            points = self.transaction_dao.historique_solde(conn, id_compte, compte['balance'])
            return {
                'account_type': compte['account_type'],
                'solde_actuel': compte['balance'],
                'points': points
            }
        finally:
            conn.close()
