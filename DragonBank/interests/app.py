"""
DragonBank - Service de Calcul des Intérêts
============================================
Service indépendant qui calcule et applique les intérêts
sur les comptes épargne (Livret A, Assurance Vie).

Bonus: +3% journalier sur les comptes épargne.
"""

import os
import time
import decimal
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import schedule

# ============================================
# CONFIGURATION
# ============================================
DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://dragonadmin:dragonpass@db:5432/dragonbank'
)
INTEREST_RATE_LIVRET_A = float(os.environ.get('INTEREST_RATE_LIVRET_A', 0.03))
INTEREST_RATE_ASSURANCE_VIE = float(os.environ.get('INTEREST_RATE_ASSURANCE_VIE', 0.02))
INTERVAL_SECONDS = int(os.environ.get('INTERVAL_SECONDS', 86400))  # 24h par défaut


def get_db_connection():
    """Crée une connexion à la base de données."""
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    return conn


def calculate_interests():
    """
    Calcule et applique les intérêts sur tous les comptes épargne actifs.
    
    - Livret A: INTEREST_RATE_LIVRET_A (par défaut 3%)
    - Assurance Vie: INTEREST_RATE_ASSURANCE_VIE (par défaut 2%)
    """
    print(f"\n{'='*60}")
    print(f"🐉 CALCUL DES INTÉRÊTS - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}")
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Récupérer tous les comptes épargne actifs
        cur.execute('''
            SELECT id, user_id, account_number, account_type, balance, interest_rate
            FROM accounts
            WHERE status = 'active'
            AND account_type IN ('livret_a', 'assurance_vie')
            AND balance > 0
        ''')
        
        accounts = cur.fetchall()
        total_interest_paid = decimal.Decimal('0.00')
        accounts_processed = 0
        
        for account in accounts:
            account_id = str(account['id'])
            balance = decimal.Decimal(str(account['balance']))
            account_type = account['account_type']
            
            # Déterminer le taux d'intérêt
            if account_type == 'livret_a':
                rate = decimal.Decimal(str(INTEREST_RATE_LIVRET_A))
            elif account_type == 'assurance_vie':
                rate = decimal.Decimal(str(INTEREST_RATE_ASSURANCE_VIE))
            else:
                continue
            
            # Calculer les intérêts
            interest_amount = (balance * rate).quantize(decimal.Decimal('0.01'))
            
            if interest_amount <= 0:
                continue
            
            new_balance = balance + interest_amount
            
            # Appliquer les intérêts
            cur.execute(
                'UPDATE accounts SET balance = %s, updated_at = NOW() WHERE id = %s',
                (float(new_balance), account_id)
            )
            
            # Enregistrer dans l'historique des intérêts
            cur.execute('''
                INSERT INTO interest_history 
                (account_id, amount, rate, balance_before, balance_after)
                VALUES (%s, %s, %s, %s, %s)
            ''', (
                account_id,
                float(interest_amount),
                float(rate),
                float(balance),
                float(new_balance)
            ))
            
            # Créer une transaction pour traçabilité
            cur.execute('''
                INSERT INTO transactions 
                (to_account_id, transaction_type, amount, description, status, executed_at)
                VALUES (%s, 'interets', %s, %s, 'completed', NOW())
            ''', (
                account_id,
                float(interest_amount),
                f"Intérêts {account_type.replace('_', ' ').title()} ({float(rate)*100:.1f}%)"
            ))
            
            total_interest_paid += interest_amount
            accounts_processed += 1
            
            print(f"  ✅ {account['account_number']} ({account_type}): "
                  f"{float(balance):.2f}€ → {float(new_balance):.2f}€ "
                  f"(+{float(interest_amount):.2f}€ à {float(rate)*100:.1f}%)")
        
        conn.commit()
        
        print(f"\n📊 Résumé:")
        print(f"   Comptes traités: {accounts_processed}")
        print(f"   Total intérêts versés: {float(total_interest_paid):.2f}€")
        print(f"{'='*60}\n")
        
    except Exception as e:
        conn.rollback()
        print(f"  ❌ ERREUR lors du calcul des intérêts: {e}")
    finally:
        conn.close()


def main():
    """Point d'entrée principal du service d'intérêts."""
    print("🐉" + "="*58)
    print("   DragonBank - Service de Calcul des Intérêts")
    print("="*60)
    print(f"   Taux Livret A:       {INTEREST_RATE_LIVRET_A*100:.1f}% / cycle")
    print(f"   Taux Assurance Vie:  {INTEREST_RATE_ASSURANCE_VIE*100:.1f}% / cycle")
    print(f"   Intervalle:          {INTERVAL_SECONDS} secondes")
    print(f"   Database:            {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'configured'}")
    print("="*60)
    
    # Attendre que la DB soit prête
    print("\n⏳ Attente de la connexion à la base de données...")
    max_retries = 30
    for i in range(max_retries):
        try:
            conn = get_db_connection()
            conn.close()
            print("✅ Connexion à la base de données établie !")
            break
        except Exception as e:
            if i < max_retries - 1:
                print(f"   Tentative {i+1}/{max_retries} échouée: {e}")
                time.sleep(2)
            else:
                print(f"❌ Impossible de se connecter à la DB après {max_retries} tentatives")
                return
    
    # Premier calcul immédiat
    print("\n🚀 Premier calcul des intérêts...")
    calculate_interests()
    
    # Planifier les calculs suivants
    # Pour la démo, on peut réduire l'intervalle
    if INTERVAL_SECONDS < 3600:
        # Si intervalle court (démo), utiliser un simple sleep
        print(f"\n⏰ Mode démo: calcul toutes les {INTERVAL_SECONDS} secondes")
        while True:
            time.sleep(INTERVAL_SECONDS)
            calculate_interests()
    else:
        # En production, calcul journalier
        schedule.every(INTERVAL_SECONDS).seconds.do(calculate_interests)
        print(f"\n⏰ Prochain calcul dans {INTERVAL_SECONDS} secondes")
        
        while True:
            schedule.run_pending()
            time.sleep(60)


if __name__ == '__main__':
    main()