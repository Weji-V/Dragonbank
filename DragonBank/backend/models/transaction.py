"""
DragonBank - Modele Transaction
=================================
Classe DAO gerant les virements et l'historique des transactions.

Chaque virement est atomique : debit et credit s'effectuent dans
la meme transaction SQL. Si l'une echoue, tout est annule.

Version : 3.0
"""

import decimal
import logging
import io
import csv

from flask import Response

from database import serialiser_ligne, serialiser_lignes
from config import LIMITE_TRANSACTIONS_DEFAUT, LIMITE_TRANSACTIONS_MAX

journaliseur = logging.getLogger('dragonbank.transaction')

# Noms lisibles pour les types de transactions (utilises dans l'export CSV).
NOMS_TYPES = {
    'virement_interne':         'Virement interne',
    'virement_entre_personnes': 'Virement entre personnes',
    'virement_externe':         'Virement externe',
    'depot':                    'Depot',
    'retrait':                  'Retrait',
    'interets':                 'Interets'
}


class TransactionDAO:
    """
    Objet d'acces aux donnees pour la table transactions.

    Contient la logique des trois types de virements :
      - Interne      : entre les propres comptes de l'utilisateur.
      - Entre personnes : vers un beneficiaire DragonBank.
      - Externe      : depuis/vers une banque tierce (simule).
    """

    # =========================================================
    # LECTURE
    # =========================================================

    def lister(self, connexion, id_utilisateur, id_compte=None,
               type_transaction=None, limite=None):
        """
        Retourne l'historique des transactions d'un utilisateur.

        Args:
            connexion           : Connexion PostgreSQL active.
            id_utilisateur      : UUID de l'utilisateur.
            id_compte (str)     : Filtrer par compte (optionnel).
            type_transaction    : Filtrer par type (optionnel).
            limite (int)        : Nombre max de resultats (defaut: 50).

        Returns:
            list[dict]: Transactions triees par date decroissante.
        """
        if limite is None:
            limite = LIMITE_TRANSACTIONS_DEFAUT
        if limite > LIMITE_TRANSACTIONS_MAX:
            limite = LIMITE_TRANSACTIONS_MAX

        requete_base = """
            SELECT t.id, t.from_account_id, t.to_account_id, t.transaction_type,
                   t.amount, t.currency, t.description, t.status, t.reference,
                   t.external_bank_name, t.external_account_number,
                   t.created_at, t.executed_at,
                   fa.account_number AS from_account_number,
                   ta.account_number AS to_account_number
            FROM transactions t
            LEFT JOIN accounts fa ON t.from_account_id = fa.id
            LEFT JOIN accounts ta ON t.to_account_id = ta.id
        """

        if id_compte:
            clause_where = "WHERE (t.from_account_id = %s OR t.to_account_id = %s)"
            parametres = [id_compte, id_compte]
        else:
            clause_where = "WHERE (fa.user_id = %s OR ta.user_id = %s)"
            parametres = [id_utilisateur, id_utilisateur]

        if type_transaction:
            clause_where = clause_where + " AND t.transaction_type = %s"
            parametres.append(type_transaction)

        parametres.append(limite)

        curseur = connexion.cursor()
        curseur.execute(
            requete_base + ' ' + clause_where + ' ORDER BY t.created_at DESC LIMIT %s',
            parametres
        )
        return serialiser_lignes(curseur.fetchall())

    def historique_solde(self, connexion, id_compte, solde_actuel):
        """
        Reconstitue l'evolution du solde d'un compte dans le temps.

        Utilise une back-calculation : on part du solde actuel
        et on remonte les transactions pour retrouver les soldes passes.

        Args:
            connexion      : Connexion PostgreSQL active.
            id_compte      : UUID du compte.
            solde_actuel   : Solde actuel du compte (float).

        Returns:
            list[dict]: Points {date, solde} en ordre chronologique.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT created_at, amount, from_account_id, to_account_id
            FROM transactions
            WHERE (from_account_id = %s OR to_account_id = %s)
              AND status = 'completed'
            ORDER BY created_at DESC
            """,
            (id_compte, id_compte)
        )
        transactions = curseur.fetchall()

        solde_courant = float(solde_actuel)
        points = []

        for transaction in transactions:
            montant   = float(transaction['amount'])
            est_debit = str(transaction['from_account_id']) == id_compte

            points.append({
                'date':  str(transaction['created_at'])[:10],
                'solde': round(solde_courant, 2)
            })

            if est_debit:
                solde_courant = solde_courant + montant
            else:
                solde_courant = solde_courant - montant

        points.append({'date': 'Ouverture', 'solde': round(solde_courant, 2)})
        points.reverse()
        return points

    # =========================================================
    # VIREMENTS
    # =========================================================

    def virement_interne(self, connexion, id_source, id_destination,
                         montant, libelle, compte_dao):
        """
        Effectue un virement entre deux comptes du meme utilisateur.

        Verifie le solde puis debite la source et credite la destination
        dans la meme transaction SQL (atomicite).

        Args:
            connexion       : Connexion PostgreSQL active.
            id_source (str) : UUID du compte source.
            id_destination  : UUID du compte destination.
            montant         : Montant (Decimal).
            libelle (str)   : Description du virement.
            compte_dao      : Instance de CompteDAO pour les mises a jour.

        Returns:
            dict: La transaction creee.

        Raises:
            ValueError: Si le solde est insuffisant.
        """
        self._verifier_solde_suffisant(connexion, id_source, montant)

        compte_dao.debiter(connexion, id_source, montant)
        compte_dao.crediter(connexion, id_destination, montant)

        return self._enregistrer(
            connexion,
            from_id=id_source,
            to_id=id_destination,
            type_t='virement_interne',
            montant=montant,
            libelle=libelle
        )

    def virement_entre_personnes(self, connexion, id_source, id_destination,
                                  montant, libelle, compte_dao):
        """
        Effectue un virement vers un beneficiaire DragonBank.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_source (str) : UUID du compte source.
            id_destination  : UUID du compte destination (beneficiaire).
            montant         : Montant (Decimal).
            libelle (str)   : Description du virement.
            compte_dao      : Instance de CompteDAO.

        Returns:
            dict: La transaction creee.

        Raises:
            ValueError: Si le solde est insuffisant.
        """
        self._verifier_solde_suffisant(connexion, id_source, montant)

        compte_dao.debiter(connexion, id_source, montant)
        compte_dao.crediter(connexion, id_destination, montant)

        return self._enregistrer(
            connexion,
            from_id=id_source,
            to_id=id_destination,
            type_t='virement_entre_personnes',
            montant=montant,
            libelle=libelle
        )

    def virement_externe(self, connexion, id_compte, montant, direction,
                          nom_banque, numero_externe, libelle, compte_dao):
        """
        Simule un virement depuis ou vers une banque externe.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_compte (str) : UUID du compte DragonBank.
            montant         : Montant (Decimal).
            direction (str) : 'outgoing' ou 'incoming'.
            nom_banque (str): Nom de la banque externe.
            numero_externe  : Numero de compte externe.
            libelle (str)   : Description.
            compte_dao      : Instance de CompteDAO.

        Returns:
            dict: La transaction creee.

        Raises:
            ValueError: Si le solde est insuffisant (direction outgoing).
        """
        if direction == 'outgoing':
            self._verifier_solde_suffisant(connexion, id_compte, montant)
            compte_dao.debiter(connexion, id_compte, montant)
            from_id = id_compte
            to_id   = None
        else:
            compte_dao.crediter(connexion, id_compte, montant)
            from_id = None
            to_id   = id_compte

        return self._enregistrer(
            connexion,
            from_id=from_id,
            to_id=to_id,
            type_t='virement_externe',
            montant=montant,
            libelle=libelle,
            banque_externe=nom_banque,
            numero_externe=numero_externe
        )

    # =========================================================
    # EXPORT CSV
    # =========================================================

    def exporter_csv(self, connexion, id_utilisateur, id_compte=None):
        """
        Genere un fichier CSV de l'historique des transactions.

        Le fichier est encode en UTF-8 avec BOM (utf-8-sig) pour
        une compatibilite optimale avec Microsoft Excel sous Windows.
        Le separateur est le point-virgule (standard europeen).

        Args:
            connexion       : Connexion PostgreSQL active.
            id_utilisateur  : UUID de l'utilisateur.
            id_compte (str) : Restreindre a un compte (optionnel).

        Returns:
            flask.Response: Reponse HTTP avec le fichier CSV en piece jointe.
        """
        if id_compte:
            curseur = connexion.cursor()
            curseur.execute(
                """
                SELECT t.created_at, t.transaction_type, t.description,
                       t.amount, t.status,
                       fa.account_number AS from_account,
                       ta.account_number AS to_account,
                       t.external_bank_name
                FROM transactions t
                LEFT JOIN accounts fa ON t.from_account_id = fa.id
                LEFT JOIN accounts ta ON t.to_account_id = ta.id
                WHERE (t.from_account_id = %s OR t.to_account_id = %s)
                ORDER BY t.created_at DESC
                """,
                (id_compte, id_compte)
            )
        else:
            curseur = connexion.cursor()
            curseur.execute(
                """
                SELECT t.created_at, t.transaction_type, t.description,
                       t.amount, t.status,
                       fa.account_number AS from_account,
                       ta.account_number AS to_account,
                       t.external_bank_name
                FROM transactions t
                LEFT JOIN accounts fa ON t.from_account_id = fa.id
                LEFT JOIN accounts ta ON t.to_account_id = ta.id
                WHERE (fa.user_id = %s OR ta.user_id = %s)
                ORDER BY t.created_at DESC
                """,
                (id_utilisateur, id_utilisateur)
            )

        lignes = curseur.fetchall()

        sortie  = io.StringIO()
        writer  = csv.writer(sortie, delimiter=';', quoting=csv.QUOTE_ALL)

        writer.writerow([
            'Date', 'Type', 'Libelle', 'Montant (EUR)',
            'Statut', 'Compte source', 'Compte destination', 'Banque externe'
        ])

        for ligne in lignes:
            date = str(ligne['created_at'])[:16].replace('T', ' ') if ligne['created_at'] else ''
            writer.writerow([
                date,
                NOMS_TYPES.get(ligne['transaction_type'], ligne['transaction_type']),
                ligne['description'] or '',
                '{:.2f}'.format(float(ligne['amount'])),
                ligne['status'] or '',
                ligne['from_account'] or '',
                ligne['to_account'] or '',
                ligne['external_bank_name'] or ''
            ])

        contenu = sortie.getvalue()
        sortie.close()

        return Response(
            contenu.encode('utf-8-sig'),
            mimetype='text/csv',
            headers={
                'Content-Disposition': 'attachment; filename="dragonbank_transactions.csv"',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )

    # =========================================================
    # STATISTIQUES
    # =========================================================

    def statistiques(self, connexion, id_utilisateur):
        """
        Calcule les statistiques de transactions du mois courant.

        Args:
            connexion       : Connexion PostgreSQL active.
            id_utilisateur  : UUID de l'utilisateur.

        Returns:
            dict: {transactions_mois, total_envoye, total_recu}
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            SELECT COUNT(*) AS transactions_mois,
                   COALESCE(SUM(CASE WHEN fa.user_id = %s THEN t.amount ELSE 0 END), 0) AS total_envoye,
                   COALESCE(SUM(CASE WHEN ta.user_id = %s THEN t.amount ELSE 0 END), 0) AS total_recu
            FROM transactions t
            LEFT JOIN accounts fa ON t.from_account_id = fa.id
            LEFT JOIN accounts ta ON t.to_account_id = ta.id
            WHERE (fa.user_id = %s OR ta.user_id = %s)
              AND t.created_at >= date_trunc('month', CURRENT_DATE)
              AND t.status = 'completed'
            """,
            (id_utilisateur, id_utilisateur, id_utilisateur, id_utilisateur)
        )
        return curseur.fetchone()

    # =========================================================
    # UTILITAIRES PRIVES
    # =========================================================

    def _verifier_solde_suffisant(self, connexion, id_compte, montant):
        """
        Verifie que le solde du compte est suffisant pour le debit.

        Args:
            connexion  : Connexion PostgreSQL active.
            id_compte  : UUID du compte a verifier.
            montant    : Montant a debiter (Decimal).

        Raises:
            ValueError: Si le solde est inferieur au montant.
        """
        curseur = connexion.cursor()
        curseur.execute('SELECT balance FROM accounts WHERE id = %s', (id_compte,))
        resultat = curseur.fetchone()
        if resultat is None:
            raise ValueError("Compte introuvable")

        solde = decimal.Decimal(str(resultat['balance']))
        if solde < montant:
            raise ValueError(
                "Solde insuffisant (disponible : "
                + '{:.2f}'.format(float(solde)) + " euros)"
            )

    def _enregistrer(self, connexion, from_id, to_id, type_t,
                      montant, libelle, banque_externe=None, numero_externe=None):
        """
        Insere une nouvelle transaction en base de donnees.

        Args:
            connexion        : Connexion PostgreSQL active.
            from_id          : UUID du compte source (ou None).
            to_id            : UUID du compte destination (ou None).
            type_t (str)     : Type de transaction.
            montant          : Montant (Decimal ou float).
            libelle (str)    : Description.
            banque_externe   : Nom de la banque externe (optionnel).
            numero_externe   : Numero de compte externe (optionnel).

        Returns:
            dict: La transaction inseree.
        """
        curseur = connexion.cursor()
        curseur.execute(
            """
            INSERT INTO transactions
                (from_account_id, to_account_id, transaction_type, amount,
                 description, status, external_bank_name,
                 external_account_number, executed_at)
            VALUES (%s, %s, %s, %s, %s, 'completed', %s, %s, NOW())
            RETURNING id, amount, description, status, created_at
            """,
            (from_id, to_id, type_t, float(montant),
             libelle, banque_externe, numero_externe)
        )
        return serialiser_ligne(curseur.fetchone())
