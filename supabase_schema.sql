-- Supabase schema for Czar Trend Intelligence
-- Run this in the Supabase SQL Editor to create the tables

-- Posts table
CREATE TABLE IF NOT EXISTS raw_posts (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,          -- 'hn' | 'reddit' | 'twitter' | 'youtube' | 'github'
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL,
    text TEXT,
    url TEXT,
    score DOUBLE PRECISION DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_posts_source ON raw_posts(source);
CREATE INDEX IF NOT EXISTS idx_posts_created ON raw_posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_score ON raw_posts(score DESC);

-- Topics table
CREATE TABLE IF NOT EXISTS topics (
    run_id TEXT NOT NULL,
    topic_id INTEGER NOT NULL,
    label TEXT,
    keywords JSONB DEFAULT '[]'::jsonb,
    post_ids JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (run_id, topic_id)
);

-- Topic scores table
CREATE TABLE IF NOT EXISTS topic_scores (
    run_id TEXT NOT NULL,
    topic_id INTEGER NOT NULL,
    score_date DATE NOT NULL,
    velocity DOUBLE PRECISION DEFAULT 0,
    novelty DOUBLE PRECISION DEFAULT 0,
    volume INTEGER DEFAULT 0,
    inflection BOOLEAN DEFAULT FALSE,
    driver TEXT,
    PRIMARY KEY (run_id, topic_id, score_date)
);

-- Enable Row Level Security (public read for now)
ALTER TABLE raw_posts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read access" ON raw_posts FOR SELECT USING (true);
CREATE POLICY "Service role insert" ON raw_posts FOR INSERT WITH CHECK (true);

ALTER TABLE topics ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read access" ON topics FOR SELECT USING (true);

ALTER TABLE topic_scores ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read access" ON topic_scores FOR SELECT USING (true);
