from database import creer_connexion, enregistrer_audit
from auth import obtenir_ip_client
from validators import valider_champs_obligatoires, valider_montant
from models.transaction import TransactionDAO
from models.compte import CompteDAO
from models.beneficiaire import BeneficiaireDAO

class TransactionService:
    def __init__(self):
        self.transaction_dao = TransactionDAO()
        self.compte_dao = CompteDAO()
        self.beneficiaire_dao = BeneficiaireDAO()

    def virement_interne(self, id_utilisateur_courant, donnees):
        conn = creer_connexion()
        try:
            valider_champs_obligatoires(donnees, ['from_account_id', 'to_account_id', 'amount'])
            montant = valider_montant(donnees['amount'])

            if donnees['from_account_id'] == donnees['to_account_id']:
                raise ValueError('Les comptes source et destination doivent etre differents')

            source = self.compte_dao.trouver_actif(conn, donnees['from_account_id'], id_utilisateur_courant)
            dest = self.compte_dao.trouver_actif(conn, donnees['to_account_id'], id_utilisateur_courant)
            
            if not source:
                raise ValueError('Compte source introuvable')
            if not dest:
                raise ValueError('Compte destination introuvable')

            libelle = donnees.get('description') or (
                'Virement ' + source['account_type'] + ' vers ' + dest['account_type']
            )

            transaction = self.transaction_dao.virement_interne(
                conn, donnees['from_account_id'], donnees['to_account_id'],
                montant, libelle, self.compte_dao
            )
            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'TRANSFER_INTERNAL',
                              {'montant': float(montant), 'source': source['account_number'],
                               'dest': dest['account_number']}, obtenir_ip_client())
            conn.commit()
            return transaction
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def virement_beneficiaire(self, id_utilisateur_courant, donnees):
        conn = creer_connexion()
        try:
            valider_champs_obligatoires(donnees, ['from_account_id', 'beneficiary_id', 'amount'])
            montant = valider_montant(donnees['amount'])

            source = self.compte_dao.trouver_actif(conn, donnees['from_account_id'], id_utilisateur_courant)
            if not source:
                raise ValueError('Compte source introuvable')

            beneficiaire = self.beneficiaire_dao.trouver_approuve(
                conn, donnees['beneficiary_id'], id_utilisateur_courant
            )
            if not beneficiaire:
                raise ValueError('Beneficiaire introuvable ou non approuve')

            dest = self.compte_dao.trouver_par_numero(conn, beneficiaire['account_number'])
            if not dest:
                raise ValueError('Le compte du beneficiaire est introuvable dans DragonBank')

            libelle = donnees.get('description') or 'Virement a ' + beneficiaire['beneficiary_name']

            transaction = self.transaction_dao.virement_entre_personnes(
                conn, donnees['from_account_id'], str(dest['id']),
                montant, libelle, self.compte_dao
            )
            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'TRANSFER_PERSON',
                              {'montant': float(montant), 'beneficiaire': beneficiaire['beneficiary_name']},
                              obtenir_ip_client())
            conn.commit()
            return transaction
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def virement_externe(self, id_utilisateur_courant, donnees):
        conn = creer_connexion()
        try:
            valider_champs_obligatoires(
                donnees,
                ['account_id', 'amount', 'external_bank_name', 'external_account_number', 'direction']
            )
            direction = donnees['direction']
            if direction not in ('incoming', 'outgoing'):
                raise ValueError('La direction doit etre "incoming" ou "outgoing"')

            montant = valider_montant(donnees['amount'])
            compte = self.compte_dao.trouver_actif(conn, donnees['account_id'], id_utilisateur_courant)
            if not compte:
                raise ValueError('Compte introuvable')

            nom_banque = donnees['external_bank_name'].strip()
            num_ext = donnees['external_account_number'].strip().upper()
            libelle = donnees.get('description', '').strip() or (
                'Virement ' + ('sortant vers ' if direction == 'outgoing' else 'entrant depuis ')
                + nom_banque + ' (' + num_ext + ')'
            )

            transaction = self.transaction_dao.virement_externe(
                conn, donnees['account_id'], montant, direction,
                nom_banque, num_ext, libelle, self.compte_dao
            )
            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'TRANSFER_EXTERNAL',
                              {'montant': float(montant), 'direction': direction, 'banque': nom_banque},
                              obtenir_ip_client())
            conn.commit()
            return transaction, direction
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def obtenir_transactions(self, id_utilisateur_courant, id_compte_filtre, type_tx_filtre, limite):
        conn = creer_connexion()
        try:
            if id_compte_filtre:
                if not self.compte_dao.trouver_par_id(conn, id_compte_filtre, id_utilisateur_courant):
                    raise ValueError('Compte introuvable ou acces refuse')

            transactions = self.transaction_dao.lister(
                conn, id_utilisateur_courant, id_compte_filtre, type_tx_filtre, limite
            )
            return transactions
        finally:
            conn.close()

    def exporter_csv(self, id_utilisateur_courant, id_compte_filtre):
        conn = creer_connexion()
        try:
            if id_compte_filtre:
                if not self.compte_dao.trouver_par_id(conn, id_compte_filtre, id_utilisateur_courant):
                    raise ValueError('Compte introuvable ou acces refuse')
            return self.transaction_dao.exporter_csv(conn, id_utilisateur_courant, id_compte_filtre)
        finally:
            conn.close()
