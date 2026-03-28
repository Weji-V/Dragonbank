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
            type_compte = donnees.get('account_type', 'courant')
            depot_brut = donnees.get('initial_deposit')
            depot = _d.Decimal(str(depot_brut)) if depot_brut else _d.Decimal('0')
            if depot < 0:
                raise ValueError('Le depot initial ne peut pas etre negatif')

            # Pour les comptes epargne, le depot est preleve du compte courant
            if type_compte in ('livret_a', 'assurance_vie') and depot > 0:
                # Trouver le compte courant actif de l'utilisateur
                comptes = self.compte_dao.lister_par_utilisateur(conn, id_utilisateur_courant)
                compte_courant = next(
                    (c for c in comptes if c['account_type'] == 'courant'), None
                )
                if not compte_courant:
                    raise ValueError(
                        "Vous devez posséder un compte courant pour alimenter ce compte."
                    )
                solde_courant = _d.Decimal(str(compte_courant['balance']))
                if solde_courant < depot:
                    raise ValueError(
                        f"Solde insuffisant sur votre compte courant "
                        f"(disponible : {float(solde_courant):.2f} €)."
                    )
                # Debiter le compte courant
                self.compte_dao.debiter(conn, str(compte_courant['id']), depot)

                # Enregistrer la transaction de transfert vers le nouveau compte (fait apres ouvrir)
                id_courant = str(compte_courant['id'])
            else:
                id_courant = None

            compte = self.compte_dao.ouvrir(
                conn, id_utilisateur_courant,
                type_compte,
                depot
            )

            # Si on a debite le courant, creer la transaction de transfert
            if id_courant and depot > 0:
                curseur = conn.cursor()
                noms = {'livret_a': 'Livret A', 'assurance_vie': 'Assurance Vie'}
                libelle = f"Versement initial sur {noms.get(type_compte, type_compte)}"
                curseur.execute(
                    """
                    INSERT INTO transactions
                        (from_account_id, to_account_id, transaction_type,
                         amount, description, status, executed_at)
                    VALUES (%s, %s, 'virement_interne', %s, %s, 'completed', NOW())
                    """,
                    (id_courant, str(compte['id']), float(depot), libelle)
                )

            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'OPEN_ACCOUNT',
                              {'type': type_compte, 'depot': float(depot)},
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
