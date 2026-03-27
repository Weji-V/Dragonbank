"""
DragonBank - Simulateur d'Epargne
===================================
Classe de logique pure pour la simulation de croissance d'epargne.

Cette classe ne fait aucun acces a la base de donnees.
Elle contient uniquement les formules mathematiques de calcul
des interets composes avec versements mensuels reguliers.

Version : 3.0
"""


class Simulateur:
    """
    Calcule la croissance d'un capital epargne par interets composes.

    Formule appliquee pour chaque mois :
        solde = solde * (1 + taux_mensuel) + versement_mensuel

    Ou taux_mensuel = taux_annuel / 100 / 12.

    Cette approche modelise les interets composes mensuels,
    qui correspondent au fonctionnement reel du Livret A et
    de l'assurance vie en fonds euros.
    """

    def simuler(self, capital_initial, taux_annuel, duree_annees,
                versement_mensuel=0.0):
        """
        Simule la croissance d'un capital sur une duree donnee.

        Calcule le capital annee par annee en appliquant les
        interets composes chaque mois et en ajoutant les versements.

        Args:
            capital_initial (float)  : Montant de depart en euros.
            taux_annuel (float)      : Taux d'interet annuel en %.
            duree_annees (int)       : Duree de la simulation en annees.
            versement_mensuel (float): Versement mensuel regulier (defaut: 0).

        Returns:
            dict: Resultats complets de la simulation :
                - capital_initial (float)   : Mise de depart.
                - taux_annuel (float)       : Taux utilise.
                - duree_annees (int)        : Duree de la simulation.
                - versement_mensuel (float) : Versement mensuel.
                - capital_final (float)     : Capital total a la fin.
                - total_verse (float)       : Somme totale versee (capital + versements).
                - total_interets (float)    : Interets generes.
                - gain_pourcentage (float)  : Gain en % par rapport au total verse.
                - courbe (list[dict])       : Evolution annee par annee.
        """
        taux_mensuel  = taux_annuel / 100.0 / 12.0
        solde_courant = float(capital_initial)
        total_verse   = float(capital_initial)
        courbe        = []

        for annee in range(1, duree_annees + 1):
            solde_courant, total_verse = self._calculer_annee(
                solde_courant, total_verse, taux_mensuel, versement_mensuel
            )

            courbe.append({
                'annee':       annee,
                'solde':       round(solde_courant, 2),
                'total_verse': round(total_verse, 2),
                'interets':    round(solde_courant - total_verse, 2)
            })

        capital_final  = round(solde_courant, 2)
        total_interets = round(solde_courant - total_verse, 2)
        gain_pct       = round((total_interets / max(total_verse, 1)) * 100, 2)

        return {
            'capital_initial':   capital_initial,
            'taux_annuel':       taux_annuel,
            'duree_annees':      duree_annees,
            'versement_mensuel': versement_mensuel,
            'capital_final':     capital_final,
            'total_verse':       round(total_verse, 2),
            'total_interets':    total_interets,
            'gain_pourcentage':  gain_pct,
            'courbe':            courbe
        }

    # =========================================================
    # UTILITAIRE PRIVE
    # =========================================================

    def _calculer_annee(self, solde, total_verse, taux_mensuel, versement_mensuel):
        """
        Calcule le solde et le total verse apres 12 mois.

        Applique la formule des interets composes mois par mois,
        puis ajoute le versement mensuel.

        Args:
            solde (float)           : Solde en debut d'annee.
            total_verse (float)     : Total deja verse en debut d'annee.
            taux_mensuel (float)    : Taux mensuel (taux_annuel / 12 / 100).
            versement_mensuel (float): Versement ajoute chaque mois.

        Returns:
            tuple: (nouveau_solde, nouveau_total_verse) apres 12 mois.
        """
        for mois in range(12):
            if taux_mensuel > 0:
                solde = solde * (1.0 + taux_mensuel)
            solde        = solde + versement_mensuel
            total_verse  = total_verse + versement_mensuel

        return solde, total_verse
