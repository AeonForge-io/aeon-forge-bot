-- Rollback NFT Tracking Tables
-- Migration: 006_nft_tracking_down.sql
-- Purpose: Remove all NFT tracking tables

-- Drop tables in reverse order due to foreign key constraints
DROP TABLE IF EXISTS nft_marketplace_state;
DROP TABLE IF EXISTS nft_sales;
DROP TABLE IF EXISTS nft_listings;
DROP TABLE IF EXISTS nft_burns;
DROP TABLE IF EXISTS nft_transfers;
DROP TABLE IF EXISTS nft_mints;
DROP TABLE IF EXISTS nft_collections;
