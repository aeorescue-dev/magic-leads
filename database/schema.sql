-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Tabela de Usuários (integra com Supabase Auth)
CREATE TABLE users (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email VARCHAR NOT NULL,
  company_name VARCHAR,
  first_name VARCHAR,
  last_name VARCHAR,
  phone VARCHAR,
  plan VARCHAR NOT NULL DEFAULT 'free', -- 'free' | 'pro' ($99/mês)
  stripe_customer_id VARCHAR UNIQUE,
  stripe_subscription_id VARCHAR UNIQUE,
  subscription_status VARCHAR DEFAULT 'inactive', -- 'active' | 'canceled' | 'past_due'
  subscription_ends_at TIMESTAMP,
  cities_filter TEXT[] DEFAULT ARRAY['NYC'], -- Cidades que acompanha
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  last_login_at TIMESTAMP
);

-- Tabela Principal: Leads
CREATE TABLE leads (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  external_id VARCHAR UNIQUE NOT NULL, -- ID do 311, permit, etc
  source_type VARCHAR NOT NULL, -- '311' | 'permit' | 'tax_delinquency'

  -- Endereço
  address VARCHAR NOT NULL,
  city VARCHAR NOT NULL,
  state VARCHAR NOT NULL,
  zip_code VARCHAR,
  lat FLOAT,
  lng FLOAT,
  county VARCHAR,

  -- Problema
  issue_category VARCHAR NOT NULL, -- 'Roof' | 'Paint' | 'Plumbing' | 'Structure' | 'Grass' | 'Permit_Rejected'
  issue_description TEXT,
  urgency_level VARCHAR DEFAULT 'medium', -- 'low' | 'medium' | 'high'

  -- Proprietário
  owner_name VARCHAR,
  owner_phone VARCHAR,
  owner_email VARCHAR,
  owner_street VARCHAR,
  owner_status VARCHAR DEFAULT 'unknown', -- 'owner-occupied' | 'tenant' | 'unknown'

  -- Datas
  date_reported TIMESTAMP NOT NULL,
  date_first_seen TIMESTAMP DEFAULT NOW(),

  -- Metadata
  image_url VARCHAR,
  source_url VARCHAR,
  is_validated BOOLEAN DEFAULT false,
  validation_error TEXT,

  -- Timestamps
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),

  -- Unique constraint
  UNIQUE(external_id, source_type)
);

-- Índices para performance
CREATE INDEX idx_city_reported ON leads (city, date_reported);
CREATE INDEX idx_source_type ON leads (source_type);
CREATE INDEX idx_category ON leads (issue_category);
CREATE INDEX idx_phone ON leads (owner_phone);

-- Tabela de Interações (Contractor vê lead e contacta)
CREATE TABLE lead_interactions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  interaction_type VARCHAR NOT NULL, -- 'view' | 'contact_sms' | 'contact_call' | 'note'
  notes TEXT,
  contacted_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Row Level Security (RLS)
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE lead_interactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view leads for their cities"
  ON leads FOR SELECT
  USING (
    city = ANY(
      (SELECT cities_filter FROM users WHERE id = auth.uid())
    )
  );

CREATE POLICY "Users can track their own interactions"
  ON lead_interactions FOR SELECT
  USING (user_id = auth.uid());
