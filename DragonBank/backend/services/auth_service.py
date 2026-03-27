from database import creer_connexion, enregistrer_audit
from auth import generer_token, obtenir_ip_client
from validators import valider_champs_obligatoires, valider_email, valider_mot_de_passe
from models.utilisateur import UtilisateurDAO
from models.compte import CompteDAO

class AuthService:
    def __init__(self):
        self.utilisateur_dao = UtilisateurDAO()
        self.compte_dao = CompteDAO()

    def inscrire(self, donnees):
        conn = creer_connexion()
        try:
            valider_champs_obligatoires(donnees, ['email', 'password', 'first_name', 'last_name'])
            email = valider_email(donnees['email'])
            valider_mot_de_passe(donnees['password'])

            if self.utilisateur_dao.email_existe(conn, email):
                raise ValueError('Cette adresse email est deja associee a un compte')

            utilisateur = self.utilisateur_dao.creer(
                conn, email, donnees['password'],
                donnees['first_name'].strip(),
                donnees['last_name'].strip(),
                donnees.get('phone', '').strip() or None,
                donnees.get('address', '').strip() or None,
                donnees.get('date_of_birth') or None
            )

            compte = self.compte_dao.ouvrir(conn, utilisateur['id'], 'courant')

            enregistrer_audit(conn.cursor(), utilisateur['id'], 'REGISTER', {
                'email': email, 'account_number': compte['account_number']
            }, obtenir_ip_client())

            conn.commit()
            token = generer_token(utilisateur['id'], email)

            return {
                'message': 'Inscription reussie ! Bienvenue chez DragonBank.',
                'user': utilisateur,
                'token': token,
                'account_number': compte['account_number']
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def connecter(self, donnees):
        if not donnees or not donnees.get('email') or not donnees.get('password'):
            raise ValueError('Email et mot de passe requis')

        conn = creer_connexion()
        try:
            email = donnees['email'].strip().lower()
            utilisateur = self.utilisateur_dao.authentifier(conn, email, donnees['password'])

            if not utilisateur:
                raise PermissionError('Email ou mot de passe incorrect')

            self.utilisateur_dao.mettre_a_jour_derniere_connexion(conn, str(utilisateur['id']))
            enregistrer_audit(conn.cursor(), str(utilisateur['id']), 'LOGIN',
                              {'ip': obtenir_ip_client()}, obtenir_ip_client())
            conn.commit()

            return {
                'message': 'Connexion reussie',
                'token': generer_token(utilisateur['id'], utilisateur['email']),
                'user': {
                    'id': str(utilisateur['id']),
                    'email': utilisateur['email'],
                    'first_name': utilisateur['first_name'],
                    'last_name': utilisateur['last_name']
                }
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
