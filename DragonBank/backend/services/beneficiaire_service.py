from database import creer_connexion, enregistrer_audit
from auth import obtenir_ip_client
from models.beneficiaire import BeneficiaireDAO
from validators import valider_champs_obligatoires

class BeneficiaireService:
    def __init__(self):
        self.beneficiaire_dao = BeneficiaireDAO()

    def obtenir_beneficiaires(self, id_utilisateur_courant):
        conn = creer_connexion()
        try:
            return self.beneficiaire_dao.lister_par_utilisateur(conn, id_utilisateur_courant)
        finally:
            conn.close()

    def ajouter_beneficiaire(self, id_utilisateur_courant, donnees):
        conn = creer_connexion()
        try:
            valider_champs_obligatoires(donnees, ['beneficiary_name', 'account_number'])
            beneficiaire = self.beneficiaire_dao.ajouter(
                conn,
                id_utilisateur_courant,
                donnees['beneficiary_name'].strip(),
                donnees['account_number'].strip().upper(),
                donnees.get('bank_name', 'DragonBank').strip(),
                donnees.get('iban', '').strip().upper() or None,
                donnees.get('bic', '').strip().upper() or None
            )
            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'ADD_BENEFICIARY',
                              {'nom': donnees['beneficiary_name']}, obtenir_ip_client())
            conn.commit()
            return beneficiaire
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def supprimer_beneficiaire(self, id_utilisateur_courant, id_beneficiaire):
        conn = creer_connexion()
        try:
            supprime = self.beneficiaire_dao.supprimer(conn, id_beneficiaire, id_utilisateur_courant)
            if not supprime:
                raise ValueError('Beneficiaire introuvable')
            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'DELETE_BENEFICIARY',
                              {'id': id_beneficiaire}, obtenir_ip_client())
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
