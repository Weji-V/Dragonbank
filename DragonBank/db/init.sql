-- ============================================
-- DragonBank - Schéma de Base de Données
-- ============================================

-- Extension pour UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================
-- TABLE: Utilisateurs
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    address TEXT,
    date_of_birth DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP WITH TIME ZONE
);

-- ============================================
-- TABLE: Types de Comptes
-- ============================================
CREATE TYPE account_type AS ENUM ('courant', 'livret_a', 'assurance_vie');
CREATE TYPE account_status AS ENUM ('active', 'closed', 'frozen');

-- ============================================
-- TABLE: Comptes Bancaires
-- ============================================
CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_number VARCHAR(20) UNIQUE NOT NULL,
    account_type account_type NOT NULL DEFAULT 'courant',
    balance DECIMAL(15, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(3) DEFAULT 'EUR',
    status account_status DEFAULT 'active',
    interest_rate DECIMAL(5, 4) DEFAULT 0.0000,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT positive_balance CHECK (balance >= 0)
);

-- ============================================
-- TABLE: Bénéficiaires
-- ============================================
CREATE TYPE beneficiary_status AS ENUM ('pending', 'approved', 'rejected');

CREATE TABLE IF NOT EXISTS beneficiaries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    beneficiary_name VARCHAR(200) NOT NULL,
    bank_name VARCHAR(200) DEFAULT 'DragonBank',
    account_number VARCHAR(34) NOT NULL,
    iban VARCHAR(34),
    bic VARCHAR(11),
    status beneficiary_status DEFAULT 'approved',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, account_number)
);

-- ============================================
-- TABLE: Transactions / Virements
-- ============================================
CREATE TYPE transaction_type AS ENUM (
    'virement_interne',
    'virement_entre_personnes', 
    'virement_externe',
    'depot',
    'retrait',
    'interets'
);

CREATE TYPE transaction_status AS ENUM ('pending', 'completed', 'failed', 'cancelled');

CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    from_account_id UUID REFERENCES accounts(id),
    to_account_id UUID REFERENCES accounts(id),
    transaction_type transaction_type NOT NULL,
    amount DECIMAL(15, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'EUR',
    description TEXT,
    status transaction_status DEFAULT 'pending',
    reference VARCHAR(50) UNIQUE DEFAULT uuid_generate_v4()::text,
    external_bank_name VARCHAR(200),
    external_account_number VARCHAR(34),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    executed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT positive_amount CHECK (amount > 0)
);

-- ============================================
-- TABLE: Historique des Intérêts
-- ============================================
CREATE TABLE IF NOT EXISTS interest_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    amount DECIMAL(15, 2) NOT NULL,
    rate DECIMAL(5, 4) NOT NULL,
    balance_before DECIMAL(15, 2) NOT NULL,
    balance_after DECIMAL(15, 2) NOT NULL,
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- TABLE: Sessions (pour la sécurité)
-- ============================================
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(500) NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

-- ============================================
-- TABLE: Logs d'audit
-- ============================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    details JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- INDEX pour performance
-- ============================================
CREATE INDEX idx_accounts_user_id ON accounts(user_id);
CREATE INDEX idx_transactions_from ON transactions(from_account_id);
CREATE INDEX idx_transactions_to ON transactions(to_account_id);
CREATE INDEX idx_transactions_status ON transactions(status);
CREATE INDEX idx_transactions_created ON transactions(created_at);
CREATE INDEX idx_beneficiaries_user_id ON beneficiaries(user_id);
CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_token ON sessions(token);
CREATE INDEX idx_audit_user_id ON audit_logs(user_id);

-- ============================================
-- FONCTION: Générer un numéro de compte
-- ============================================
CREATE OR REPLACE FUNCTION generate_account_number()
RETURNS VARCHAR(20) AS $$
DECLARE
    new_number VARCHAR(20);
    prefix VARCHAR(4) := 'DRG';
BEGIN
    new_number := prefix || LPAD(FLOOR(RANDOM() * 10000000000)::TEXT, 13, '0');
    WHILE EXISTS (SELECT 1 FROM accounts WHERE account_number = new_number) LOOP
        new_number := prefix || LPAD(FLOOR(RANDOM() * 10000000000)::TEXT, 13, '0');
    END LOOP;
    RETURN new_number;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- FONCTION: Mise à jour du timestamp
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers
CREATE TRIGGER update_users_timestamp
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_accounts_timestamp
    BEFORE UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================
-- DONNÉES DE TEST
-- ============================================

-- Utilisateur de test (mot de passe: "password123")
INSERT INTO users (id, email, password_hash, first_name, last_name, phone, address, date_of_birth) 
VALUES (
    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
    'jean.dupont@email.com',
    '$2b$12$LJ3m4ys3GZ5aJfrRkOmU0OYm0MqfGBCqGY5nS5B1VZHvMKvSG1IHa',
    'Jean',
    'Dupont',
    '+33612345678',
    '12 Rue de la Paix, 75001 Paris',
    '1990-05-15'
);

-- Deuxième utilisateur de test
INSERT INTO users (id, email, password_hash, first_name, last_name, phone, address, date_of_birth)
VALUES (
    'b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22',
    'marie.martin@email.com',
    '$2b$12$LJ3m4ys3GZ5aJfrRkOmU0OYm0MqfGBCqGY5nS5B1VZHvMKvSG1IHa',
    'Marie',
    'Martin',
    '+33698765432',
    '5 Avenue des Champs-Élysées, 75008 Paris',
    '1985-11-20'
);

-- Comptes bancaires de test
INSERT INTO accounts (user_id, account_number, account_type, balance, interest_rate)
VALUES 
    ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'DRG0000000001234', 'courant', 5000.00, 0.0000),
    ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'DRG0000000001235', 'livret_a', 15000.00, 0.0300),
    ('b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22', 'DRG0000000005678', 'courant', 3200.00, 0.0000),
    ('b1eebc99-9c0b-4ef8-bb6d-6bb9bd380a22', 'DRG0000000005679', 'assurance_vie', 25000.00, 0.0200);

-- Bénéficiaire de test
INSERT INTO beneficiaries (user_id, beneficiary_name, bank_name, account_number)
VALUES 
    ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'Marie Martin', 'DragonBank', 'DRG0000000005678');

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO dragonadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO dragonadmin;