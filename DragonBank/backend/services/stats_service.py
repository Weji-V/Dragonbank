from database import creer_connexion, serialiser_valeur
from models.transaction import TransactionDAO

class StatsService:
    def __init__(self):
        self.transaction_dao = TransactionDAO()

    def obtenir_statistiques(self, id_utilisateur_courant):
        conn = creer_connexion()
        try:
            curseur = conn.cursor()

            curseur.execute(
                """
                SELECT COALESCE(SUM(balance), 0) AS total_balance,
                       COUNT(*) AS total_accounts
                FROM accounts
                WHERE user_id = %s AND status = 'active'
                """,
                (id_utilisateur_courant,)
            )
            stats_comptes = curseur.fetchone()

            stats_tx = self.transaction_dao.statistiques(conn, id_utilisateur_courant)

            curseur.execute(
                'SELECT COUNT(*) AS total_beneficiaries FROM beneficiaries WHERE user_id = %s',
                (id_utilisateur_courant,)
            )
            stats_ben = curseur.fetchone()

            return {
                'total_balance': serialiser_valeur(stats_comptes['total_balance']),
                'total_accounts': stats_comptes['total_accounts'],
                'monthly_transactions': stats_tx['transactions_mois'],
                'total_sent': serialiser_valeur(stats_tx['total_envoye']),
                'total_received': serialiser_valeur(stats_tx['total_recu']),
                'total_beneficiaries': stats_ben['total_beneficiaries']
            }
        finally:
            conn.close()
