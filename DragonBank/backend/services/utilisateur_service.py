"""
DragonBank - Couche Service (Utilisateur)
=========================================
Ce module implémente le pattern 'Service Layer' (Couche Métier).

Choix architecturaux :
1. Séparation des responsabilités (Separation of Concerns) : 
   Les routes Flask (Controllers) ne font que recevoir les requêtes HTTP.
   C'est cette classe Service qui concentre TOUTES les règles métier complexes
   (validation des mots de passe bcrypt, règles de profil, audits de sécurité).
2. Gestion Transactionnelle (ACID) : 
   Chaque méthode du service encapsule l'ouverture et la fermeture de la connexion DB.
   Si une exception survient pendant une mise à jour, le bloc `except` appelle un `conn.rollback()`
   pour garantir que la base de données ne reste jamais dans un état instable.
3. Abstraction des Données (DAO) :
   Le service instancie la classe `UtilisateurDAO` pour lire et écrire les données.
   Il ignore totalement la complexité des requêtes SQL (Pattern Repository/DAO).
"""

from database import creer_connexion, enregistrer_audit
from auth import obtenir_ip_client, verifier_mot_de_passe, hacher_mot_de_passe
from config import CHAMPS_PROFIL_MODIFIABLES
from validators import valider_email, valider_mot_de_passe
from models.utilisateur import UtilisateurDAO

class UtilisateurService:
    def __init__(self):
        self.utilisateur_dao = UtilisateurDAO()

    def obtenir_profil(self, id_utilisateur_courant):
        conn = creer_connexion()
        try:
            utilisateur = self.utilisateur_dao.trouver_par_id(conn, id_utilisateur_courant)
            if not utilisateur:
                raise ValueError('Utilisateur introuvable')
            return utilisateur
        finally:
            conn.close()

    def modifier_profil(self, id_utilisateur_courant, donnees):
        donnees = donnees or {}
        champs = {
            k: v.strip()
            for k, v in donnees.items()
            if k in CHAMPS_PROFIL_MODIFIABLES and isinstance(v, str)
        }
        if not champs:
            raise ValueError('Aucun champ valide a mettre a jour')

        conn = creer_connexion()
        try:
            mis_a_jour = self.utilisateur_dao.mettre_a_jour_profil(conn, id_utilisateur_courant, champs)
            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'UPDATE_PROFILE',
                              {'champs': list(champs.keys())}, obtenir_ip_client())
            conn.commit()
            return mis_a_jour
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def changer_mot_de_passe(self, id_utilisateur_courant, donnees):
        donnees = donnees or {}
        ancien_mot_de_passe = donnees.get('current_password')
        nouveau_mot_de_passe = donnees.get('new_password')
        
        if not ancien_mot_de_passe or not nouveau_mot_de_passe:
            raise ValueError('Le mot de passe actuel et le nouveau mot de passe sont requis')
            
        valider_mot_de_passe(nouveau_mot_de_passe)
        
        conn = creer_connexion()
        try:
            utilisateur = self.utilisateur_dao.trouver_par_id(conn, id_utilisateur_courant)
            if not utilisateur:
                raise ValueError('Utilisateur introuvable')
                
            utilisateur_complet = self.utilisateur_dao.trouver_par_email(conn, utilisateur['email'])
            
            if not verifier_mot_de_passe(ancien_mot_de_passe, utilisateur_complet['password_hash']):
                raise PermissionError('Le mot de passe actuel est incorrect')
                
            nouveau_hash = hacher_mot_de_passe(nouveau_mot_de_passe)
            self.utilisateur_dao.mettre_a_jour_mot_de_passe(conn, id_utilisateur_courant, nouveau_hash)
            
            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'UPDATE_PASSWORD', {}, obtenir_ip_client())
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def changer_email(self, id_utilisateur_courant, donnees):
        donnees = donnees or {}
        mot_de_passe = donnees.get('password')
        nouvel_email = donnees.get('new_email')
        
        if not mot_de_passe or not nouvel_email:
            raise ValueError('Le mot de passe et le nouvel email sont requis')
            
        email_valide = valider_email(nouvel_email)
        
        conn = creer_connexion()
        try:
            utilisateur = self.utilisateur_dao.trouver_par_id(conn, id_utilisateur_courant)
            if not utilisateur:
                raise ValueError('Utilisateur introuvable')
                
            if utilisateur['email'] == email_valide:
                raise ValueError("Le nouvel email est identique a l'actuel")
                
            if self.utilisateur_dao.email_existe(conn, email_valide):
                raise ValueError('Cette adresse email est deja utilisee')
                
            utilisateur_complet = self.utilisateur_dao.trouver_par_email(conn, utilisateur['email'])
            if not verifier_mot_de_passe(mot_de_passe, utilisateur_complet['password_hash']):
                raise PermissionError('Mot de passe incorrect')
                
            self.utilisateur_dao.mettre_a_jour_email(conn, id_utilisateur_courant, email_valide)
            
            enregistrer_audit(conn.cursor(), id_utilisateur_courant, 'UPDATE_EMAIL', 
                              {'ancien': utilisateur['email'], 'nouveau': email_valide}, 
                              obtenir_ip_client())
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
